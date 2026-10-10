"""The bridge: one process that is both the workflow worker and the device API.

    uv run python -m dungeon_master.bridge.server

Hosting the worker here is the point. The workflow has to be executed by
*something* on this machine, so the bridge is not an extra moving part -- it is
the process that was required anyway, with an HTTP endpoint bolted on.

Endpoints, kept deliberately boring so an ESP32 can speak them:

    GET  /ping                  liveness. No game, no Catalyst. Rung 1.
    GET  /scene?slot=cyd-1      the current screen, pre-wrapped
    POST /command               {"slot":"cyd-1","k":"n"} -> the next screen

Plain HTTP on the LAN, no TLS, no auth token: the device holds no credential,
and this listens on a private network. If that ever stops being true, put a
shared secret in a header before putting it on a routable address.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..engine import engine
from . import layout

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

HOST = os.environ.get("DM_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("DM_BRIDGE_PORT", "8080"))
REST_SECONDS = int(float(os.environ.get("DM_REST_SECONDS", "20")))

# Which button maps to which typed command. The device sends a key, never prose,
# so the game's parser is only ever handed input it already understands.
DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west"}

_client = None
_runtime = None
_lock = threading.Lock()
# Last full prose per slot, so a "more" tap does not cost a turn.
_full_prose: dict[str, list[str]] = {}


def _start_worker():
    """Register the workflow and start polling Catalyst for work."""
    global _client, _runtime
    from dapr.ext.workflow import DaprWorkflowClient

    from ..workflow import workflow as wf

    # Reuse the front end's own registration rather than repeating it: it
    # registers the workflow under an explicit name and every activity by the
    # name the orchestrator calls it by, which is easy to get subtly wrong twice.
    _runtime = wf.build_runtime()
    _runtime.start()
    _client = DaprWorkflowClient()
    log.info("worker up; workflow registered")


def _exit_buttons(scene: dict) -> list[dict]:
    """Turn 'north — The Collapsed Entry' into a button.

    The label is the destination once walked and 'unexplored' before, which is
    the game's own rule about exits naming where they go; the device just draws
    whatever it is handed.
    """
    out = []
    for line in scene.get("exits") or []:
        m = re.match(r"\s*(north|south|east|west)\s*[—-]\s*(.+)", str(line))
        if not m:
            continue
        where = m.group(2).strip()
        # Drop a leading "The ": four characters of nothing, on a button that
        # has about eighteen.
        if where.lower().startswith("the "):
            where = where[4:]
        letter = m.group(1)[0].upper()
        # The letter leads, so the direction is readable at a glance -- the
        # destination name alone does not say which way it is.
        out.append({"k": letter.lower(), "label": f"{letter}  {where}",
                    "dir": True})
    return out


def _menu_buttons(scene: dict) -> list[dict]:
    """Numbered choices. The count changes per scene, because a choice already
    taken disappears -- so the device must lay these out dynamically."""
    # wide: a full row each. These labels are sentences.
    return [{"k": str(i), "label": label, "wide": True}
            for i, label in enumerate(scene.get("menu") or [], 1)]


def _compact_hud(hud: str) -> str:
    """Squeeze the terminal's HUD onto 240 pixels.

    "health 11/30   gold 17   carrying: ashen lodestone" is about 50
    characters, which at the measured 6.3px per character is 315px on a 240px
    panel -- so the terminal's own line is cut off at "carrying: a". The same
    facts fit in 30.
    """
    m = re.search(r"health\s+(\d+)/(\d+)", hud or "")
    hp = f"{m.group(1)}/{m.group(2)}hp" if m else ""
    g = re.search(r"gold\s+(\d+)", hud or "")
    gold = f"{g.group(1)}g" if g else ""
    c = re.search(r"carrying:\s*(.+?)\s*$", hud or "")
    carry = (c.group(1) if c else "").strip()
    if carry == "nothing":
        carry = ""
    return "  ".join(x for x in (hp, gold, carry) if x)


def _screen(slot: str, scene: dict, ended: bool = False) -> dict:
    buttons = _exit_buttons(scene) + _menu_buttons(scene)
    if not ended:
        buttons.append({"k": "look", "label": "look", "dir": True})
    prose = scene.get("prose") or ""
    _full_prose[slot] = layout.wrap(prose)
    out = layout.compose(scene.get("title") or "", scene.get("verbatim") or [],
                         prose, buttons)
    # A "more" button, because the prose that did not fit is otherwise
    # unreachable -- an ellipsis the player cannot tap is just a tease.
    if out.get("more") and not ended:
        buttons.append({"k": "more", "label": "more...", "dir": True})
        out["buttons"] = buttons
    out.update({
        "seq": scene.get("seq", 0),
        "hud": _compact_hud(scene.get("hud") or ""),
        "ended": bool(ended or scene.get("ended")),
        "slot": slot,
    })
    return out


def _ensure_run(slot: str) -> dict:
    """Resume this slot's adventure, or begin one. One slot, one save."""
    from ..workflow import cli as wcli

    state = _client.get_workflow_state(slot)
    running = state is not None and state.runtime_status not in wcli.TERMINAL_STATES
    if not running:
        from ..workflow import workflow as wf
        _client.schedule_new_workflow(
            workflow=wf.dungeon_master,
            input={"rest_seconds": REST_SECONDS},
            instance_id=slot,
        )
        scene, _ = wcli.wait_for_scene(_client, slot, 0, "opening", timeout=90)
        return _screen(slot, scene or {})

    scene = wcli._decode_status(state.serialized_custom_status)
    return _screen(slot, scene or {})


def _do_command(slot: str, key: str) -> dict:
    from ..workflow import cli as wcli

    key = (key or "").strip().lower()
    if key == "more":
        # Not a turn: hand back the prose the screen could not fit.
        lines = _full_prose.get(slot) or []
        return {"title": "", "rule": [], "prose": lines, "more": False,
                "buttons": [{"k": "back", "label": "back", "dir": True}], "seq": -1,
                "hud": "", "ended": False, "slot": slot}
    if key == "back":
        return _ensure_run(slot)

    command = DIRECTIONS.get(key) or ("look" if key == "look" else key)

    state = _client.get_workflow_state(slot)
    if state is None or state.runtime_status in wcli.TERMINAL_STATES:
        return _ensure_run(slot)
    before = (wcli._decode_status(state.serialized_custom_status) or {}).get("seq", 0)

    wcli.send(_client, slot, command)
    scene, output = wcli.wait_for_scene(_client, slot, before, "turn", timeout=120)
    if scene is None:
        return {"error": "the dungeon did not answer", "slot": slot}
    return _screen(slot, scene, ended=output is not None)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/ping":
            self._send({"ok": True, "game": "dungeon-master", "t": int(time.time())})
            return
        if u.path == "/scene":
            slot = (parse_qs(u.query).get("slot") or ["cyd-1"])[0]
            with _lock:
                self._send(_ensure_run(slot))
            return
        self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/command":
            self._send({"error": "not found"}, 404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            self._send({"error": "bad json"}, 400)
            return
        slot = str(req.get("slot") or "cyd-1")
        with _lock:
            self._send(_do_command(slot, str(req.get("k") or "")))

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def main() -> None:
    _start_worker()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("bridge listening on http://%s:%d", HOST, PORT)
    log.info("device endpoints: GET /ping  GET /scene?slot=cyd-1  POST /command")
    try:
        srv.serve_forever()
    finally:
        if _runtime:
            _runtime.shutdown()


if __name__ == "__main__":
    main()

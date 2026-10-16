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

from ..engine import engine, world
from . import layout

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

HOST = os.environ.get("DM_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("DM_BRIDGE_PORT", "8080"))
REST_SECONDS = int(float(os.environ.get("DM_REST_SECONDS", "20")))

# Ask the narrator for prose this screen can actually show. After the title,
# the HUD, the buttons and the rule lines there is often room for only five
# short lines -- about 180 characters -- so requesting 2-4 sentences produces
# text the player never sees. One or two is the honest ask for a 240x320 panel.
os.environ.setdefault("DM_PROSE_LENGTH", "1-2 short sentences")

# Which button maps to which typed command. The device sends a key, never prose,
# so the game's parser is only ever handed input it already understands.
DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west"}

_client = None
_runtime = None
_lock = threading.Lock()
# slot -> the workflow instance currently holding that slot's adventure.
# A slot is NOT an instance id: see _instance_for.
_instance: dict[str, str] = {}
# Last full prose per slot, so a "more" tap does not cost a turn.
_full_prose: dict[str, list[str]] = {}
# Last full screen served per slot. When Catalyst cannot be reached this is
# served instead of an error: at a booth a two-second blip would otherwise put
# "is the bridge running?" on the board, which is alarming and, since the
# bridge is fine, untrue. The uplink is the one thing a booth cannot promise.
_last_screen: dict[str, dict] = {}


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
    # The vault's picture takes rows off the top, so the budget has to know
    # about it. Previously the art was handled by blanking the prose outright,
    # which left the screen showing a drawing and no words at all.
    art_rows = layout.ART_ROWS if scene.get("room") == world.VAULT_ROOM else 0
    out = layout.compose(scene.get("title") or "", scene.get("verbatim") or [],
                         prose, buttons, art_rows=art_rows)

    # The one illustration in the game, and only where it is the payoff: the
    # vault. Asking for it anywhere else would make it wallpaper, and the
    # dragon is worth more as the thing you finally see. The device draws it
    # from primitives, so this costs one short string.
    if scene.get("room") == world.VAULT_ROOM:
        out["art"] = "vault"
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
    # Only real screens are remembered. The map and the "more" overlay build
    # their own dicts and carry a negative seq (see the device poll), and
    # re-serving one of those after a blip would be a stranger thing to show
    # than the room the player is standing in.
    _last_screen[slot] = out
    return out


def _map_screen(slot: str, scene: dict) -> dict:
    """A fog-of-war map, built from where the player has actually been.

    Three rules, and they are the game's rules rather than drawing decisions:

      * only rooms you have stood in get a name. The game already refuses to
        name an exit you have not walked, and a map that ignored that would
        hand over the layout and make the lodestone pointless.
      * an unexplored room that adjoins somewhere you HAVE been shows as "?".
        That is the same information the exit list already gives you, drawn in
        two dimensions instead of one.
      * the vault does not appear at all until the door is open. The whole
        point of the secret is that nothing readable gives it away, and a box
        on a map is readable.
    """
    visited = set(scene.get("visited") or [])
    here = scene.get("room")
    door_open = bool(scene.get("door_open"))

    shown: dict[tuple[int, int], dict] = {}
    for rid in visited:
        if rid not in world.ROOMS:
            continue
        x, y = world.ROOMS[rid]["coord"]
        shown[(x, y)] = {"x": x, "y": y, "label": _short(world.ROOMS[rid]["title"]),
                         "seen": True, "here": rid == here}
        # Its neighbours become "?" boxes, unless they are still secret.
        for direction, dest in world.exits_of(rid).items():
            if dest in visited:
                continue
            if dest == world.VAULT_ROOM and not door_open:
                continue            # the secret stays secret
            dx, dy = world.ROOMS[dest]["coord"]
            shown.setdefault((dx, dy), {"x": dx, "y": dy, "label": "?",
                                        "seen": False, "here": False})

    if not shown:
        shown[(0, 0)] = {"x": 0, "y": 0, "label": "?", "seen": False, "here": True}

    xs = [c[0] for c in shown]
    ys = [c[1] for c in shown]
    return {
        "title": "the map",
        "rule": [], "prose": [], "more": False,
        "map": {"x0": min(xs), "y0": min(ys),
                "w": max(xs) - min(xs) + 1, "h": max(ys) - min(ys) + 1,
                "cells": list(shown.values())},
        "buttons": [{"k": "back", "label": "back", "dir": True}],
        "seq": -2,
        # The run id, not the slot: a slot is a device, a run is an adventure,
        # and when a terminal has joined the same adventure this is the line
        # that proves it. 240px at font 2 is about 34 characters.
        "hud": (f"{scene.get('instance') or slot}  "
                f"{_compact_hud(scene.get('hud') or '')}")[:34],
        "ended": False,
        "slot": slot,
    }


def _short(title: str) -> str:
    """Room names, minus the article, for a 72px cell."""
    t = title[4:] if title.lower().startswith("the ") else title
    return t


def _instance_for(slot: str, start_new_if_finished: bool = True) -> str | None:
    """The workflow instance holding this slot's adventure.

    A slot is not an instance id, and this is the whole reason the function
    exists. Dapr lets a TERMINAL instance id be reused, so using the slot
    directly meant that finishing an adventure and beginning the next one
    silently overwrote the finished one's history -- including the
    secret_vault_found record, which is the single thing most worth keeping.
    For a game whose premise is that the history IS the save file, that was the
    worst possible bug to have.

    So adventures are numbered: cyd-1-1, cyd-1-2, ... Finished runs stay put
    and stay readable in the console for as long as they are not purged.

    Returns None only when nothing exists and we were asked not to create one.
    """
    from ..workflow import cli as wcli
    from ..workflow import workflow as wf

    cached = _instance.get(slot)
    if cached:
        st = _client.get_workflow_state(cached)
        if st is not None and st.runtime_status not in wcli.TERMINAL_STATES:
            return cached

    # Walk the numbered runs to find the newest. Only on a cache miss, and
    # only a handful of reads, because adventures are counted from 1.
    newest_n, newest_state = 0, None
    # A bare slot id is an adventure from before numbering existed. Adopt it
    # rather than abandoning someone mid-game.
    legacy = _client.get_workflow_state(slot)
    if legacy is not None and legacy.runtime_status not in wcli.TERMINAL_STATES:
        _instance[slot] = slot
        return slot

    n = 1
    while n < 500:
        st = _client.get_workflow_state(f"{slot}-{n}")
        if st is None:
            break
        newest_n, newest_state = n, st
        n += 1

    if newest_state is not None and newest_state.runtime_status not in wcli.TERMINAL_STATES:
        _instance[slot] = f"{slot}-{newest_n}"
        return _instance[slot]

    if not start_new_if_finished:
        return f"{slot}-{newest_n}" if newest_n else None

    # The previous adventure ended (or there was none). The next one gets its
    # own id, so the ended one survives.
    nxt = f"{slot}-{newest_n + 1}"
    _client.schedule_new_workflow(
        workflow=wf.dungeon_master,
        input={"rest_seconds": REST_SECONDS},
        instance_id=nxt,
    )
    wcli.wait_for_scene(_client, nxt, 0, "opening", timeout=90)
    _instance[slot] = nxt
    log.info("slot %s -> new adventure %s", slot, nxt)
    return nxt


def _ensure_run(slot: str) -> dict:
    """Resume this slot's adventure, or begin the next one."""
    from ..workflow import cli as wcli

    iid = _instance_for(slot)
    state = _client.get_workflow_state(iid)
    scene = wcli._decode_status(state.serialized_custom_status) if state else None
    return _screen(slot, scene or {})


def _poll(slot: str, since: int) -> dict:
    """Has this slot's adventure moved since `since`? The device's background poll.

    Two differences from _ensure_run, and both matter.

    It never starts an adventure. _ensure_run exists to begin the next one, which
    is right when a player taps the screen and wrong every three seconds: a poll
    that created a run would wipe the ending screen and open a fresh dungeon a
    few seconds after someone won.

    And it answers `nochange` rather than the scene, which is almost always the
    answer. The board re-renders nothing and parses 20 bytes instead of 2KB.
    """
    from ..workflow import cli as wcli

    iid = _instance_for(slot, start_new_if_finished=False)
    if iid is None:
        return {"nochange": True}
    state = _client.get_workflow_state(iid)
    scene = wcli._decode_status(state.serialized_custom_status) if state else None
    if not scene or int(scene.get("seq", 0)) == since:
        return {"nochange": True}
    return _screen(slot, scene)


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
    if key == "map":
        # A free action, like `look`: no turn, no event raised, so checking
        # where you are never costs 2 health to the lodestone.
        from ..workflow import cli as wcli
        iid = _instance_for(slot)
        state = _client.get_workflow_state(iid)
        scene = wcli._decode_status(state.serialized_custom_status) if state else None
        if not scene:
            return {"error": "no adventure to map", "slot": slot}
        return _map_screen(slot, scene)

    command = DIRECTIONS.get(key) or ("look" if key == "look" else key)

    iid = _instance_for(slot)
    state = _client.get_workflow_state(iid)
    if state is None or state.runtime_status in wcli.TERMINAL_STATES:
        return _ensure_run(slot)
    before = (wcli._decode_status(state.serialized_custom_status) or {}).get("seq", 0)

    wcli.send(_client, iid, command)
    scene, output = wcli.wait_for_scene(_client, iid, before, "turn", timeout=120)
    if scene is None:
        return {"error": "the dungeon did not answer", "slot": slot}
    if output is not None:
        # Ended. Drop the cached instance so the next command begins a new
        # adventure under a new id, leaving this one's history intact.
        _instance.pop(slot, None)
    return _screen(slot, scene, ended=output is not None)


def _stale(slot: str) -> dict | None:
    """The last screen served to this slot, flagged.

    The board ignores `stale` -- ArduinoJson drops keys it was not asked for --
    so the flag is for the log and for any firmware that later wants to show a
    dot. What matters here is that the glass keeps the screen it had.
    """
    last = _last_screen.get(slot)
    if last is None:
        return None
    out = dict(last)
    out["stale"] = True
    return out


def _poll_or_hold(slot: str, since: int) -> tuple[dict, int]:
    """The background poll. A failure here must be invisible.

    If Catalyst cannot be read we do not know whether the adventure moved, and
    `nochange` is the answer that keeps the board exactly as it is. It polls
    again in three seconds; a blip shorter than that is never seen by anyone.
    """
    try:
        return _poll(slot, since), 200
    except Exception:
        log.warning("poll failed for %s; answering nochange", slot, exc_info=True)
        return {"nochange": True}, 200


def _scene_or_last(slot: str) -> tuple[dict, int]:
    """A full screen request: the board booting, or coming back from an overlay."""
    try:
        return _ensure_run(slot), 200
    except Exception:
        last = _stale(slot)
        log.warning("scene failed for %s; serving %s", slot,
                    "last known screen" if last else "503", exc_info=True)
        if last is not None:
            return last, 200
        return {"error": "upstream unavailable"}, 503


def _command_or_last(slot: str, key: str) -> tuple[dict, int]:
    """A tap. On failure the honest answer is the screen before it.

    The turn did not land, so the previous screen *is* the current state: the
    player sees nothing moved and taps again. In the one case where the event
    reached Catalyst and only the wait for the result failed, the background
    poll corrects the screen within three seconds.
    """
    try:
        return _do_command(slot, key), 200
    except Exception:
        last = _stale(slot)
        log.warning("command %r failed for %s; serving %s", key, slot,
                    "last known screen" if last else "503", exc_info=True)
        if last is not None:
            return last, 200
        return {"error": "upstream unavailable"}, 503


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
            q = parse_qs(u.query)
            slot = (q.get("slot") or ["cyd-1"])[0]
            since = (q.get("since") or [None])[0]
            if since is not None:
                try:
                    n = int(since)
                except (ValueError, TypeError):
                    self._send({"error": "bad since"}, 400)
                    return
                # `since` makes it a poll: cheap, and it never starts a run.
                with _lock:
                    body, code = _poll_or_hold(slot, n)
            else:
                with _lock:
                    body, code = _scene_or_last(slot)
            self._send(body, code)
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
            body, code = _command_or_last(slot, str(req.get("k") or ""))
        self._send(body, code)

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def main() -> None:
    _start_worker()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("bridge listening on http://%s:%d", HOST, PORT)
    log.info("device endpoints: GET /ping  GET /scene?slot=cyd-1[&since=N]  POST /command")
    try:
        srv.serve_forever()
    finally:
        if _runtime:
            _runtime.shutdown()


if __name__ == "__main__":
    main()

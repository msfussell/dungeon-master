"""dungeon-master: play the agent.

    uv run dungeon-master-agent                 resume or start slot dm-<user>
    uv run dungeon-master-agent --new           discard the slot, start over
    uv run dungeon-master-agent --slot NAME     play a named save slot
    uv run dungeon-master-agent --rest 15       shorter campfire, for a demo
    uv run dungeon-master-agent --timeline      print the adventure's history

Must run where DAPR_HTTP_ENDPOINT and DAPR_API_TOKEN are set, which is what
`diagrid dev run` does. The terminal holds no state: the save is the agent's
durable memory, and every turn is a call through Catalyst.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from ..engine import ui
from . import config, narrator
from .client import SPINNERS, rest_poll, spin, turn
from .history import print_timeline

RESET, BOLD, DIM = ui.RESET, ui.BOLD, ui.DIM

BANNER = r"""
   ___                              __  ___         __
  / _ \__ _____  ___ ____ ___  ___ /  |/  /__ ____ / /____ ____
 / // / // / _ \/ _ `/ -_) _ \/ _ \ /|_/ / _ `(_-</ __/ -_) __/
/____/\_,_/_//_/\_,_/\__/\___/_//_/_/  /_/\_,_/___/\__/\__/_/
                        a durable agent on Catalyst
"""


def _render(scene: dict, verbatim: list, prose: str, interpreted_by: str | None) -> None:
    nouns = scene.get("nouns") or []
    print()
    print(ui.c(ui.TITLE, f"══ {scene.get('title')} " + "═" * max(0, 74 - len(scene.get('title') or ''))))
    print()
    # VERBATIM FIRST, and exactly as written. These are the lines that state a
    # rule or an instruction; the model has never seen them.
    for line in verbatim or []:
        print(ui.c(ui.RULE, ui.wrap(line)))
    if verbatim:
        print()
    if prose:
        print(ui.highlight(ui.wrap(prose), nouns))
        print()
    for e in scene.get("exits") or []:
        print(ui.c(ui.EXITS, "  " + e))
    menu = scene.get("menu") or []
    for i, m in enumerate(menu, 1):
        print(ui.c(ui.MENU, f"  {i}) ") + ui.highlight(m, nouns))
    if scene.get("exits") or menu:
        print()
    print(ui.c(ui.HUD, "  " + (scene.get("hud") or "")))
    if interpreted_by == "model":
        # Worth showing once in a while: it is the agent earning its keep.
        print(ui.c(ui.DIM, "  (read by the agent)"))
    print()


def _wait_out_rest(slot: str, rest_seconds: float) -> dict | None:
    """Wait out a campfire, by asking the agent whether it is over.

    The rest is a durable workflow timer, so this loop is only the terminal's
    patience -- killing it does not stop the fire burning down, and the next
    turn (today or tomorrow) picks the waking event up regardless.
    """
    deadline = time.time() + max(900.0, rest_seconds + 300)
    announced = False
    while time.time() < deadline:
        try:
            out = (rest_poll(slot, rest_seconds) or {}).get("output") or {}
        except Exception:
            spin("the fire burns down", 3.0)
            continue
        if not out.get("resting"):
            return out
        if not announced:
            due = out.get("wake_at") or ""
            print(ui.c(ui.NOTICE, ui.wrap(
                "The rest is a durable workflow timer on Catalyst"
                + (f", due at {due}" if due else "")
                + ". You can close this app; the fire still burns down on time, "
                  "and your next turn picks up where it left off.")))
            announced = True
        spin("the fire burns down", 4.0)
    print(ui.c(ui.NOTICE, ui.wrap(
        "Giving up waiting, but the rest is still running on Catalyst. "
        "Start the app again and your next turn will collect it.")))
    return None


def main() -> int:
    ap = argparse.ArgumentParser(prog="dungeon-master-agent")
    ap.add_argument("--slot", default=None, help="save slot (an agent memory key)")
    ap.add_argument("--new", action="store_true", help="discard the slot and start over")
    ap.add_argument("--rest", type=float, default=None, help="campfire seconds")
    ap.add_argument("--timeline", action="store_true", help="print the history and stop")
    args = ap.parse_args()

    slot = args.slot or f"dm-{os.environ.get('USER', 'traveller')}"
    rest_seconds = args.rest if args.rest is not None else config.REST_SECONDS

    if args.timeline:
        return print_timeline(slot)   # fetches the state from the agent itself


    print(ui.c(ui.TITLE, BANNER))
    print(f"  save slot: {BOLD}{slot}{RESET}    narrator: {narrator.model_name()}")
    print(f"  agent: {ui.c(ui.LINK, config.agent_link())}")
    print(ui.rule_line())

    # `--new` is the agent's job: it owns the save, and only its identity can
    # clear it. The first command carries the request.
    first = True
    opening = "__reset__" if args.new else "__resume__"
    while True:
        raw = opening if first else None
        if not first:
            try:
                raw = input(ui.c(ui.BOLD, "> ")).strip()
            except (EOFError, KeyboardInterrupt):
                raw = "save and quit"

        import random
        label = random.choice(SPINNERS)
        result: dict = {}
        try:
            # The call is synchronous: the agent's turn is a workflow run and
            # /agent/run returns when it completes.
            import threading
            box: dict = {}

            def _go():
                try:
                    box["r"] = turn(slot, raw or "", rest_seconds)
                except Exception as exc:
                    box["e"] = exc

            t = threading.Thread(target=_go, daemon=True)
            t.start()
            while t.is_alive():
                spin(label, 0.4)
            if "e" in box:
                raise box["e"]
            result = box.get("r") or {}
        except Exception as exc:
            print(ui.c(ui.NOTICE, f"The dungeon did not answer: {exc}"))
            print(ui.c(ui.DIM, "Is the agent running behind `diagrid dev run`? See README."))
            return 1

        out = result.get("output") or {}
        if result.get("type") == "workflow_failed" or not out:
            print(ui.c(ui.NOTICE, "The agent's turn failed. Its run:"))
            print("  " + ui.c(ui.LINK, config.workflow_link(result.get("workflow_id", "?"))))
            return 1

        scene = out.get("scene") or {}
        verbatim = out.get("verbatim") or []
        prose = out.get("prose") or ""

        if first:
            # One dramatic sentence back into the moment, made client-side so
            # resuming appends nothing to the adventure's history.
            if scene.get("turn"):
                print()
                print(ui.c(ui.RECAP, ui.wrap(narrator.recap(scene, prose))))
            first = False

        _render(scene, verbatim, prose, out.get("interpreted_by"))

        # A rest started this turn: wait on its own durable workflow.
        for run in out.get("runs") or []:
            if run.get("kind") == "campfire_rest":
                # The agent applies the waking event itself when the timer has
                # fired, so the poll that comes back not-resting already
                # carries the result. No __wake__ round trip to get wrong.
                woke = _wait_out_rest(slot, rest_seconds)
                if woke:
                    _render(woke.get("scene") or {}, woke.get("verbatim") or [],
                            woke.get("prose") or "", None)
            if run.get("kind") == "secret_vault_found":
                print(ui.c(ui.WIN, "  ★ recorded as a workflow step named "
                                   "secret_vault_found"))
                print("  " + ui.c(ui.LINK, config.workflow_link(run["id"])))
                print()

        if scene.get("ending"):
            # Hand the agent's own copy of the state to the timeline rather
            # than letting it go looking in a store it cannot read.
            print_timeline(slot, out.get("game"))
            return 0
        if (out.get("game") or {}).get("parked") or scene.get("parked"):
            print(ui.c(ui.NOTICE, "Saved. Start again to pick it up."))
            return 0


if __name__ == "__main__":
    sys.exit(main())

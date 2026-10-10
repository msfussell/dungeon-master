"""The adventure, read back out of Catalyst.

One honest difference from the workflow version of this game. There, the whole
adventure was a single long-lived workflow, so "the timeline from the run
history" meant one run's history. Here each turn is its own durable run, so the
adventure is a *sequence* of runs on the agent's App ID, plus the auxiliary runs
(`secret_vault_found`, `campfire_rest`) that the turns started.

So the timeline is built from the run list for this App ID, which is server
truth, and the typed commands come from the agent's own durable memory. Where
the run list cannot be read, the memory log alone is used and the output says
so on screen rather than quietly presenting a weaker thing as the same thing.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from ..engine import ui
from . import config


def _runs() -> list[dict]:
    """Every run on the agent's App ID, oldest first, via the Diagrid CLI.

    The MCP tools withhold run payloads at the default `metadata` data-sharing
    level; the CLI returns them. Either way the run's *name* is always visible,
    which is what proves `secret_vault_found` happened.
    """
    if not shutil.which("diagrid"):
        return []
    try:
        out = subprocess.run(
            ["diagrid", "workflow", "list", "--project", config.PROJECT],
            capture_output=True, text=True, timeout=60).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[0] != config.AGENT_APP_ID:
            continue
        rows.append({"id": parts[1], "name": parts[2], "start": parts[3],
                     "status": parts[-1]})
    rows.sort(key=lambda r: r["start"])
    return rows


def print_timeline(slot: str, game: dict | None = None) -> int:
    """Print the adventure. `game` comes from the agent, never from its store.

    Dapr prefixes state keys with the writing App ID, so this process -- a
    different identity from the agent -- cannot read the agent's memory even
    though it can name the store. That is the right boundary: the client holds
    no state and asks the agent, which is what makes "save and quit" just an
    exit. When called without a game (the --timeline flag), one free `look`
    turn fetches it; a free action costs no turn and no health.
    """
    if game is None:
        try:
            from .client import turn
            out = (turn(slot, "look", 0.0) or {}).get("output") or {}
            game = out.get("game")
        except Exception:
            game = None

    runs = _runs()
    mine = [r for r in runs if slot in r["id"]]

    print()
    print(ui.c(ui.TITLE, "── Your adventure, read back out of Catalyst " + "─" * 32))
    print()

    if not mine:
        print(ui.c(ui.NOTICE, "  No runs for this slot are visible from here."))
    for r in mine:
        mark = "★" if r["name"] == "secret_vault_found" else (
            "☾" if r["name"] == "campfire_rest" else "·")
        label = r["name"] if r["name"] != f"dapr.langgraph.{_title(config.AGENT_APP_ID)}.workflow" else "a turn"
        print(f"  {ui.c(ui.DIM, r['start'][11:19])}  {mark}  {label}"
              + ("" if r["status"] == "completed" else f"   {ui.c(ui.NOTICE, r['status'])}"))
    print()

    if game:
        print(ui.c(ui.TITLE, "── What you did " + "─" * 61))
        print()
        for entry in game.get("log") or []:
            cmd = entry.get("command") or ""
            if cmd.startswith("__"):
                continue
            print(f"  {ui.c(ui.DIM, 't%2d' % entry.get('turn', 0))}  >  {cmd}")
        print()
        print(ui.c(ui.HUD, "  " + _summary(game)))
        print()
        if game.get("ending") == "vault":
            print(ui.c(ui.WIN, "  ★ Show this run to the Diagrid booth to claim your reward."))
            print()
    else:
        print(ui.c(ui.NOTICE, "  No saved adventure in the agent's memory for this slot."))
        print()

    if not runs:
        print(ui.c(ui.NOTICE, ui.wrap(
            "  (The Diagrid CLI was not available, so the list above came from "
            "the agent's memory rather than from server-side run history.)")))
        print()
    print(ui.c(ui.TITLE, "── This adventure on Catalyst " + "─" * 47))
    print()
    print("  agent: " + ui.c(ui.LINK, config.agent_link()))
    for r in mine:
        if r["name"] in ("secret_vault_found", "campfire_rest"):
            print(f"  {r['name']}: " + ui.c(ui.LINK, config.workflow_link(r["id"])))
    print()
    return 0


def _summary(game: dict) -> str:
    inv = ", ".join(game.get("inventory") or []) or "nothing"
    return (f"ending {game.get('ending') or 'unfinished'}   "
            f"turns {game.get('turn')}   health {game.get('health')}/"
            f"{game.get('max_health')}   gold {game.get('gold')}   "
            f"rests {game.get('rests')}   carrying {inv}")


def _title(name: str) -> str:
    return "".join(p.capitalize() for p in name.replace("-", " ").replace("_", " ").split())

"""The ending timeline, derived from the workflow run history.

HOW THIS IS DERIVED — BE CLEAR ABOUT IT
=======================================
The Dapr Python SDK's `DaprWorkflowClient` does NOT expose run history. It gives
runtime status, custom status and output, and nothing else. So the raw step names and
their timestamps come from Catalyst itself, via the `diagrid` CLI:

    diagrid workflow get <instance> --app-id <app> --project <project>

which prints YAML with a `history:` list, newest event first. Each entry carries a
`date`, an `eventType` (TaskScheduled / TaskCompleted / TimerCreated / TimerFired /
EventRaised / ExecutionStarted / ExecutionCompleted), and for tasks a
`metadata.name` which is the registered activity name. That is the real,
server-side record — not something this app kept on the side.

Two consequences stated plainly:

1. The timeline needs the `diagrid` CLI on PATH and an authenticated session. Without
   it, we fall back to the workflow's own return value (the `log` field, which the
   orchestrator built from the same command sequence) and SAY SO on screen, rather
   than quietly printing something that looks server-derived but is not.
2. Timestamps are Catalyst's, in UTC, exactly as the API reports them.
"""

from __future__ import annotations

import json
import subprocess

import yaml

from ..engine import ui, world
from . import config
from .activities import STORY_ACTIVITIES

# Machinery steps. Real activities, real history entries, but they are the narrator
# turning the handle — not beats of the adventure. Counted, not listed.
MACHINERY = {"narrate_scene", "recap_moment", "campfire_event"}

# How a story step reads in the timeline.
STEP_LABELS = {
    "take_cursed_item": "took the ashen lodestone",
    "secret_vault_found": "SECRET VAULT FOUND",
    "trade_with_merchant": "traded with Hask",
    "cheat_the_merchant": "cheated Hask",
    "settle_the_ledger": "settled the ledger with Hask",
    "campfire_rest_begin": "bedded down at the campfire",
    "claim_durable_scroll": "took the durable scroll",
    "save_and_quit": "saved and quit",
}


def fetch(instance_id: str) -> dict | None:
    """Full run record from Catalyst, or None if the CLI is unavailable."""
    try:
        proc = subprocess.run(
            ["diagrid", "workflow", "get", instance_id,
             "--app-id", config.app_id(), "--project", config.project()],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        doc = yaml.safe_load(proc.stdout)
    except yaml.YAMLError:
        return None
    return doc if isinstance(doc, dict) else None


def _loads(raw):
    """Decode an activity payload, allowing for Dapr's occasional double encoding.

    Only re-decode when the inner string actually looks like JSON: an activity that
    legitimately returns the string "The Hall of Teeth" must not be parsed twice and
    thrown away.
    """
    if not raw:
        return None
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(val, str) and val[:1] in ("{", "["):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return val
    return val


def step_names(instance_id: str, doc: dict | None = None) -> list[str]:
    """Every activity name that actually executed, oldest first. The proof surface."""
    doc = doc if doc is not None else fetch(instance_id)
    if not doc:
        return []
    events = sorted(doc.get("history") or [], key=lambda e: str(e.get("date", "")))
    return [
        (e.get("metadata") or {}).get("name")
        for e in events
        if e.get("eventType") == "TaskCompleted" and (e.get("metadata") or {}).get("name")
    ]


def timeline(instance_id: str, doc: dict | None = None) -> tuple[list[tuple[str, str, str]], int]:
    """Return ([(hh:mm:ss, marker, text)], narration_step_count), oldest first."""
    doc = doc if doc is not None else fetch(instance_id)
    if not doc:
        return [], 0

    events = sorted(doc.get("history") or [], key=lambda e: str(e.get("date", "")))
    rows: list[tuple[str, str, str]] = []
    narrations = 0

    for ev in events:
        when = str(ev.get("date", ""))[11:19] or "--:--:--"
        etype = ev.get("eventType")
        meta = ev.get("metadata") or {}
        name = meta.get("name")

        if etype == "ExecutionStarted":
            rows.append((when, "·", "the adventure began"))

        elif etype == "EventRaised" and name == "player_command":
            cmd = (_loads(ev.get("input")) or {}).get("command", "")
            if cmd == "__resume__":
                rows.append((when, "⟲", "the player came back"))
            elif cmd:
                rows.append((when, ">", cmd))

        elif etype == "TaskScheduled" and name in MACHINERY:
            if name == "narrate_scene":
                narrations += 1

        # Rows come from TaskScheduled, not TaskCompleted: the API reliably carries
        # a task's INPUT (which is where the room id is), while it omits the output of
        # an activity that returned a bare string. The executed-step proof is
        # step_names() below, which reads TaskCompleted.
        elif etype == "TaskScheduled" and name == "enter_room":
            rid = (_loads(ev.get("input")) or {}).get("room")
            title = world.ROOMS[rid]["title"] if rid in world.ROOMS else (rid or "?")
            rows.append((when, "·", f"entered {title}"))

        elif etype == "TaskScheduled" and name in STORY_ACTIVITIES and name != "enter_room":
            label = STEP_LABELS.get(name, name)
            marker = "★" if name == "secret_vault_found" else "◆"
            rows.append((when, marker, f"{label}   [step: {name}]"))

        elif etype == "TimerCreated" and meta.get("timer_type") != "external_event":
            rows.append((when, "⏱", f"durable timer set, due {str(meta.get('fire_at', ''))[:19]} UTC"))

        elif etype == "TimerFired" and meta.get("timer_type") != "external_event":
            rows.append((when, "⏱", "the timer fired and woke the player"))

        elif etype == "ExecutionCompleted":
            rows.append((when, "·", "the record was sealed"))

    return rows, narrations


def render_timeline(instance_id: str, output: dict | None) -> None:
    """Print the adventure as a timeline. Server history if we can, honest fallback if not."""
    doc = fetch(instance_id)
    rows, narrations = timeline(instance_id, doc)

    print(ui.c(ui.TITLE, "── Your adventure, read back out of the workflow run history "
                         + "─" * 18))
    print()

    if rows:
        for when, marker, text in rows:
            colour = ui.WIN if marker == "★" else (ui.MENU if marker == ">" else ui.PROSE)
            if marker == "⏱":
                colour = ui.RULE
            print(f"  {ui.c(ui.DIM, when)}  {ui.c(colour, marker)}  {ui.c(colour, text)}")
        print()
        print(ui.c(ui.DIM, f"  source: diagrid workflow get {instance_id} "
                           f"--app-id {config.app_id()} --project {config.project()}"))
        print(ui.c(ui.DIM, f"  plus {narrations} narration steps, not listed"))
    else:
        # The CLI was not available. Say exactly that, and use the workflow's own
        # return value instead of pretending.
        print(ui.c(ui.NOTICE, "  (Catalyst run history unavailable — the `diagrid` CLI is not on PATH"))
        print(ui.c(ui.NOTICE, "   or not logged in. Falling back to the workflow's own output,"))
        print(ui.c(ui.NOTICE, "   which is the same command sequence without server timestamps.)"))
        print()
        for turn, room, what in (output or {}).get("log", []):
            label = STEP_LABELS.get(what, what)
            print(f"  {ui.c(ui.DIM, f'turn {turn:>2}')}  "
                  f"{ui.c(ui.PROSE, world.room(room)['title'])} — {label}")

    if output:
        print()
        line = (f"  turns {output.get('turns')}    "
                f"health {output.get('health')}    gold {output.get('gold')}    "
                f"rooms seen {len(output.get('visited') or [])}/{len(world.ROOMS)}    "
                f"choices made {len(output.get('choices_made') or [])}")
        print(ui.c(ui.HUD, line))
        if output.get("cheated_merchant"):
            note = ("  Hask's ledger still has your name in it"
                    + (", under a settlement." if output.get("ledger_settled") else "."))
            print(ui.c(ui.NOTICE, note))

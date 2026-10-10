"""Prove nothing the player can read explains why the door wants the lodestone.

Three surfaces, because this version has three ways the secret could escape:

  1. the engine's own strings  -- enumerated by exercising it, not grepped
  2. the narrator's prompts    -- the model must never be TOLD the condition,
                                  or it can leak what it was told
  3. a real transcript         -- the model writes the prose now, so the only
                                  way to know what it said is to read what it said

    uv run python leakcheck.py                    surfaces 1 and 2
    uv run python leakcheck.py transcript.txt     surface 3

A leak is a string that ties the door or the vault to the lodestone or to the
act of giving, *as a motive or an instruction*. The menu label is allowed to
name the verb -- that is deliberate, an unguessable verb is a dead end rather
than a secret -- and the after-the-fact lines a player only reads once the door
is already open are allowed too. Everything else is a leak.
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

DOORISH = re.compile(r"door|vault|teeth|threshold", re.I)
GIVEISH = re.compile(r"lodestone|ashen|offer|give|given|giving|hand over|sacrific"
                     r"|toll|tribute|payment|price", re.I)
MOTIVE = re.compile(
    r"\b(because|reason|why|in order to|so that|only when|only if|unless|if you|"
    r"come back when|return when|you must|you need|needs?|requires?|wants?|"
    r"will open|opens when|opens if|the way to|how to|bring me|in exchange|"
    r"bargain|oath|owed|debt|once part of|same stone|belongs to|its own)\b", re.I)

ALLOWED = {
    "offer the ashen lodestone to the door",
    "the door is open. north leads into the vault.",
    "the door stands open. north leads into the vault.",
    '"yes," says the door. "that one."',
    "the ashen lodestone is gone. it is no longer draining you, and it is no "
    "longer pointing anywhere.",
    "the ashen lodestone is no longer draining you. it is also no longer "
    "pointing anywhere.",
}


def suspicious(text: str) -> bool:
    t = " ".join((text or "").split())
    if t.lower().strip() in ALLOWED:
        return False
    if not DOORISH.search(t) or not GIVEISH.search(t):
        return False
    return bool(MOTIVE.search(t))


def engine_strings() -> list[tuple[str, str]]:
    """Every string the engine can put on screen, by exercising it."""
    from dungeon_master.engine import engine, world
    from dungeon_master.agent import narrator, tools
    found: list[tuple[str, str]] = []

    for rid, room in world.ROOMS.items():
        for field in ("title", "prose", "facts"):
            if room.get(field):
                found.append((f"{rid}.{field}", room[field]))
        for a in room.get("ambience") or []:
            found.append((f"{rid}.ambience", a))
    for a in world.GLOBAL_AMBIENCE:
        found.append(("global.ambience", a))
    for e in world.CAMPFIRE_EVENTS:
        for field in ("beat",):
            if e.get(field):
                found.append((f"campfire[{e['id']}].{field}", e[field]))
        for v in e.get("verbatim") or []:
            found.append((f"campfire[{e['id']}].verbatim", v))
    found.append(("world.OPENING", world.OPENING))

    # Every transition, under enough state variations to reach both branches of
    # the ones that have branches.
    variants = []
    for carrying, door, cheated, settled, hurt in itertools.product(
            (False, True), (False, True), (False, True), (False, True), (False, True)):
        s = engine.new_state(30)
        s["carrying_lodestone"] = carrying
        s["lodestone_taken_ever"] = carrying
        s["door_open"] = door
        s["cheated_merchant"] = cheated
        s["ledger_settled"] = settled
        if hurt:
            s["health"] = 10
        variants.append(s)

    for s in variants:
        for rid in world.ROOMS:
            s["room"] = rid
            for line in engine.room_entry_verbatim(s):
                found.append((f"{rid}.entry", line))
            for c in engine.available_choices(s):
                found.append((f"{rid}.choice[{c['id']}]", c["label"]))
            for c in list(engine.available_choices(s)):
                import copy
                s2 = copy.deepcopy(s)
                r = engine.apply_choice(s2, c["id"])
                if r.get("beat"):
                    found.append((f"{rid}.{c['id']}.beat", r["beat"]))
                for v in r.get("verbatim") or []:
                    found.append((f"{rid}.{c['id']}.verbatim", v))
            for d in ("north", "south", "east", "west"):
                import copy
                s2 = copy.deepcopy(s)
                r = engine.move(s2, d)
                if r.get("beat"):
                    found.append((f"{rid}.move.beat", r["beat"]))
                for v in r.get("verbatim") or []:
                    found.append((f"{rid}.move.verbatim", v))
            for action in ("look", "status", "help", "rest", "none"):
                import copy
                s2 = copy.deepcopy(s)
                r = tools.apply_action(s2, action, "")
                if r.get("beat"):
                    found.append((f"{rid}.tool[{action}].beat", r["beat"]))
                for v in r.get("verbatim") or []:
                    found.append((f"{rid}.tool[{action}].verbatim", v))

    # The narrator's fallbacks are player-visible; its prompts are checked
    # separately below.
    found.append(("narrator.recap_fallback",
                  narrator.recap({"title": "The Hall of Teeth"}, "")))
    return found


def prompt_strings() -> list[tuple[str, str]]:
    """What the model is TOLD. It cannot leak a condition it was never given."""
    from dungeon_master.agent import narrator
    return [("narrator.NARRATE_SYSTEM", narrator.NARRATE_SYSTEM),
            ("narrator.INTERPRET_SYSTEM", narrator.INTERPRET_SYSTEM)]


CHROME = re.compile(r"^\s*(?:[─═│]|…|\.\.\.|health \d+|\s*\d\)|"
                    r"(?:north|south|east|west) —|\[\[|★|☾|·|>\s*$)", re.I)


def transcript_strings(path: Path) -> list[tuple[str, str]]:
    raw = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", path.read_text(errors="replace"))
    kept = [ln for ln in raw.splitlines() if not CHROME.match(ln)]
    flat = " ".join(kept)
    return [(path.name, s) for s in re.split(r"(?<=[.!?])\s+", flat)]


def main() -> int:
    if len(sys.argv) > 1:
        pairs = [p for a in sys.argv[1:] for p in transcript_strings(Path(a))]
        what = "transcripts: " + ", ".join(Path(a).name for a in sys.argv[1:])
    else:
        pairs = engine_strings() + prompt_strings()
        what = "engine strings + narrator prompts"

    leaks = [(w, t) for w, t in pairs if suspicious(t)]
    print(f"leakcheck — {what}")
    print(f"  strings checked: {len(pairs)}")
    if leaks:
        print(f"\nFAIL: {len(leaks)} string(s) give the door a motive:")
        for w, t in leaks[:20]:
            print(f"  [{w}] {' '.join(t.split())[:160]}")
        return 1
    print("PASS: nothing readable explains why the door wants it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

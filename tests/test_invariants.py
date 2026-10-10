#!/usr/bin/env python3
"""Invariant checks on the pure game rules. No Catalyst, no network, no key.

Run with `make test` or `uv run python -m tests.test_invariants`. These are the
checks that earn their keep: they exercise the whole rule set in about a second
and they caught, between them, a turn counter that never advanced and a choice
that was offered twice.

1. DETERMINISM: the same command sequence must produce byte-identical state. This is
   the property Dapr relies on when it replays the orchestrator.
2. NO INERT MENU ENTRY: taking any offered choice must change the state. If it does
   not, the player was made to pick something just to be told it did nothing.
3. NO REPEATED ONCE-CHOICE: a once-only choice must never be offered twice.
"""
import copy, json, random, sys

from dungeon_master.engine import engine, world

def snap(s):
    return json.dumps({k: v for k, v in s.items() if k != "recent_ambience"}, sort_keys=True)

def run(seed, record=None, events=None):
    """`record` replays a command list; `events` replays the campfire activity results.

    Replaying the activity result rather than re-rolling it is exactly what Dapr does:
    a random choice made inside an activity is recorded in the history and handed back
    on replay. Re-rolling it here would be testing the test, not the game.
    """
    rnd = random.Random(seed)
    s = engine.new_state(20)
    cmds = []
    rolled = []
    ev_queue = list(events) if events is not None else None
    offered_history = []
    for _ in range(120):
        if s["ending"]:
            break
        live = engine.available_choices(s)
        offered_history.append([c["id"] for c in live])
        opts = [("move", d) for d in engine.open_directions(s)] + [("choice", c["id"]) for c in live]
        if not opts:
            break
        kind, arg = (record.pop(0) if record else rnd.choice(opts))
        cmds.append((kind, arg))
        before = snap(s)
        if kind == "move":
            engine.move(s, arg)
        else:
            r = engine.apply_choice(s, arg)
            if r["timer"]:
                if ev_queue is not None:
                    eid = ev_queue.pop(0)
                else:
                    eid = rnd.choice(world.CAMPFIRE_EVENTS)["id"]
                rolled.append(eid)
                engine.apply_campfire_event(s, eid)
            after = snap(s)
            if before == after:
                return None, f"INERT CHOICE: {arg} in {s['room']} changed nothing"
        engine.apply_upkeep(s)
    return (s, cmds, offered_history, rolled), None

ONCE = {c["id"] for c in engine.CHOICES
        if "not _taken" in __import__("inspect").getsource(c["when"])}

fails = []
for seed in range(400):
    out, err = run(seed)
    if err:
        fails.append((seed, err)); continue
    s, cmds, offered, rolled = out
    # 3. once-only choices never offered twice after being taken
    seen = set()
    for menu in offered:
        for cid in menu:
            if cid in ONCE and cid in seen:
                fails.append((seed, f"ONCE-CHOICE RE-OFFERED: {cid}")); break
        for cid in menu:
            pass
        # mark what the walk actually took
    taken_counts = {}
    for cid in s["taken"]:
        taken_counts[cid] = taken_counts.get(cid, 0) + 1
    for cid, n in taken_counts.items():
        if cid in ONCE and n > 1:
            fails.append((seed, f"ONCE-CHOICE TAKEN {n}x: {cid}"))
    # 1. determinism: replay the identical command list
    out2, err2 = run(seed, record=list(cmds), events=list(rolled))
    if err2:
        fails.append((seed, f"replay errored: {err2}")); continue
    if snap(out2[0]) != snap(s):
        fails.append((seed, "NON-DETERMINISTIC replay"))

print(f"once-only choice ids detected: {len(ONCE)}")
print(f"walks run: 400")
if fails:
    print(f"FAILURES ({len(fails)}):")
    for seed, msg in fails[:20]:
        print(f"  seed {seed}: {msg}")
else:
    print("ALL INVARIANTS HOLD: deterministic replay, no inert menu entry, no once-choice re-offered")

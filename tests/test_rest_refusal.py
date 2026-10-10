#!/usr/bin/env python3
"""The one explanation, checked for both front ends at once.

This exists because the bug it covers was fixed twice and landed once: the
agent front end explained an unavailable rest, the workflow front end still
said "not something you can do here" to a player who was simply uninjured.
Now there is a single engine.rest_refusal and this asserts its three cases.
"""
import sys

from dungeon_master.engine import engine, world


def main() -> int:
    failures = []

    # 1. Away from the campfire: the room is the problem.
    s = engine.new_state(20)
    s["room"] = world.START_ROOM
    got = engine.rest_refusal(s)
    if got != world.REST_REFUSAL_NO_CAMPFIRE:
        failures.append(f"away from camp: {got!r}")

    # 2. At the campfire, unhurt: the player is the problem, and must be told
    #    so -- blaming the room here is the actual bug.
    s = engine.new_state(20)
    s["room"] = world.CAMPFIRE_ROOM
    s["health"] = s["max_health"]
    got = engine.rest_refusal(s)
    if got != world.REST_REFUSAL_FULL_HEALTH:
        failures.append(f"at camp, full health: {got!r}")

    # 3. At the campfire, hurt: no refusal at all.
    s = engine.new_state(20)
    s["room"] = world.CAMPFIRE_ROOM
    s["health"] = s["max_health"] - 5
    got = engine.rest_refusal(s)
    if got is not None:
        failures.append(f"at camp, hurt: expected None, got {got!r}")

    # 4. Neither message may blame the room when the room is right.
    for line in world.REST_REFUSAL_FULL_HEALTH:
        if "here to rest" in line or "not something you can do here" in line:
            failures.append(f"full-health message blames the room: {line!r}")

    if failures:
        print("FAIL")
        for f in failures:
            print("  " + f)
        return 1
    print("PASS: rest refusals explain themselves, in all three cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""List an adventure's decision points, and fork it from one of them.

`diagrid workflow rerun` takes an --event-id, which is the useful part and the
unusable part: the history is 46 entries of TaskScheduled and TaskCompleted,
and nothing in it says "this is where you walked into the vault". This pairs
each event id with the command the player actually typed, so a fork point can
be chosen by what happened rather than by number.

    tools/fork.py cyd-1-1                  list the decision points
    tools/fork.py cyd-1-1 18               fork from event 18
    tools/fork.py cyd-1-1 18 my-other-run  ... into a named instance

Forking leaves the original untouched: both adventures then exist, which is
the whole point of the history being the save file.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def history(instance: str, app: str, project: str) -> list[dict]:
    out = subprocess.run(
        ["diagrid", "workflow", "get", instance,
         "--app-id", app, "--project", project],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit(f"could not read {instance}: {(out.stderr or out.stdout).strip()[:200]}")
    try:
        import yaml
    except ImportError:
        sys.exit("needs pyyaml:  uv run --extra workflow python tools/fork.py ...")
    doc = yaml.safe_load(out.stdout) or {}
    # The CLI returns newest first; decisions read better oldest first.
    return list(reversed(doc.get("history") or []))


def decisions(hist: list[dict]) -> list[dict]:
    """Pair each typed command with the event id that follows it.

    Forking from that id replays everything up to and including the command,
    so the new run resumes at the moment just after it was typed -- with the
    same choices still open.
    """
    out, pending = [], None
    for entry in hist:
        meta = entry.get("metadata") or {}
        if entry.get("eventType") == "EventRaised" and meta.get("name") == "player_command":
            raw = entry.get("input") or ""
            try:
                cmd = json.loads(raw).get("command", raw)
            except (ValueError, TypeError):
                cmd = str(raw)
            pending = {"command": str(cmd), "date": str(entry.get("date", ""))[11:19]}
        elif pending and entry.get("eventId"):
            pending["event_id"] = entry["eventId"]
            pending["then"] = meta.get("name", "")
            out.append(pending)
            pending = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("event_id", nargs="?")
    ap.add_argument("new_name", nargs="?")
    ap.add_argument("--app-id", default=os.environ.get("DM_APP_ID", "dungeon-master"))
    ap.add_argument("--project", default=os.environ.get("DM_PROJECT", "dungeon-master"))
    a = ap.parse_args()

    if a.event_id is None:
        rows = decisions(history(a.instance, a.app_id, a.project))
        if not rows:
            print(f"{a.instance}: no player commands in its history yet.")
            return 0
        print(f"{a.instance} -- fork points, oldest first\n")
        print(f"  {'event':>5}  {'at':8}  {'you typed':<22}  which ran")
        print(f"  {'-'*5}  {'-'*8}  {'-'*22}  {'-'*20}")
        for r in rows:
            print(f"  {r['event_id']:>5}  {r['date']:8}  {r['command'][:22]:<22}  {r['then']}")
        print(f"\nFork one:  tools/fork.py {a.instance} <event> [new-name]")
        return 0

    new = a.new_name or f"{a.instance}-fork-{a.event_id}"
    print(f"forking {a.instance} at event {a.event_id} -> {new}")
    # Needs a connected worker, the same as terminate and purge.
    r = subprocess.run(
        ["diagrid", "workflow", "rerun",
         "--app-id", a.app_id, "--project", a.project,
         "--instance-id", a.instance, "--event-id", str(a.event_id),
         "--new-workflow-id", new],
        capture_output=True, text=True, timeout=120)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        print("\nIf that said no worker is connected, start the bridge or the "
              "worker first -- rerun needs one, like terminate and purge.")
        return 1
    print(f"\n{a.instance} is untouched. Play the fork with slot '{new}':")
    print(f"  curl -s -XPOST $BRIDGE/command -d '{{\"slot\":\"{new}\",\"k\":\"look\"}}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())

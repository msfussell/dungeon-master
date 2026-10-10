"""The terminal you play in.

It holds no game state. Every turn is a call to the agent through Catalyst --
service invocation, not localhost -- and the agent reads the save out of its own
durable memory. So "save and quit" is just an exit, and starting again resumes.

The campfire is the one place the client waits on something other than the
agent: the rest is its own workflow holding a durable timer, so the client
polls that run. Kill this terminal during a rest and the fire still burns down
on time; start it again and it tells you how long is left.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

from ..engine import ui
from . import config

SPINNERS = [
    "the dungeon considers", "the dark takes a breath", "the walls confer",
    "something decides what you deserve", "the hollow turns this over",
]


def _endpoint() -> tuple[str, str]:
    base = os.environ.get("DAPR_HTTP_ENDPOINT", "").rstrip("/")
    token = os.environ.get("DAPR_API_TOKEN", "")
    if not base or not token:
        sys.exit("No DAPR_HTTP_ENDPOINT / DAPR_API_TOKEN. Run this under "
                 "`diagrid dev run` (see README), or export a connection.")
    return base, token


def _post(path: str, payload: dict, timeout: float = 180.0) -> dict:
    base, token = _endpoint()
    req = urllib.request.Request(
        f"{base}{path}", method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "dapr-api-token": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _get(path: str, timeout: float = 30.0) -> dict:
    base, token = _endpoint()
    req = urllib.request.Request(f"{base}{path}",
                                 headers={"dapr-api-token": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def turn(slot: str, raw: str, rest_seconds: float) -> dict:
    """One player command, through Catalyst, into the agent."""
    return _post(
        f"/v1.0/invoke/{config.AGENT_APP_ID}/method/agent/run",
        {"session_id": slot, "slot": slot, "raw": raw,
         "rest_seconds": rest_seconds})


def rest_poll(slot: str, rest_seconds: float) -> dict:
    """Ask the AGENT whether the rest is over.

    Deliberately not a read of the rest workflow. This process is a different
    App ID from the agent, and the Dapr workflow API is scoped per identity, so
    reading the agent's run returns 404 ERR_INSTANCE_ID_NOT_FOUND -- which once
    made the client spin for ten minutes and never deliver the waking event.
    The agent owns the run; ask the agent.
    """
    return turn(slot, "__restpoll__", rest_seconds)


def spin(label: str, seconds: float) -> None:
    """Silence reads as a hang, and the first thing anyone does to a hung game
    is kill it. The phrase varies because a fixed one is wallpaper by turn 3."""
    if not sys.stdout.isatty():
        time.sleep(seconds)
        return
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    end = time.time() + seconds
    i = 0
    while time.time() < end:
        sys.stdout.write(f"\r  {ui.DIM}{frames[i % len(frames)]} {label}…{ui.RESET}")
        sys.stdout.flush()
        i += 1
        time.sleep(0.12)
    sys.stdout.write("\r" + " " * (len(label) + 12) + "\r")
    sys.stdout.flush()

"""dungeon-master: one dungeon, two durable shapes on Diagrid Catalyst.

    dungeon_master.engine     the game: map, rules, parser. No Catalyst in it.
    dungeon_master.workflow   front end 1 -- one long-lived Dapr Workflow
    dungeon_master.agent      front end 2 -- a Catalyst Agent over LangGraph

The engine is the point of this layout. It is pure functions over plain dicts,
with no clock, no network and no global RNG, so both front ends sit on exactly
one copy of the rules and a fix lands once. Everything that differs between
them is durable plumbing, which is the contrast worth showing.

WHY THIS FILE HAS CODE IN IT: `dapr.conf.settings` snapshots DAPR_* at import
time. Load .env any later and the SDK has already decided it is talking to a
sidecar on 127.0.0.1:50001, and every connection fails with no warning. Loading
here guarantees it happens first, because importing anything in this package
runs this file. See https://github.com/dapr/python-sdk/issues/1259.
"""

from __future__ import annotations

import os
import pathlib

try:
    from dotenv import load_dotenv
except ImportError:  # the engine alone needs no dependencies
    load_dotenv = None  # type: ignore[assignment]

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    # override=False, deliberately: under `diagrid dev run` the four DAPR_*
    # values are injected into the environment and must beat the file, because
    # the tunnel's endpoint is the real one.
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / ".env.workflow", override=False)
    load_dotenv(PROJECT_ROOT / ".env.agent", override=False)

# Catalyst hands out https:// gRPC endpoints; the Dapr SDK deprecates that
# spelling and prints a UserWarning straight into the game's prose.
_grpc = os.environ.get("DAPR_GRPC_ENDPOINT", "")
if _grpc and "?tls=" not in _grpc:
    if _grpc.startswith("https://"):
        os.environ["DAPR_GRPC_ENDPOINT"] = _grpc[len("https://"):] + "?tls=true"
    elif _grpc.startswith("http://"):
        os.environ["DAPR_GRPC_ENDPOINT"] = _grpc[len("http://"):] + "?tls=false"

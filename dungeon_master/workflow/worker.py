"""Worker-only process: hosts the orchestrator and activities, drives no game.

Two reasons this exists separately from the CLI:

1. Catalyst's terminate and purge operations require a connected workflow worker.
   With no app running they fail, so admin work needs a process that is nothing but
   a worker.
2. It is the honest way to show the durability claim. Kill the CLI mid-rest, start
   only this, and the campfire timer still fires and the game still advances with no
   player attached at all.

    uv run python -m dungeon_master.worker
"""

from __future__ import annotations

import signal
import sys
import threading

from . import config
from .workflow import build_runtime


def main() -> int:
    if not config.have_connection():
        print("No Catalyst connection in the environment. Check .env "
              "(DAPR_GRPC_ENDPOINT, DAPR_API_TOKEN).", file=sys.stderr)
        return 1

    runtime = build_runtime()
    runtime.start()
    print(f"dungeon-master worker connected "
          f"(project={config.project()} app={config.app_id()}). Ctrl-C to stop.",
          flush=True)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()

    print("worker shutting down", flush=True)
    runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

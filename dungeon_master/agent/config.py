"""Settings and console links."""
from __future__ import annotations

import os

CONSOLE = "https://catalyst.diagrid.io"

PROJECT = os.environ.get("DM_PROJECT", "dungeon-master")
AGENT_APP_ID = os.environ.get("DM_AGENT_ID", "dungeon-master-agent")
MEMORY_STORE = os.environ.get("DM_MEMORY_STORE", "agent-memory")
REST_SECONDS = float(os.environ.get("DM_REST_SECONDS", "120"))
AGENT_PORT = int(os.environ.get("PORT", "5001"))


def workflow_link(run_id: str) -> str:
    """A run of the agent's workflow. These are the only console routes that exist."""
    return f"{CONSOLE}/workflows/{AGENT_APP_ID}/{run_id}?project={PROJECT}"


def agent_link(agent_id: str | None = None) -> str:
    # An agent with no registry record yet takes its app id in both places.
    aid = agent_id or AGENT_APP_ID
    return f"{CONSOLE}/agents/{AGENT_APP_ID}/{aid}?project={PROJECT}"

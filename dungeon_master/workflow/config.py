"""Environment and Catalyst coordinates. One place, loaded once."""

from __future__ import annotations

import os

# .env is loaded in dungeon_master/__init__.py, which MUST happen before `import dapr`
# anywhere in the process. See the note there.
from .. import PROJECT_ROOT  # noqa: F401  (re-exported for callers)

WORKFLOW_NAME = "dungeon_master"


def project() -> str:
    return os.environ.get("DM_PROJECT", "dungeon-master")


def app_id() -> str:
    return os.environ.get("DM_APP_ID", "dungeon-master")


def rest_seconds() -> int:
    """How long the campfire rest lasts. 120 by default; shorten it for a demo."""
    try:
        return max(1, int(os.environ.get("DM_REST_SECONDS", "120")))
    except ValueError:
        return 120


def console_url(instance_id: str) -> str:
    return (
        f"https://catalyst.diagrid.io/workflows/{app_id()}/{instance_id}"
        f"?project={project()}"
    )


def have_connection() -> bool:
    return bool(os.environ.get("DAPR_GRPC_ENDPOINT") and os.environ.get("DAPR_API_TOKEN"))

"""The agent process.

One process hosts three things:

  * the LangGraph agent, served over HTTP at /agent/run, which Catalyst calls
    into through the Agent resource's endpoint;
  * the Dapr workflow worker the adapter runs the graph on;
  * the two auxiliary workflows (the named vault step and the campfire timer),
    registered on that same runtime.

Run it behind an app tunnel, because an Agent is called *into*:

    diagrid dev run --project dungeon-master --app-id dungeon-master-agent \
        --app-port 5001 --yes -- \
        sh -c 'set -a; . ./.env; set +a; exec uv run python -m dungeon_master_agent.agent'

`dev run` injects DAPR_API_TOKEN and the endpoints; .env must not override them.
"""

from __future__ import annotations

import logging
import os

from . import config
from .aux_workflows import ACTIVITIES, WORKFLOWS
from .graph import build


def quiet_logs() -> None:
    """The agent's own log is a server log, so INFO is fine here -- but the
    frameworks are chatty enough to bury a real error, and this process is what
    anyone debugging a booth failure will read."""
    if os.environ.get("DM_VERBOSE"):
        logging.basicConfig(level=logging.INFO)
        return
    logging.basicConfig(level=logging.INFO)
    for name in ("httpx", "httpcore", "openai", "urllib3", "langchain",
                 "langchain_openai", "langgraph"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    quiet_logs()
    log = logging.getLogger("dungeon-master-agent")

    from diagrid.agent.langgraph import DaprWorkflowGraphRunner

    runner = DaprWorkflowGraphRunner(
        build(),
        name=config.AGENT_APP_ID,
        role="dungeon master",
        goal="Narrate a dungeon truthfully, and never decide what is true.",
    )

    # The auxiliary workflows go on the runner's own runtime, so there is still
    # one process and one connection. A LangGraph node cannot create a durable
    # timer (it runs inside an activity) and cannot give a step its own name in
    # the history -- these two can. See aux_workflows.
    runtime = runner._workflow_runtime
    for wf in WORKFLOWS:
        runtime.register_workflow(wf)
    for act in ACTIVITIES:
        runtime.register_activity(act)

    log.info("agent workflow : %s", runner.workflow_name)
    log.info("aux workflows  : %s", ", ".join(w.__name__ for w in WORKFLOWS))
    log.info("memory store   : %s", config.MEMORY_STORE)
    log.info("serving on     : %s", config.AGENT_PORT)
    runner.serve(port=config.AGENT_PORT)


if __name__ == "__main__":
    main()

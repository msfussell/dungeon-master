"""The two durable things a LangGraph node cannot do for itself.

**A step named `secret_vault_found`.** Every node in a LangGraph agent is
executed by one generic activity, `execute_node_activity`; the node's own name
survives only inside that activity's payload, and payloads are withheld at the
default `metadata` data-sharing level. So a node called `secret_vault_found`
does *not* put that name in the run history. A workflow does: a run appears
under its own function name, readable from the console and the API by anyone,
months later, without raising anyone's data-sharing level. That is why the
vault moment is its own one-step workflow and not a node.

**A durable timer.** A node runs *inside* an activity, and an activity cannot
call `ctx.create_timer`. The campfire is therefore its own workflow: the node
starts it and returns immediately, so the agent's turn stays short, and the
client waits on the timer instead. The app can be dead for the whole nap.

Both are registered on the agent runner's own WorkflowRuntime, so this is still
one process -- see agent.py.
"""

from __future__ import annotations

import random
from datetime import timedelta

from dapr.ext.workflow import DaprWorkflowContext, WorkflowActivityContext

from ..engine import world

# Instance id prefixes, so a run's purpose is legible in a project listing.
VAULT_PREFIX = "vault"
REST_PREFIX = "rest"


def vault_opened(ctx: WorkflowActivityContext, payload: dict) -> dict:
    """The recorded fact. Deliberately tiny: its value is that it happened."""
    return {
        "step": "secret_vault_found",
        "slot": payload.get("slot"),
        "turn": payload.get("turn"),
        "room": payload.get("room"),
    }


def secret_vault_found(ctx: DaprWorkflowContext, payload: dict):
    """Named for the history, not for the code.

    A run of this workflow IS the record that the player opened the vault.
    """
    result = yield ctx.call_activity(vault_opened, input=payload)
    return result


def choose_waking(ctx: WorkflowActivityContext, payload: dict) -> dict:
    """Roll the event that ends the rest.

    Seeded from the slot and the rest count because activities run at least
    once: a retried roll must land on the event that actually happened rather
    than quietly replacing it.
    """
    rng = random.Random(f"{payload.get('slot')}:rest:{payload.get('rests')}")
    return {"event_id": rng.choice([e["id"] for e in world.CAMPFIRE_EVENTS])}


def campfire_rest(ctx: DaprWorkflowContext, payload: dict):
    """The rest. A real timer on Catalyst, not a sleep in anybody's process."""
    seconds = float(payload.get("seconds") or 120)
    wake_at = ctx.current_utc_datetime + timedelta(seconds=seconds)
    # The client reads this to tell the player when they will wake, and to
    # recognise a rest that finished while the app was closed.
    ctx.set_custom_status(f'{{"wake_at": "{wake_at.isoformat()}"}}')
    yield ctx.create_timer(wake_at)
    event = yield ctx.call_activity(choose_waking, input=payload)
    return event


WORKFLOWS = (secret_vault_found, campfire_rest)
ACTIVITIES = (vault_opened, choose_waking)

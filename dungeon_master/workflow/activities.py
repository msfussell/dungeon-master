"""Workflow activities.

DESIGN NOTES

* An activity is where everything non-deterministic is allowed to live: the LLM call,
  the random flavour roll, the random campfire event. The orchestrator never does any
  of it, so a replay re-reads the recorded answer instead of rolling again.

* ACTIVITY NAMES ARE THE SAVE FILE'S VOCABULARY. The workflow history is the only
  save file this game has, and these names are what show up in it. So they are named
  for the story beat, not for the code path: `secret_vault_found`, `cheat_the_merchant`,
  `claim_durable_scroll`. `secret_vault_found` in particular is required by the spec
  to appear in the run history, and it appears there precisely because it is a real
  activity that really executes when the door opens.

* Activities are effectively idempotent: they compute and return, and the only
  side effect is an outbound LLM read. Re-running one on retry costs a few tokens
  and nothing else. Nothing here writes state; the orchestrator owns state.
"""

from __future__ import annotations

import random

import dapr.ext.workflow as wf

from ..engine import world
from . import narrator


def pick_ambience(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    """One varied flavour line, avoiding whatever was shown recently.

    (Rule: a fixed per-turn line is wallpaper by turn 3. So the pool is the room's
    own lines plus the global pool, minus the last few used.)
    """
    pool = list(world.room(inp["room"])["ambience"]) + list(world.GLOBAL_AMBIENCE)
    recent = set(inp.get("recent", []))
    fresh = [p for p in pool if p not in recent] or pool
    return random.choice(fresh)


def narrate_scene(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    """Prose for the current scene, plus a fresh ambience line. Never sees verbatim."""
    return {
        "prose": narrator.narrate_scene(inp),
        "ambience": pick_ambience(ctx, {"room": inp["room"], "recent": inp.get("recent", [])}),
        "narrator": narrator.provider_label(),
    }


def recap_moment(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    """One dramatic sentence, for a resumed run."""
    return narrator.narrate_recap(inp)


def campfire_event(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    """The random event that wakes the player, rolled HERE so replay cannot re-roll."""
    event = random.choice(world.CAMPFIRE_EVENTS)
    return {
        "event_id": event["id"],
        "prose": narrator.narrate_waking({"room": inp["room"], "event": event}),
    }


# ---------------------------------------------------------------------------
# Named story steps.
#
# These exist to be legible in the run history. They take the small amount of
# context worth recording and hand back an acknowledgement, so that reading the
# history reads like reading the adventure.
# ---------------------------------------------------------------------------

def enter_room(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    return world.room(inp["room"])["title"]


def take_cursed_item(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    return "the ashen lodestone is in the player's hands"


def secret_vault_found(ctx: wf.WorkflowActivityContext, inp: dict) -> dict:
    """The spec's named step. Recorded the moment the talking door opens."""
    return {
        "step": "secret_vault_found",
        "room": inp.get("room"),
        "turn": inp.get("turn"),
        "vault": world.room(world.VAULT_ROOM)["title"],
    }


def trade_with_merchant(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    return f"Hask recorded a sale: {inp.get('choice')}"


def cheat_the_merchant(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    """The merchant's memory is this line in the history, and the state flag it sets."""
    return "Hask recorded the theft of the ivory die in his ledger"


def settle_the_ledger(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    return "Hask recorded the settlement, under the original entry"


def campfire_rest_begin(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    return f"the player bedded down for {inp.get('seconds')} seconds"


def claim_durable_scroll(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    return "the durable scroll left the vault"


def save_and_quit(ctx: wf.WorkflowActivityContext, inp: dict) -> str:
    """Marks the park point in the history, so a resume is visible in the timeline."""
    return f"parked in {world.room(inp['room'])['title']} on turn {inp.get('turn')}"


# Every activity the orchestrator may be asked to call by name, from the `activity`
# field an engine transition returns.
STORY_ACTIVITIES = {
    "enter_room": enter_room,
    "take_cursed_item": take_cursed_item,
    "secret_vault_found": secret_vault_found,
    "trade_with_merchant": trade_with_merchant,
    "cheat_the_merchant": cheat_the_merchant,
    "settle_the_ledger": settle_the_ledger,
    "campfire_rest_begin": campfire_rest_begin,
    "claim_durable_scroll": claim_durable_scroll,
    "save_and_quit": save_and_quit,
}

ALL_ACTIVITIES = {
    **STORY_ACTIVITIES,
    "narrate_scene": narrate_scene,
    "recap_moment": recap_moment,
    "campfire_event": campfire_event,
}

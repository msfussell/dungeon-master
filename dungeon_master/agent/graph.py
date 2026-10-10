"""The agent's graph: one player command, five nodes.

    load -> interpret -> act -> narrate -> save

Each node is executed as a durable activity, so a turn that dies halfway is
resumed rather than restarted: the nodes that already ran are replayed from the
run's history and are not executed twice. That is the property proved by
killing the process mid-node.

The split of responsibility is the whole design:

    interpret   the model may read my English          (guessing allowed)
    act         the engine decides what is true        (no model, ever)
    narrate     the model writes the prose             (facts supplied)

`verbatim` lines are carried around `narrate`, never through it.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, TypedDict

from ..engine import engine, world
from . import config, narrator, tools
from .aux_workflows import REST_PREFIX, VAULT_PREFIX, campfire_rest, secret_vault_found

logger = logging.getLogger(__name__)


def _last(a, b):
    """Reducer: last write wins. The game state is a single authority."""
    return b if b is not None else a


def _append(a, b):
    return (a or []) + (b or [])


class Turn(TypedDict, total=False):
    slot: Annotated[str, _last]
    raw: Annotated[str, _last]
    rest_seconds: Annotated[float, _last]
    game: Annotated[dict, _last]
    action: Annotated[str, _last]
    argument: Annotated[str, _last]
    result: Annotated[dict, _last]
    scene: Annotated[dict, _last]
    prose: Annotated[str, _last]
    verbatim: Annotated[list, _append]
    runs: Annotated[list, _append]          # auxiliary workflow runs this turn
    interpreted_by: Annotated[str, _last]
    resting: Annotated[bool, _last]
    wake_at: Annotated[str, _last]


# ---------------------------------------------------------------------------
# Durable memory: the save file
# ---------------------------------------------------------------------------

def _key(slot: str) -> str:
    return f"dungeon-master/{slot}"


def load_game(slot: str) -> dict | None:
    from dapr.clients import DaprClient
    with DaprClient() as d:
        item = d.get_state(store_name=config.MEMORY_STORE, key=_key(slot))
        if not item.data:
            return None
        try:
            return json.loads(item.data)
        except (ValueError, TypeError):
            return None


def save_game(slot: str, game: dict) -> None:
    from dapr.clients import DaprClient
    with DaprClient() as d:
        d.save_state(store_name=config.MEMORY_STORE, key=_key(slot),
                     value=json.dumps(game))


def delete_game(slot: str) -> None:
    from dapr.clients import DaprClient
    with DaprClient() as d:
        d.delete_state(store_name=config.MEMORY_STORE, key=_key(slot))


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

RESET_COMMAND = "__reset__"


def _resolve_pending_rest(slot: str, game: dict) -> tuple[list[str], bool, str]:
    """Apply a campfire rest whose timer has fired. Runs inside the AGENT.

    The client cannot do this. `play.sh` is a different App ID, and the Dapr
    workflow API is scoped per identity: the client's poll of the rest run
    comes back 404 ERR_INSTANCE_ID_NOT_FOUND, which is exactly the bug this
    replaces. The agent owns the run, so the agent reads it.

    Doing it here, in `load`, also means a player who quits during a rest and
    comes back tomorrow has it resolved by their next turn, with no special
    case: the rest count outruns the applied count until it is applied.

    Returns (verbatim lines, still_resting, wake_at).
    """
    rests = int(game.get("rests") or 0)
    applied = int(game.get("last_rest_applied") or 0)
    if rests <= applied:
        return [], False, ""

    run_id = f"{REST_PREFIX}-{slot}-{rests}"
    try:
        from dapr.ext.workflow import DaprWorkflowClient
        st = DaprWorkflowClient().get_workflow_state(run_id)
    except Exception as exc:
        logger.warning("could not read the rest run %s: %s", run_id, exc)
        return [], True, ""
    if st is None:
        # No such run: the rest never started. Do not strand the player.
        game["last_rest_applied"] = rests
        return ["The fire never caught. The rest did not happen."], False, ""

    status = str(getattr(st, "runtime_status", "")).upper()
    if "COMPLETED" not in status:
        if "FAILED" in status or "TERMINATED" in status:
            game["last_rest_applied"] = rests
            return ["Something interrupted the rest. You are awake, and no "
                    "better for it."], False, ""
        wake_at = ""
        try:
            cs = getattr(st, "serialized_custom_status", None)
            if cs:
                wake_at = (json.loads(cs) or {}).get("wake_at", "")
        except (ValueError, TypeError):
            pass
        return [], True, wake_at

    event_id = ""
    try:
        raw_out = getattr(st, "serialized_output", None)
        if raw_out:
            parsed = json.loads(raw_out)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            event_id = (parsed or {}).get("event_id", "")
    except (ValueError, TypeError):
        event_id = ""

    if not event_id:
        game["last_rest_applied"] = rests
        return ["You wake, and the fire is out."], False, ""

    result = engine.apply_campfire_event(game, event_id)
    game["last_rest_applied"] = rests
    lines = list(result.get("verbatim") or [])
    if result.get("beat"):
        # The waking event's own prose. It is recorded in the rest run, so it
        # is the same on every replay; printing it verbatim keeps it that way.
        lines.insert(0, result["beat"])
    return lines, False, ""


def load(state: Turn) -> dict:
    slot = state["slot"]
    raw = (state.get("raw") or "").strip()
    # Starting over has to happen HERE, inside the agent. Dapr prefixes state
    # keys with the writing App ID, so the client -- a different identity --
    # cannot delete the agent's save even though it knows the store's name.
    # A client-side delete silently does nothing, which looks like `--new`
    # being ignored.
    game = None if raw == RESET_COMMAND else load_game(slot)
    fresh = game is None
    if fresh:
        game = engine.new_state(int(state.get("rest_seconds") or config.REST_SECONDS))
    game["parked"] = False

    # A rest whose timer has fired is applied before anything else this turn.
    rest_lines, still_resting, wake_at = _resolve_pending_rest(slot, game)

    out: dict[str, Any] = {"game": game, "scene": tools.scene(game),
                           "resting": still_resting, "wake_at": wake_at}
    if rest_lines:
        out["verbatim"] = rest_lines
    if fresh:
        # The opening line. Printed, not narrated: it states the goal, and a
        # narrator asked to re-describe a goal turns it into atmosphere.
        out["verbatim"] = [world.OPENING]
    return out


def interpret(state: Turn) -> dict:
    game, raw = state["game"], state.get("raw") or ""
    local = tools.interpret_locally(game, raw)
    if local is not None:
        return {**local, "interpreted_by": "engine"}
    guess = narrator.interpret(tools.scene(game), raw)
    if guess is not None:
        return {**guess, "interpreted_by": "model"}
    # Neither could place it. `none` reaches apply_action and becomes a
    # verbatim refusal, rather than the model being allowed to improvise.
    return {"action": "none", "argument": raw, "interpreted_by": "nobody"}


def act(state: Turn) -> dict:
    """The only node that changes the world, and it uses no model at all."""
    game = state["game"]
    if state.get("resting"):
        # Still asleep on a durable timer. Accept no action: a command taken
        # mid-rest would let the player act while the fire is still burning.
        return {"result": {"beat": "", "verbatim": [], "activity": None,
                           "timer": False, "ending": None, "moved": False},
                "scene": tools.scene(game)}
    before_room = game["room"]
    result = tools.apply_action(game, state.get("action") or "none",
                                state.get("argument") or "")

    verbatim = list(result.get("verbatim") or [])
    runs: list[dict] = []

    # Does this action move the world on? Looking at things does not, and a
    # move into a wall does not either -- it is a refusal, not a turn. Getting
    # this wrong means the curse charges you for reading the help text.
    action = state.get("action") or "none"
    advances = (action in ("choose", "rest", "wake")
                or (action == "walk" and bool(result.get("moved"))))

    if advances:
        game["turn"] += 1

    # Room-entry lines are rule lines: what is here, what just opened. They
    # come after the turn counter moves, as in the single-process original.
    if result.get("moved"):
        verbatim = engine.room_entry_verbatim(game) + verbatim

    # The upkeep the cursed item charges, once per turn it is carried.
    if advances:
        verbatim += engine.apply_upkeep(game)

    # --- the named step -----------------------------------------------------
    # A node cannot put its own name in the history, so the vault moment gets
    # its own workflow. See aux_workflows.
    if result.get("activity") == "secret_vault_found":
        run_id = f"{VAULT_PREFIX}-{state['slot']}-{game['turn']}"
        try:
            from dapr.ext.workflow import DaprWorkflowClient
            DaprWorkflowClient().schedule_new_workflow(
                workflow=secret_vault_found,
                input={"slot": state["slot"], "turn": game["turn"], "room": game["room"]},
                instance_id=run_id)
            runs.append({"kind": "secret_vault_found", "id": run_id})
        except Exception as exc:
            # The game must not die because the audit record did not start.
            logger.error("could not record secret_vault_found: %s", exc)

    # --- the durable rest ---------------------------------------------------
    if result.get("timer"):
        run_id = f"{REST_PREFIX}-{state['slot']}-{game['rests']}"
        try:
            from dapr.ext.workflow import DaprWorkflowClient
            DaprWorkflowClient().schedule_new_workflow(
                workflow=campfire_rest,
                input={"slot": state["slot"], "rests": game["rests"],
                       "seconds": float(game.get("rest_seconds") or config.REST_SECONDS)},
                instance_id=run_id)
            runs.append({"kind": "campfire_rest", "id": run_id})
        except Exception as exc:
            logger.error("could not start the campfire timer: %s", exc)
            verbatim.append("The fire would not catch. The rest did not start.")

    if advances:
        game["log"].append({"turn": game["turn"], "room": before_room,
                            "command": state.get("raw") or "",
                            "action": action})
    return {"game": game, "result": result, "verbatim": verbatim, "runs": runs,
            "scene": tools.scene(game)}


def narrate(state: Turn) -> dict:
    """Prose only. Never sees a verbatim line."""
    result = state.get("result") or {}
    game = state["game"]
    beat = result.get("beat") or ""
    if game.get("ending") or game.get("parked"):
        # An ended or parked adventure gets no new scenery; the verbatim lines
        # already say what happened.
        return {"prose": beat}
    return {"prose": narrator.narrate(tools.scene(game), beat,
                                      arrived=bool(result.get("moved")))}


def save(state: Turn) -> dict:
    game = state["game"]
    save_game(state["slot"], game)
    return {"scene": tools.scene(game)}


def build():
    from langgraph.graph import END, START, StateGraph
    g = StateGraph(Turn)
    g.add_node("load", load)
    g.add_node("interpret", interpret)
    g.add_node("act", act)
    g.add_node("narrate", narrate)
    g.add_node("save", save)
    g.add_edge(START, "load")
    g.add_edge("load", "interpret")
    g.add_edge("interpret", "act")
    g.add_edge("act", "narrate")
    g.add_edge("narrate", "save")
    g.add_edge("save", END)
    return g.compile()

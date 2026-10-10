"""The engine, exposed as the agent's tools.

This module is the boundary that keeps the game honest. The model is allowed to
decide *which* tool to call; the tool decides *what happened*. Every return
value carries two separate fields:

    beat      -- prose the narrator may rewrite
    verbatim  -- lines that print exactly as written, and never reach the model

A rule line ("there is no way north from here", "you have not got 5 gold",
"the door is open, north leads into the vault") only ever travels in
`verbatim`. Hand one to a narrator and it comes back as an event that did not
happen: the purchase that was refused, described as a purchase.

The tools are deterministic and take the game state explicitly, so a replayed
turn produces the same result. Nothing here calls a clock, a die or a network.
"""

from __future__ import annotations

from typing import Any

from ..engine import engine, world

# Actions the model is allowed to ask for. Anything else is not a tool call.
ACTIONS = ("walk", "choose", "look", "status", "help", "rest", "save_and_quit")

# Sent by the client when a campfire's durable timer has fired, carrying the
# event the rest workflow rolled. Not typeable, and never shown to the model:
# the event is already decided and recorded, so this is bookkeeping, not a
# player action.
WAKE_PREFIX = "__wake__"


def scene(state: dict) -> dict:
    """Everything the client needs to draw the current scene.

    Includes the compass reading, which is the cursed item's whole justification
    and is generated from the map rather than from anything the model says.
    """
    return {
        "room": state["room"],
        "title": world.ROOMS[state["room"]]["title"],
        "facts": world.ROOMS[state["room"]]["facts"],
        "prose": world.ROOMS[state["room"]]["prose"],
        "nouns": world.ROOMS[state["room"]].get("nouns") or [],
        "hud": engine.hud(state),
        "exits": engine.exit_lines(state),
        "menu": engine.menu_labels(state),
        "health": state["health"],
        "max_health": state["max_health"],
        "gold": state["gold"],
        "inventory": list(state["inventory"]),
        "turn": state["turn"],
        "carrying_lodestone": state["carrying_lodestone"],
        "door_open": state["door_open"],
        "ending": state["ending"],
    }


def _blank() -> dict:
    return {"beat": "", "verbatim": [], "activity": None, "timer": False,
            "ending": None, "moved": False}


def apply_action(state: dict, action: str, argument: str = "") -> dict:
    """Run one action against the state and return the authoritative result.

    `state` is mutated in place, exactly as the single-process engine expects.
    The caller is responsible for persisting it.
    """
    action = (action or "").strip().lower()
    arg = (argument or "").strip().lower()

    if action == "look":
        # A free action: re-read the room without spending a turn or ticking
        # the curse. The room's own prose is the fallback, never invented.
        out = _blank()
        out["beat"] = world.ROOMS[state["room"]]["prose"]
        return out

    if action == "status":
        out = _blank()
        # Pure arithmetic. Narrating it would turn numbers into adjectives.
        out["verbatim"] = [engine.hud(state)]
        return out

    if action == "help":
        out = _blank()
        # Instructions, so verbatim by definition.
        out["verbatim"] = [
            "Type a number to take a choice, or type what you want to do.",
            "Walk with: north, south, east, west (or n, s, e, w).",
            "`rest` makes camp. `look`, `status`, `help`.",
            "`save and quit` stops the app; the adventure keeps its place.",
        ]
        return out

    if action == "save_and_quit":
        state["parked"] = True
        out = _blank()
        out["verbatim"] = ["Saved. The adventure keeps its place."]
        return out

    if action == "wake":
        # The rest's own workflow already chose the event and recorded it. All
        # that is left is to apply it with the pure function.
        return engine.apply_campfire_event(state, arg)

    if action == "walk":
        direction = world.DIRECTION_ALIASES.get(arg, arg)
        if direction not in world.DIRECTIONS:
            out = _blank()
            out["verbatim"] = [f'"{argument}" is not a direction.']
            return out
        return engine.move(state, direction)

    if action == "choose":
        live = {c["id"]: c for c in engine.available_choices(state)}
        cid = arg
        if cid not in live:
            # Let the model name a choice loosely; resolve it against the live
            # menu rather than refusing on an exact-match technicality.
            intent = engine.parse(state, argument)
            if intent.get("kind") == "choice":
                cid = intent["id"]
            elif intent.get("kind") == "move":
                return engine.move(state, intent["direction"])
        if cid not in live:
            out = _blank()
            out["verbatim"] = [f'"{argument}" is not something you can do here.']
            return out
        return engine.apply_choice(state, cid)

    if action == "rest":
        live = {c["id"] for c in engine.available_choices(state)}
        if "rest_campfire" not in live:
            out = _blank()
            # Say which of the two reasons it is. "Not here" on a player who is
            # simply unhurt is a misleading refusal: it blames the room.
            out["verbatim"] = engine.rest_refusal(state) or []
            return out
        return engine.apply_choice(state, "rest_campfire")

    out = _blank()
    out["verbatim"] = [f'"{argument or action}" is not something you can do here.']
    return out


def interpret_locally(state: dict, raw: str) -> dict | None:
    """Resolve the unambiguous input without spending an LLM call.

    Numbers, directions, and the meta commands are not interpretation problems,
    and sending them to a model adds latency, cost and a chance of being wrong
    about something that was never in doubt. Returns None when the input really
    does need the model.
    """
    text = (raw or "").strip()
    if text == "__restpoll__":
        # Asking "am I awake yet?". The answer is produced in the load node,
        # which resolves the rest; this turn itself must cost nothing.
        return {"action": "look", "argument": ""}
    if text == "__reset__":
        # The save has already been discarded in the load node; all this turn
        # has to do is show the player the room they are starting in.
        return {"action": "look", "argument": ""}
    if text.startswith(WAKE_PREFIX):
        return {"action": "wake", "argument": text[len(WAKE_PREFIX):].strip()}

    intent = engine.parse(state, raw)
    kind = intent.get("kind")
    if kind == "move":
        return {"action": "walk", "argument": intent["direction"]}
    if kind == "choice":
        return {"action": "choose", "argument": intent["id"]}
    if kind == "look":
        return {"action": "look", "argument": ""}
    if kind == "help":
        return {"action": "help", "argument": ""}
    if kind == "save_and_quit":
        return {"action": "save_and_quit", "argument": ""}
    if kind == "noop":
        return {"action": "look", "argument": ""}
    if kind == "resume":
        # Reconnecting is not a turn. Show the room, not the arithmetic: the
        # HUD row already carries the numbers, so a status line here just
        # prints them twice before the player has done anything.
        return {"action": "look", "argument": ""}
    return None

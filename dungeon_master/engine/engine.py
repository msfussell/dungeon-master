"""Pure game rules: state shape, the choice menu, and every state transition.

DESIGN NOTES

* This module is imported by the workflow orchestrator and must stay deterministic:
  no clock, no randomness, no I/O, no mutable module globals. Given the same command
  sequence it must produce byte-identical state, because that is exactly what Dapr
  does to it on every replay.

* STATE SHAPE. One flat JSON-safe dict. Flat because it ends up in the workflow's
  custom status and in activity inputs, and a flat dict diffs readably in the Catalyst
  console. No dataclasses: they would need (de)serialisation shims at four boundaries
  for no gain.

* CHOICE MENU. Choices are data with a `when` predicate. The predicate is the whole
  mechanism behind the hard rule "a choice the player has already taken disappears":
  a once-only choice's predicate consults `taken`, so it is simply not generated
  again. There is no "you already did that" branch anywhere in this file, by
  construction. Choices that are genuinely repeatable (drinking, resting) are gated on
  having an effect — you cannot drink at full health — so no menu entry is ever inert.

* VERBATIM. Every transition returns a `verbatim` list. Those lines are printed
  exactly as written and are never shown to the narrator. Rules, prices, numbers, the
  door's terms and the compass all live there. The narrator only ever rewords `prose`.
"""

from __future__ import annotations

from . import world

MAX_CHOICES = 3  # "up to 3 choices per scene"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def new_state(rest_seconds: int = 120) -> dict:
    return {
        "room": world.START_ROOM,
        "health": world.START_HEALTH,
        "max_health": world.START_HEALTH,
        "gold": world.START_GOLD,
        "inventory": [],
        "visited": [world.START_ROOM],
        # Every choice id the player has ever taken, in order. This is the
        # "every choice the player made" the spec asks us to track; the workflow
        # history is the durable copy, this is the fast one.
        "taken": [],
        "log": [],                 # (turn, room, command) triples, for the timeline
        "turn": 0,
        "carrying_lodestone": False,
        "lodestone_room": world.LODESTONE_START_ROOM,
        "lodestone_taken_ever": False,
        "door_open": False,
        "cheated_merchant": False,
        "ledger_settled": False,
        "rest_seconds": rest_seconds,
        "rests": 0,
        # How many rests have had their waking event applied. A rest whose
        # timer has fired but whose event is not yet applied shows up as
        # rests > last_rest_applied, which is what lets a player quit during a
        # nap and have it resolved by their next turn. The workflow front end
        # never needs it (one run holds the whole nap); the agent front end
        # does. It lives here so there is one state shape, not two.
        "last_rest_applied": 0,
        "ending": None,            # None | "vault" | "death"
        "parked": False,           # set by "save and quit"
        "recent_ambience": [],
    }


def hud(state: dict) -> str:
    inv = ", ".join(state["inventory"]) if state["inventory"] else "nothing"
    return (
        f"health {state['health']}/{state['max_health']}   "
        f"gold {state['gold']}   carrying: {inv}"
    )


# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------

def exit_lines(state: dict) -> list[str]:
    """Exits name their destination once walked; unvisited ones say 'unexplored'."""
    out = []
    for direction, dest in world.exits_of(state["room"]).items():
        if world.is_locked(state["room"], direction, state):
            continue  # a locked door is scenery, not an exit, until it opens
        if dest in state["visited"]:
            out.append(f"{direction} — {world.room(dest)['title']}")
        else:
            out.append(f"{direction} — unexplored")
    return out


def open_directions(state: dict) -> dict[str, str]:
    return {
        d: dest
        for d, dest in world.exits_of(state["room"]).items()
        if not world.is_locked(state["room"], d, state)
    }


# ---------------------------------------------------------------------------
# Choices
#
# Fields: id, room (or None for "any room"), label, priority, when(state).
# `verbs` are extra words the parser will accept besides the menu number.
# ---------------------------------------------------------------------------

def _taken(state, cid):
    return cid in state["taken"]


CHOICES: list[dict] = [
    # --- the cursed item: pick up / put down, available wherever it actually is ---
    {
        "id": "take_lodestone",
        "room": None,
        "priority": 0,
        "label": "lift the ashen lodestone",
        "verbs": ["lift", "take lodestone", "lodestone", "take the lodestone"],
        "when": lambda s: (not s["carrying_lodestone"]
                           and s["lodestone_room"] == s["room"]),
    },
    {
        "id": "drop_lodestone",
        "room": None,
        "priority": 90,
        "label": "set the ashen lodestone down",
        "verbs": ["drop", "set down", "drop lodestone", "put down"],
        "when": lambda s: s["carrying_lodestone"],
    },

    # --- the talking door ---------------------------------------------------
    # The offer is on the menu every single time it is actionable, so the player
    # never has to invent a verb. (Deliberate reading of the spec: "whenever the
    # player is carrying the item" is honoured at the door, because an offer to a
    # door you are not standing at would be an inert menu entry, and inert menu
    # entries are exactly what the playability rules forbid.)
    {
        "id": "offer_lodestone",
        "room": world.DOOR_ROOM,
        "priority": 1,
        "label": "offer the ashen lodestone to the door",
        "verbs": ["offer", "offer lodestone", "give", "give lodestone"],
        "when": lambda s: s["carrying_lodestone"] and not s["door_open"],
    },
    {
        "id": "knock_door",
        "room": world.DOOR_ROOM,
        "priority": 10,
        "label": "knock on the door",
        "verbs": ["knock"],
        "when": lambda s: not _taken(s, "knock_door") and not s["door_open"],
    },
    {
        "id": "listen_door",
        "room": world.DOOR_ROOM,
        "priority": 11,
        "label": "put your ear to the door",
        "verbs": ["listen", "ear"],
        "when": lambda s: not _taken(s, "listen_door") and not s["door_open"],
    },

    # --- collapsed entry ----------------------------------------------------
    {
        "id": "read_banner",
        "room": "collapsed_entry",
        "priority": 10,
        "label": "read the banner",
        "verbs": ["read", "banner"],
        "when": lambda s: not _taken(s, "read_banner"),
    },
    {
        "id": "dig_rubble",
        "room": "collapsed_entry",
        "priority": 11,
        "label": "dig at the rubble",
        "verbs": ["dig", "rubble"],
        "when": lambda s: not _taken(s, "dig_rubble"),
    },

    # --- bone orchard -------------------------------------------------------
    {
        "id": "take_spade",
        "room": "bone_orchard",
        "priority": 10,
        "label": "pull the spade from the soil",
        "verbs": ["spade", "pull"],
        "when": lambda s: not _taken(s, "take_spade"),
    },
    {
        "id": "pick_fruit",
        "room": "bone_orchard",
        "priority": 11,
        "label": "pick a knucklebone from the branches",
        "verbs": ["pick", "fruit", "knucklebone"],
        "when": lambda s: not _taken(s, "pick_fruit"),
    },
    {
        "id": "dig_orchard",
        "room": "bone_orchard",
        "priority": 12,
        "label": "dig where the spade was standing",
        "verbs": ["dig"],
        "when": lambda s: "rusted spade" in s["inventory"] and not _taken(s, "dig_orchard"),
    },

    # --- ember hollow -------------------------------------------------------
    {
        "id": "rest_campfire",
        "room": "ember_hollow",
        "priority": 10,
        "label": "bed down at the campfire and rest",
        "verbs": ["rest", "sleep", "campfire"],
        # Repeatable, but only offered while it would actually do something.
        "when": lambda s: s["health"] < s["max_health"],
    },
    {
        "id": "search_bedroll",
        "room": "ember_hollow",
        "priority": 11,
        "label": "search the bedroll",
        "verbs": ["search", "bedroll"],
        "when": lambda s: not _taken(s, "search_bedroll"),
    },

    # --- reliquary ----------------------------------------------------------
    {
        "id": "drink_spring",
        "room": "reliquary",
        "priority": 11,
        "label": "drink from the spring",
        "verbs": ["drink", "spring"],
        "when": lambda s: s["health"] < s["max_health"],
    },
    {
        "id": "count_niches",
        "room": "reliquary",
        "priority": 12,
        "label": "count the empty niches",
        "verbs": ["count", "niches"],
        "when": lambda s: not _taken(s, "count_niches"),
    },

    # --- glass cistern ------------------------------------------------------
    {
        "id": "break_glass",
        "room": "glass_cistern",
        "priority": 10,
        "label": "break the glass and take the coins",
        "verbs": ["break", "glass", "coins"],
        "when": lambda s: not _taken(s, "break_glass"),
    },
    {
        "id": "follow_reflection",
        "room": "glass_cistern",
        "priority": 11,
        "label": "wait for your reflection to catch up",
        "verbs": ["wait", "reflection"],
        "when": lambda s: not _taken(s, "follow_reflection"),
    },

    # --- merchant -----------------------------------------------------------
    {
        "id": "buy_bandage",
        "room": "merchants_niche",
        "priority": 10,
        "label": "buy the clean bandage",
        "verbs": ["buy bandage", "bandage"],
        "when": lambda s: (not _taken(s, "buy_bandage")
                           and not s["cheated_merchant"]
                           and s["gold"] >= 6),
    },
    {
        "id": "buy_die",
        "room": "merchants_niche",
        "priority": 11,
        "label": "buy the ivory die",
        "verbs": ["buy die", "die"],
        "when": lambda s: (not _taken(s, "buy_die")
                           and not _taken(s, "steal_die")
                           and s["gold"] >= _die_price(s)),
    },
    {
        "id": "steal_die",
        "room": "merchants_niche",
        "priority": 12,
        "label": "pocket the ivory die while Hask is writing",
        "verbs": ["pocket", "steal"],
        "when": lambda s: (not _taken(s, "steal_die")
                           and not _taken(s, "buy_die")),
    },
    {
        "id": "settle_ledger",
        "room": "merchants_niche",
        "priority": 9,
        "label": "settle the ledger with Hask",
        "verbs": ["settle", "ledger", "apologise", "apologize", "pay"],
        "when": lambda s: (s["cheated_merchant"]
                           and not s["ledger_settled"]
                           and s["gold"] >= 10),
    },

    # --- flooded stair ------------------------------------------------------
    {
        "id": "take_lantern",
        "room": "flooded_stair",
        "priority": 10,
        "label": "take the floating lantern",
        "verbs": ["lantern"],
        "when": lambda s: not _taken(s, "take_lantern"),
    },
    {
        "id": "wade_stair",
        "room": "flooded_stair",
        "priority": 11,
        "label": "wade down the seventh step",
        "verbs": ["wade", "step", "stair"],
        "when": lambda s: not _taken(s, "wade_stair"),
    },

    # --- the vault ----------------------------------------------------------
    {
        "id": "speak_dragon",
        "room": world.VAULT_ROOM,
        "priority": 10,
        "label": "speak to the dragon",
        "verbs": ["speak", "talk", "dragon"],
        "when": lambda s: not _taken(s, "speak_dragon"),
    },
    {
        "id": "take_scroll",
        "room": world.VAULT_ROOM,
        "priority": 1,
        "label": "take the glowing durable scroll",
        "verbs": ["take scroll", "scroll", "take"],
        "when": lambda s: True,
    },
]

CHOICES_BY_ID = {c["id"]: c for c in CHOICES}


def _die_price(state: dict) -> int:
    return 4


def available_choices(state: dict) -> list[dict]:
    """The menu. At most MAX_CHOICES, lowest priority number first."""
    if state["ending"]:
        return []
    out = [
        c for c in CHOICES
        if (c["room"] is None or c["room"] == state["room"]) and c["when"](state)
    ]
    out.sort(key=lambda c: c["priority"])
    return out[:MAX_CHOICES]


def menu_labels(state: dict) -> list[str]:
    return [c["label"] for c in available_choices(state)]


# ---------------------------------------------------------------------------
# Transitions
#
# Each returns a dict the orchestrator reads:
#   verbatim : list[str]  lines printed exactly, never narrated
#   beat     : str        a one-line factual beat for the narrator to dress up
#   activity : str|None   name of an extra workflow step to record
#   timer    : bool       the orchestrator should create a durable timer
#   ending   : str|None
# ---------------------------------------------------------------------------

def _result(beat="", verbatim=None, activity=None, timer=False, ending=None, moved=False):
    return {
        "beat": beat,
        "verbatim": list(verbatim or []),
        "activity": activity,
        "timer": timer,
        "ending": ending,
        "moved": moved,
    }


def _damage(state: dict, amount: int) -> list[str]:
    """Apply damage and return any verbatim lines (the death line is a rule line)."""
    state["health"] = max(0, state["health"] - amount)
    if state["health"] <= 0:
        state["ending"] = "death"
        return ["Your health reached 0. The adventure ends here."]
    return []


def apply_upkeep(state: dict) -> list[str]:
    """Per-turn upkeep. The curse bills you here."""
    lines = []
    if state["carrying_lodestone"] and not state["ending"]:
        lines += _damage(state, world.LODESTONE_HEALTH_COST)
        if not state["ending"]:
            lines.append(
                f"The ashen lodestone drinks {world.LODESTONE_HEALTH_COST} health. "
                f"You are at {state['health']}/{state['max_health']}."
            )
            # The bearing is only offered to the living. If that last 2 health was
            # fatal, the stone has nothing more to say.
            lines.append(world.compass_line(state["room"]))
    return lines


def move(state: dict, direction: str) -> dict:
    """Walk. Returns a result dict; refusals are verbatim so they stay exact."""
    opens = open_directions(state)
    if direction not in opens:
        if state["room"] == world.DOOR_ROOM and direction == "north":
            return _result(verbatim=[
                "The door's mouth stays shut. It is not a door you can simply walk through.",
            ])
        return _result(verbatim=[f"There is no way {direction} from here."])
    dest = opens[direction]
    was_visited = dest in state["visited"]
    state["room"] = dest
    if not was_visited:
        state["visited"].append(dest)
    out = _result(beat=f"You walk {direction} into {world.room(dest)['title']}.", moved=True)
    out["first_visit"] = not was_visited
    return out


def room_entry_verbatim(state: dict) -> list[str]:
    """VERBATIM lines that fire on walking into a room, because of what you have done.

    This is where the merchant's memory becomes visible. A state flag the player
    cannot see is not a consequence; being refused service, out loud, every time you
    come back, is. Note that it keeps saying it after the ledger is settled, because
    settling an account is not the same as it never having happened.
    """
    lines: list[str] = []
    if state["room"] == "merchants_niche" and state["cheated_merchant"]:
        if state["ledger_settled"]:
            lines.append('"Settled," says Hask, without looking up. "Not forgotten. '
                         'The entry stays in the book."')
        else:
            lines.append('"You and I have an account open," says Hask. '
                         '"The bandage is not for sale to you."')
    if state["room"] == world.DOOR_ROOM and state["door_open"]:
        lines.append("The door stands open. North leads into the vault.")
    return lines


def apply_choice(state: dict, cid: str) -> dict:
    """Resolve one menu choice. Mutates state, returns a result dict."""
    state["taken"].append(cid)

    # --- the cursed item -------------------------------------------------
    if cid == "take_lodestone":
        state["carrying_lodestone"] = True
        state["lodestone_room"] = None
        state["lodestone_taken_ever"] = True
        if "ashen lodestone" not in state["inventory"]:
            state["inventory"].append("ashen lodestone")
        return _result(
            beat="You lift the lodestone off the plinth. It is heavier than iron that size has any right to be, and it immediately pulls in one direction.",
            # The compass line is deliberately NOT here: apply_upkeep runs immediately
            # after this on the same turn and owns it, so including it would print the
            # bearing twice on the pick-up turn.
            verbatim=[
                "The ashen lodestone is cursed. While you carry it, it takes "
                f"{world.LODESTONE_HEALTH_COST} health from you every turn.",
                "While you carry it, it will tell you how far away what it wants is, and which way to walk.",
            ],
            activity="take_cursed_item",
        )

    if cid == "drop_lodestone":
        state["carrying_lodestone"] = False
        state["lodestone_room"] = state["room"]
        if "ashen lodestone" in state["inventory"]:
            state["inventory"].remove("ashen lodestone")
        # Taken-once bookkeeping must be undone, or the pick-up choice could never
        # come back. `taken` is an audit log, not a lock, for repeatable pairs.
        state["taken"] = [t for t in state["taken"] if t not in ("take_lodestone", "drop_lodestone")]
        return _result(
            beat="You set the lodestone on the floor. The pull stops. So does the bleeding.",
            verbatim=["The ashen lodestone is no longer draining you. It is also no longer pointing anywhere."],
        )

    # --- the talking door -------------------------------------------------
    if cid == "knock_door":
        return _result(
            beat="You knock. The carved mouth opens a crack, considers, and speaks without opening further.",
            # NOTE: these lines state the RULE for opening and give no reason for it.
            # "Bring me what I am owed" was the first draft and was cut, because a debt
            # is a motive and the door's motive is never explained anywhere.
            verbatim=[
                '"Knocking," says the door, "is for doors with locks that matter."',
                '"My keyhole is decoration. When you are holding the right thing, '
                'I will open. Not before."',
            ],
        )

    if cid == "listen_door":
        return _result(
            beat="You put your ear to the black wood. Something enormous is breathing on the other side, slowly, and it is not in a hurry.",
            verbatim=['"That is not for your ear," says the door. "Not yet."'],
        )

    if cid == "offer_lodestone":
        state["door_open"] = True
        state["carrying_lodestone"] = False
        state["lodestone_room"] = None
        if "ashen lodestone" in state["inventory"]:
            state["inventory"].remove("ashen lodestone")
        return _result(
            beat="You hold the lodestone out. The door's mouth opens all the way, takes it, and swallows. Then the whole frame draws back from the wall and the way north is open.",
            verbatim=[
                '"Yes," says the door. "That one."',
                "The door is open. North leads into the vault.",
                "The ashen lodestone is gone. It is no longer draining you, and it is no longer pointing anywhere.",
            ],
            activity="secret_vault_found",
        )

    # --- collapsed entry --------------------------------------------------
    if cid == "read_banner":
        return _result(
            beat="Under the worn teeth there is still a motto, picked out in thread that has outlasted the cloth around it.",
            verbatim=['The banner reads: "WHAT IS WRITTEN HERE IS NOT FORGOTTEN HERE."'],
        )

    if cid == "dig_rubble":
        state["gold"] += 5
        lines = _damage(state, 3)
        return _result(
            beat="You haul stone aside until your hands are ruined, and find a flat leather purse belonging to someone who did not get out.",
            verbatim=["You lose 3 health to the rubble. You find 5 gold."] + lines,
        )

    # --- bone orchard ------------------------------------------------------
    if cid == "take_spade":
        state["inventory"].append("rusted spade")
        return _result(
            beat="The spade comes free with a sound like a tooth leaving a jaw. The soil closes over the hole at once.",
            verbatim=["You are carrying the rusted spade."],
        )

    if cid == "pick_fruit":
        state["inventory"].append("knucklebone")
        return _result(
            beat="You twist a knucklebone off its branch. The tree does not react. The other fruit all turn very slightly towards you.",
            verbatim=["You are carrying a knucklebone."],
        )

    if cid == "dig_orchard":
        state["gold"] += 9
        return _result(
            beat="You dig where the gardener stopped digging, and about a foot down you find what they were putting in rather than taking out: a jar of coins, sealed with wax.",
            verbatim=["You find 9 gold."],
        )

    # --- ember hollow ------------------------------------------------------
    if cid == "rest_campfire":
        state["rests"] += 1
        # The timer and the waking event are the orchestrator's job; this is only
        # the setup beat. The rest's length lives in state so it is fixed in the
        # workflow's input history and cannot drift on replay.
        return _result(
            beat="You lie down on the warm bedroll. The embers do not need tending. Sleep takes you faster than you expected.",
            verbatim=[
                f"You are resting for {state['rest_seconds']} seconds. This is a durable workflow timer: "
                "you can close this app and the rest will still be running when you come back.",
            ],
            timer=True,
            activity="campfire_rest_begin",
        )

    if cid == "search_bedroll":
        state["gold"] += 3
        return _result(
            beat="Under the bedroll, pressed flat, is a folded square of paper with nothing written on it, and three coins someone was saving for a journey.",
            verbatim=["You find 3 gold."],
        )

    # --- reliquary ---------------------------------------------------------
    if cid == "drink_spring":
        before = state["health"]
        state["health"] = min(state["max_health"], state["health"] + 6)
        return _result(
            beat="The water is so cold it hurts your teeth, and it tastes faintly of ink.",
            verbatim=[f"You recover {state['health'] - before} health. You are at {state['health']}/{state['max_health']}."],
        )

    if cid == "count_niches":
        return _result(
            beat="You count for a long time. You get eight hundred and ninety-nine empty, and one that is not empty but holds nothing — a niche with a shape worn into its dust.",
            verbatim=["The one occupied niche is empty. Whatever belongs in it is out on the plinth."]
            if state["lodestone_room"] == "reliquary"
            else ["The one occupied niche is empty. Whatever belongs in it is not in this room any more."],
        )

    # --- glass cistern -----------------------------------------------------
    if cid == "break_glass":
        state["gold"] += 14
        lines = _damage(state, 4)
        return _result(
            beat="You bring your heel down. The glass gives all at once, in one note, and you go in to the knee among the coins. The water underneath is not cold. It is nothing at all.",
            verbatim=["You lose 4 health on the broken glass. You take 14 gold."] + lines,
        )

    if cid == "follow_reflection":
        return _result(
            beat="You stand still. Your reflection arrives, settles into place, and for one moment the two of you are in perfect agreement. Then it looks up at something behind you that is not there.",
            verbatim=["You feel steadier. Nothing about your condition has changed."],
        )

    # --- the merchant ------------------------------------------------------
    if cid == "buy_bandage":
        state["gold"] -= 6
        before = state["health"]
        state["health"] = min(state["max_health"], state["health"] + 8)
        return _result(
            beat="Hask takes the coins, counts them without appearing to, and binds your worst hand himself.",
            verbatim=[
                "You pay 6 gold for the clean bandage.",
                f"You recover {state['health'] - before} health. You are at {state['health']}/{state['max_health']}.",
            ],
            activity="trade_with_merchant",
        )

    if cid == "buy_die":
        price = _die_price(state)
        state["gold"] -= price
        state["inventory"].append("ivory die")
        return _result(
            beat="Hask writes the sale in the ledger, one line, and slides the die across with two fingers.",
            verbatim=[f"You pay {price} gold for the ivory die.", "You are carrying the ivory die."],
            activity="trade_with_merchant",
        )

    if cid == "steal_die":
        state["cheated_merchant"] = True
        state["inventory"].append("ivory die")
        return _result(
            beat="You take the die while Hask is writing. He does not look up, does not stop writing, and finishes the line he was on. Then he writes another one.",
            verbatim=[
                "You have the ivory die. You paid nothing for it.",
                "Hask wrote it down.",
            ],
            activity="cheat_the_merchant",
        )

    if cid == "settle_ledger":
        state["gold"] -= 10
        state["ledger_settled"] = True
        return _result(
            beat="You put ten gold on the stall. Hask counts it, writes a second line under the first, and draws no line through either.",
            verbatim=[
                "You pay 10 gold to settle the ledger.",
                "Hask will still sell to you. The entry stays in the ledger.",
            ],
            activity="settle_the_ledger",
        )

    # --- flooded stair -----------------------------------------------------
    if cid == "take_lantern":
        state["inventory"].append("lit lantern")
        return _result(
            beat="You lift the lantern out of the water. It is dry. It has been floating in there long enough to have rotted twice over, and it is dry.",
            verbatim=["You are carrying the lit lantern."],
        )

    if cid == "wade_stair":
        lines = _damage(state, 5)
        return _result(
            beat="You put your weight on the seventh step. There is no seventh step. There is no eighth either. Something far down takes polite hold of your ankle, decides against it, and lets go. You get back up the stair faster than you went down it.",
            verbatim=["You lose 5 health in the water."] + lines,
        )

    # --- the vault ---------------------------------------------------------
    if cid == "speak_dragon":
        return _result(
            beat="You ask the dragon what it is guarding. It answers in a voice that arrives in your chest before your ears.",
            verbatim=[
                '"A record," says the dragon. "Every step of it. Including this one."',
                '"Take it if you like. It will still say what you did."',
            ],
        )

    if cid == "take_scroll":
        state["inventory"].append("durable scroll")
        state["ending"] = "vault"
        return _result(
            beat="You lift the scroll off the stone table. The dragon watches you do it and does nothing whatsoever, which is somehow much worse. The light does not dim in your hands.",
            verbatim=["You are carrying the durable scroll."],
            ending="vault",
            activity="claim_durable_scroll",
        )

    return _result(verbatim=["Nothing comes of that."])


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

REST_VERBS = ("rest", "sleep", "campfire", "bed down")


def rest_refusal(state: dict) -> list[str] | None:
    """Why `rest` is unavailable here -- or None when it is available.

    The rest choice is gated on being hurt, which means a player at full health
    who types `rest` must not be told "not here": it is not the room that is
    wrong, it is that they do not need it. Both front ends print whatever this
    returns, verbatim, so the explanation cannot drift between them.
    """
    if any(c["id"] == "rest_campfire" for c in available_choices(state)):
        return None
    if state["room"] != world.CAMPFIRE_ROOM:
        return list(world.REST_REFUSAL_NO_CAMPFIRE)
    return list(world.REST_REFUSAL_FULL_HEALTH)


def parse(state: dict, raw: str) -> dict:
    """Turn typed text into an intent.

    Accepts: menu numbers, direction words and letters, the verbs declared on each
    live choice, plus a few meta commands. Deliberately permissive about matching
    a choice's label words, because a text adventure that argues about phrasing is
    not fun.
    """
    cmd = (raw or "").strip().lower()
    if not cmd:
        return {"kind": "noop"}

    # The client sends this on reconnect. It is not typeable by the player.
    if cmd == "__resume__":
        return {"kind": "resume"}

    if cmd in ("save and quit", "save & quit", "save", "quit", "exit"):
        return {"kind": "save_and_quit"}
    if cmd in ("look", "l", "look around"):
        return {"kind": "look"}
    if cmd in ("help", "?", "commands"):
        return {"kind": "help"}

    if cmd in world.DIRECTION_ALIASES:
        return {"kind": "move", "direction": world.DIRECTION_ALIASES[cmd]}
    for prefix in ("go ", "walk ", "head ", "move "):
        if cmd.startswith(prefix):
            tail = cmd[len(prefix):].strip()
            if tail in world.DIRECTION_ALIASES:
                return {"kind": "move", "direction": world.DIRECTION_ALIASES[tail]}

    live = available_choices(state)

    if cmd.isdigit():
        idx = int(cmd) - 1
        if 0 <= idx < len(live):
            return {"kind": "choice", "id": live[idx]["id"]}
        return {"kind": "unknown", "raw": cmd}

    # Exact-ish label match, then declared verbs, then a loose word overlap.
    for c in live:
        if cmd == c["label"].lower():
            return {"kind": "choice", "id": c["id"]}
    for c in live:
        for v in c["verbs"]:
            if cmd == v or cmd.startswith(v + " ") or v in cmd:
                return {"kind": "choice", "id": c["id"]}
    for c in live:
        words = {w for w in c["label"].lower().split() if len(w) > 3}
        if words & set(cmd.split()):
            return {"kind": "choice", "id": c["id"]}

    return {"kind": "unknown", "raw": cmd}


# ---------------------------------------------------------------------------
# The campfire rest's waking event
# ---------------------------------------------------------------------------

def apply_campfire_event(state: dict, event_id: str) -> dict:
    """Apply the base rest plus one random waking event. PURE and replay-safe:
    the random roll already happened in an activity; this only applies its result."""
    event = world.CAMPFIRE_EVENTS_BY_ID[event_id]
    verbatim = []

    before = state["health"]
    state["health"] = min(state["max_health"], state["health"] + world.REST_BASE_HEAL)
    healed = state["health"] - before
    verbatim.append(f"The rest is over. You recover {healed} health from sleeping.")

    if event["health"] > 0:
        before = state["health"]
        state["health"] = min(state["max_health"], state["health"] + event["health"])
        if state["health"] - before:
            verbatim.append(f"You recover a further {state['health'] - before} health.")
    elif event["health"] < 0:
        verbatim.append(f"You lose {abs(event['health'])} health.")
        verbatim += _damage(state, abs(event["health"]))

    if event["gold"]:
        state["gold"] += event["gold"]
        verbatim.append(f"You find {event['gold']} gold where they were sitting.")

    if not state["ending"]:
        verbatim.append(f"You are at {state['health']}/{state['max_health']} health.")

    return _result(beat=event["beat"], verbatim=verbatim, activity=None)

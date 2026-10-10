"""The world: map, rooms, prose, nouns, choices, and the lodestone's compass maths.

DESIGN NOTES (decisions made here, deliberately, without consulting anything else)

* The map is a coordinate grid, not a bag of rooms with arbitrary links. Every room
  owns an (x, y) and exits are derived from neighbouring coordinates. That buys two
  things for free: (a) the compass in `bearing_to` is real arithmetic rather than a
  hand-maintained lookup table, and (b) it is impossible to author an exit that leads
  somewhere non-euclidean, which is the classic text-adventure map bug.

* Everything in this module is PURE DATA + PURE FUNCTIONS. It is imported by the
  workflow orchestrator, which replays. Nothing here may touch the clock, the
  network, randomness or global mutable state, or a replay would diverge. Random
  flavour selection lives in an activity (see activities.py), never here.

* Prose lives here as the no-API-key fallback AND as the ground truth handed to the
  narrator. The narrator rewords `prose`; it is never allowed near `verbatim` lines.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------
# Layout (x grows east, y grows north). The vault sits behind the talking door,
# which is the north wall of the Hall of Teeth.
#
#                        (0,2)  Vault of the Long Memory
#                                      |  <- the talking door
#   (-1,1) Merchant's Niche --- (0,1) Hall of Teeth --- (1,1) Flooded Stair
#                                      |
#   (-1,0) Ember Hollow ------- (0,0) Collapsed Entry -- (1,0) Bone Orchard
#                                      |
#                        (0,-1) Reliquary ------------- (1,-1) Glass Cistern

START_ROOM = "collapsed_entry"
VAULT_ROOM = "vault_of_long_memory"
DOOR_ROOM = "hall_of_teeth"
LODESTONE_START_ROOM = "reliquary"
CAMPFIRE_ROOM = "ember_hollow"

# What the cursed item is drawn towards. The player is never told this coordinate;
# they are only ever told a distance and a direction.
LODESTONE_TARGET = (0, 2)

START_HEALTH = 30
START_GOLD = 12
# Carrying the lodestone costs this much health every turn. That is the trade:
# perfect navigation, paid for in blood.
LODESTONE_HEALTH_COST = 2

ROOMS: dict[str, dict] = {
    "collapsed_entry": {
        "title": "The Collapsed Entry",
        "coord": (0, 0),
        "nouns": ["rubble", "staircase", "banner", "draught"],
        "prose": (
            "Half a staircase hangs above you, snapped off mid-flight and going nowhere. "
            "The way you came in is gone — a slow slide of rubble took it some time last "
            "century. A rotted banner still clings to one wall, its device worn down to a "
            "suggestion of teeth. A cold draught comes from the north, and it smells of "
            "old paper."
        ),
        "facts": "A broken staircase, impassable rubble where the entrance was, a rotted banner, a cold draught from the north smelling of paper.",
        "ambience": [
            "Grit shifts somewhere above you and does not finish falling.",
            "The banner stirs, though you feel no wind.",
            "Something in the rubble settles with a sound like a held breath.",
        ],
    },
    "bone_orchard": {
        "title": "The Bone Orchard",
        "coord": (1, 0),
        "nouns": ["trees", "ribs", "fruit", "spade"],
        "prose": (
            "Someone planted ribs here in rows, and the rows took. Pale trees of bone "
            "stand in neat ranks, and from their branches hang fruit that is not fruit: "
            "smooth grey knucklebones, swaying. A rusted spade has been left driven into "
            "the soil, as if the gardener meant to come back."
        ),
        "facts": "Rows of trees grown from ribs, knucklebone fruit hanging from branches, a rusted spade driven into the soil.",
        "ambience": [
            "The knucklebone fruit knock together, counting something.",
            "A branch creaks and bends towards you, then thinks better of it.",
            "The soil here is warm. Nothing explains why.",
        ],
    },
    "ember_hollow": {
        "title": "The Ember Hollow",
        "coord": (-1, 0),
        "nouns": ["campfire", "embers", "bedroll", "chimney"],
        "prose": (
            "A bowl of stone, scorched black at its centre, where a campfire has been "
            "burning longer than any wood should allow. The embers never grey. A bedroll "
            "lies beside it, laid out neatly for someone, and a natural chimney in the "
            "roof draws the smoke up and away into the dark."
        ),
        "facts": "A stone bowl with a campfire of embers that never die, a neatly laid bedroll, a natural chimney in the roof.",
        "ambience": [
            "The embers brighten as if someone leaned in to blow on them.",
            "The bedroll is warm. It has been warm since before you arrived.",
            "Smoke climbs the chimney in a perfectly straight line.",
        ],
    },
    "reliquary": {
        "title": "The Reliquary",
        "coord": (0, -1),
        "nouns": ["plinth", "lodestone", "niches", "spring"],
        "prose": (
            "Nine hundred small niches in the walls, and eight hundred and ninety-nine of "
            "them empty. The one that is not holds nothing — its relic sits instead on a "
            "plinth in the middle of the floor, set out in the open like bait: the ashen "
            "lodestone, a fist of grey iron with a seam of something brighter through it. "
            "A thin spring runs down the far wall into a basin."
        ),
        "facts": "Nine hundred wall niches, nearly all empty. A plinth in the middle of the room. A thin spring running into a basin.",
        "ambience": [
            "The empty niches breathe out a draught that smells of rust.",
            "Water finds the basin, drop by patient drop.",
            "Your shadow arrives on the far wall a moment after you do.",
        ],
    },
    "glass_cistern": {
        "title": "The Glass Cistern",
        "coord": (1, -1),
        "nouns": ["water", "glass", "coins", "reflection"],
        "prose": (
            "The floor is water, and the water is glass — frozen mid-ripple, hard enough "
            "to stand on. Beneath it, coins lie scattered across the real floor, a drowned "
            "payroll a few inches down and utterly out of reach. Your reflection walks "
            "under you, slightly out of step."
        ),
        "facts": "A floor of glass-hard frozen water, coins visible beneath it and out of reach, a reflection that lags behind the player.",
        "ambience": [
            "Your reflection stops walking before you do.",
            "Something moves under the glass, between you and the coins.",
            "The glass sings faintly under your weight, one clear note.",
        ],
    },
    "hall_of_teeth": {
        "title": "The Hall of Teeth",
        "coord": (0, 1),
        "nouns": ["door", "pillars", "hinges", "keyhole"],
        "prose": (
            "Pillars run the length of this hall, each carved as a jaw, each jaw open. "
            "At the north end stands a door of black wood banded in iron, taller than it "
            "needs to be. It has hinges, a frame, a keyhole — and a mouth, carved deep "
            "across its middle, which is at this moment closed."
        ),
        "facts": "A hall of pillars carved as open jaws. A tall black door banded in iron at the north end, with hinges, a keyhole and a carved mouth.",
        "ambience": [
            "One of the pillar-jaws has closed since you last looked. You are fairly sure.",
            "The door's mouth works silently, as if tasting the air.",
            "Your footsteps arrive back from the north end a beat too late.",
        ],
    },
    "merchants_niche": {
        "title": "The Merchant's Niche",
        "coord": (-1, 1),
        "nouns": ["Hask", "ledger", "bandage", "die", "stall"],
        "prose": (
            "A stall, in a dungeon, lit better than anywhere else you have been. Behind it "
            "stands Hask — grey, patient, entirely unsurprised to see you — with a ledger "
            "open at his elbow and a pen already uncapped. His stock is thin and well "
            "chosen: a clean bandage, and a small ivory die, yellowed with handling."
        ),
        "facts": "A well-lit market stall run by a merchant named Hask, who keeps an open ledger and an uncapped pen. His stock: a clean bandage and a small ivory die.",
        "ambience": [
            "Hask turns a page of the ledger without looking down.",
            "Hask's pen hovers, then writes one short word.",
            "Hask watches your hands, pleasantly, and does not pretend otherwise.",
        ],
    },
    "flooded_stair": {
        "title": "The Flooded Stair",
        "coord": (1, 1),
        "nouns": ["stair", "water", "lantern", "handrail"],
        "prose": (
            "A stair going down into black water, which is going nowhere. Six steps are "
            "visible; the seventh is a guess. A lantern floats upright against the "
            "handrail, still lit, as though set down a moment ago by someone who has not "
            "yet come back up."
        ),
        "facts": "A stairway descending into still black water, six steps visible, a lit lantern floating upright against the handrail.",
        "ambience": [
            "The water has not moved since you came in. Not once.",
            "The lantern turns slowly to face you.",
            "Six steps. You count them again and get six.",
        ],
    },
    "vault_of_long_memory": {
        "title": "The Vault of the Long Memory",
        "coord": (0, 2),
        "nouns": ["dragon", "scroll", "hoard", "scales"],
        "prose": (
            "The vault is one enormous room and most of it is dragon. It lies curled "
            "around a low stone table, scales the colour of cooling iron, one eye open and "
            "steady on you. On the table, under nothing, guarded by everything: a scroll, "
            "and the scroll is glowing. Its light is not firelight. It does not flicker, "
            "and it has clearly not flickered in a very long time."
        ),
        "facts": "An enormous vault. A dragon with iron-coloured scales curled around a low stone table, one eye open. On the table a glowing scroll whose light never flickers.",
        "ambience": [
            "The dragon breathes out. The scroll's light does not move.",
            "A scale shifts against a scale, somewhere down the long body.",
            "The dragon's open eye tracks you and does not blink.",
        ],
    },
}

# Global flavour pool, mixed with the per-room pools so that repeated visits to the
# same room do not reuse the same three lines. (Rule: a fixed per-turn line is
# wallpaper by turn 3.)
GLOBAL_AMBIENCE = [
    "The dark here has edges, and you keep finding them.",
    "Far off, stone moves against stone, and stops.",
    "You have the specific feeling of being counted.",
    "The air tastes of cold ink.",
    "Something very old turns over in its sleep and does not wake.",
    "A draught crosses your ankles, going the wrong way.",
]

DIRECTIONS = {
    "north": (0, 1),
    "south": (0, -1),
    "east": (1, 0),
    "west": (-1, 0),
}

DIRECTION_ALIASES = {
    "n": "north", "north": "north", "up": "north",
    "s": "south", "south": "south", "down": "south",
    "e": "east", "east": "east",
    "w": "west", "west": "west",
}

_BY_COORD = {room["coord"]: rid for rid, room in ROOMS.items()}


def room(room_id: str) -> dict:
    return ROOMS[room_id]


def exits_of(room_id: str) -> dict[str, str]:
    """Derive exits from the coordinate grid, so the map cannot be inconsistent."""
    x, y = ROOMS[room_id]["coord"]
    out = {}
    for name, (dx, dy) in DIRECTIONS.items():
        neighbour = _BY_COORD.get((x + dx, y + dy))
        if neighbour is not None:
            out[name] = neighbour
    return out


def is_locked(from_room: str, direction: str, state: dict) -> bool:
    """The only locked edge in the world is the talking door."""
    if from_room == DOOR_ROOM and direction == "north":
        return not state.get("door_open", False)
    # The vault's way back out is never locked; the dragon simply does not care.
    return False


def nouns_for(room_id: str, state: dict) -> list[str]:
    """Interactable nouns to highlight in the prose, including carried/present items."""
    ns = list(ROOMS[room_id]["nouns"])
    if state.get("lodestone_room") == room_id and not state.get("carrying_lodestone"):
        ns.append("lodestone")
    if state.get("carrying_lodestone"):
        ns.append("lodestone")
    return sorted(set(ns), key=len, reverse=True)


# ---------------------------------------------------------------------------
# The compass. The cursed item's only kindness.
# ---------------------------------------------------------------------------

def bearing_to(room_id: str, target: tuple[int, int] = LODESTONE_TARGET) -> tuple[int, str]:
    """Return (manhattan distance, direction word) from a room to the target."""
    x, y = ROOMS[room_id]["coord"]
    tx, ty = target
    dx, dy = tx - x, ty - y
    dist = abs(dx) + abs(dy)
    if dist == 0:
        return 0, "here"
    # Walk the dominant axis first; ties break north/south, which suits this map.
    if abs(dy) >= abs(dx):
        return dist, "north" if dy > 0 else "south"
    return dist, "east" if dx > 0 else "west"


def compass_line(room_id: str) -> str:
    """VERBATIM line. The lodestone states a distance and a direction, nothing else.

    It never says what it is pulling towards and it never says why.
    """
    dist, direction = bearing_to(room_id)
    if dist == 0:
        return "The ashen lodestone is still in your hand, and for the first time it is still."
    if dist == 1:
        return f"The ashen lodestone pulls {direction}. One room, no more. It is almost warm."
    return f"The ashen lodestone pulls {direction}. {dist} rooms between it and what it wants."


# ---------------------------------------------------------------------------
# The campfire rest
# ---------------------------------------------------------------------------
# The rest itself is a durable workflow timer. When it elapses, ONE of these wakes
# the player. Which one is chosen at RANDOM INSIDE AN ACTIVITY, never in the
# orchestrator — the orchestrator only ever receives the chosen id back and applies
# its effects with the pure function in engine.apply_campfire_event, so a replay
# re-applies the same event instead of rolling again.

# Why `rest` is unavailable, when it is. The rest choice is gated on being
# hurt, so a player at full health who types `rest` must not be told "not
# here" -- it is not the room that is wrong, it is that they do not need it.
# Both front ends print these verbatim.
REST_REFUSAL_NO_CAMPFIRE = ["There is no campfire here to rest at."]
REST_REFUSAL_FULL_HEALTH = [
    "You are at full health, so there is nothing to sleep off.",
    "Rest here when something has hurt you.",
]


REST_BASE_HEAL = 12

CAMPFIRE_EVENTS: list[dict] = [
    {
        "id": "embers_flare",
        "beat": "The embers go up all at once, roaring to the height of a man, and you are on your feet before you are awake. By the time you can see, the fire is low again and perfectly ordinary.",
        "health": 4,
        "gold": 0,
    },
    {
        "id": "a_visitor_left",
        "beat": "You wake because the warmth on your left has gone. Someone was sitting across the fire from you, close enough to share it, and they have only just stood up. The dust where they sat is pressed flat and still settling.",
        "health": 0,
        "gold": 7,
    },
    {
        "id": "cold_snap",
        "beat": "You wake with frost in your eyelashes. For some part of the night the fire that cannot go out went out, and whatever took the heat has only just given it back.",
        "health": -5,
        "gold": 0,
    },
    {
        "id": "your_name",
        "beat": "You wake because something a long way off, through a great deal of stone, said your name once and then stopped. It was a wooden sort of voice.",
        "health": 0,
        "gold": 0,
    },
    {
        "id": "knucklebones",
        "beat": "You wake to a rattle like dice in a cup — a hundred small bones knocking together somewhere east of here, all at once, and then nothing.",
        "health": 0,
        "gold": 0,
    },
    {
        "id": "the_spade_moved",
        "beat": "You wake rested, and find the rusted spade standing upright in the stone beside your head, driven a hand deep into rock that has no give in it at all.",
        "health": 2,
        "gold": 0,
    },
]

CAMPFIRE_EVENTS_BY_ID = {e["id"]: e for e in CAMPFIRE_EVENTS}


# VERBATIM. Printed exactly, as the first thing the player ever reads: it says
# what they are looking for. A narrator handed a goal turns it into atmosphere,
# and the player never learns what they are doing here. Shared, because both
# front ends open with it.
OPENING = (
    "You are looking for the durable scroll: the one record in this place that cannot "
    "be lost, however the world goes. It is sealed in a vault, and you do not know where."
)

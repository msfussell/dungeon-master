"""The orchestrator. The workflow's history IS the save file.

DESIGN NOTES

* WHY A WORKFLOW IS A SAVE FILE AT ALL. Every mutation of game state in here is the
  deterministic consequence of (a) the workflow input and (b) the ordered list of
  `player_command` external events in the history. So the history does not *describe*
  the save, it *is* the save: Dapr reconstructs `state` by replaying this function.
  There is no database and no file on disk, and there is nothing to keep in sync.

* HOW THE PLAYER AND THE WORKFLOW TALK.
    player -> workflow : raise_workflow_event("player_command", {"command": "..."})
    workflow -> player : ctx.set_custom_status(json.dumps(scene))
  The client polls custom status and redraws when `seq` changes. `seq` is just a
  counter over publishes, so it is a pure function of the command sequence and stays
  identical across replays. This is why the client can be killed at any instant and
  lose nothing: the current scene is always sitting in the workflow's own status.

* DETERMINISM RAILS. No random, no wall clock, no I/O, no env reads in this function.
  The rest duration arrives in the workflow *input* so it is pinned in history and
  cannot drift if someone edits .env mid-rest. The campfire's random event is rolled
  in an activity and only its *result* is applied here. Time comes from
  ctx.current_utc_datetime, which is the replay-safe clock.

* VERBATIM DISCIPLINE. `verbatim` lines travel from engine.py to the client in their
  own field and are never passed to a narrate activity. The narrator physically cannot
  paraphrase a rule it is never shown.
"""

from __future__ import annotations

import json
from datetime import timedelta

import dapr.ext.workflow as wf

from ..engine import engine, world
from . import activities

PLAYER_COMMAND = "player_command"
RESUME_COMMAND = "__resume__"


HELP_LINES = [
    "Type a number to take a choice, or type what you want to do.",
    "Walk with: north, south, east, west (or n, s, e, w).",
    "Other commands: look, help, save and quit.",
    "The highlighted words in the prose are things you can act on.",
]

MAX_PROSE = 900  # keep custom status comfortably small


def _scene(ctx, state, seq, narration, verbatim, recap=None, notice=None,
           resting=False, rest_due=None, ending=None, opening=None):
    prose = (narration or {}).get("prose", "") or ""
    return {
        "seq": seq,
        "turn": state["turn"],
        "instance": ctx.instance_id,
        "room": state["room"],
        "title": world.room(state["room"])["title"],
        "prose": prose[:MAX_PROSE],
        "ambience": (narration or {}).get("ambience"),
        "narrator": (narration or {}).get("narrator"),
        "nouns": world.nouns_for(state["room"], state),
        "verbatim": list(verbatim or []),
        "opening": opening,
        "recap": recap,
        "notice": list(notice or []),
        "menu": engine.menu_labels(state),
        "exits": engine.exit_lines(state),
        "hud": engine.hud(state),
        "health": state["health"],
        "gold": state["gold"],
        "inventory": list(state["inventory"]),
        # Which rooms the player has stood in. The map on the device is fog of
        # war and needs this; a map that showed the whole grid would hand over
        # the layout and undo both the exploration and the lodestone, which is
        # only worth carrying because it is the one thing that knows the way.
        "visited": list(state["visited"]),
        "choices_made": list(state["taken"]),
        "cheated_merchant": state["cheated_merchant"],
        "door_open": state["door_open"],
        "carrying_lodestone": state["carrying_lodestone"],
        "parked": state["parked"],
        "resting": resting,
        "rest_due": rest_due,
        "rest_seconds": state["rest_seconds"],
        "ending": ending,
        # A full scene, not a notice-only redraw. See _redraw.
        "redraw": False,
    }


def _redraw(scene: dict, seq: int, notice: list[str]) -> str:
    """A notice-only republish of the SAME scene.

    Typing `help`, or a command the game does not understand, or walking into a wall
    must not reprint the prose — and, much worse, must not reprint verbatim lines the
    player has already been shown. Re-showing "The banner reads ..." a second time
    reads as the banner having been read again, which is exactly the kind of invented
    event the verbatim rule exists to prevent. So this strips the narrative fields and
    the client renders a short block: the notice, the exits, the menu, the HUD.
    """
    return json.dumps({
        **scene,
        "seq": seq,
        "notice": list(notice),
        "verbatim": [],
        "prose": "",
        "ambience": None,
        "opening": None,
        "recap": None,
        "redraw": True,
    })


ENDINGS = {
    # VERBATIM endings. The booth line in particular must print exactly.
    "vault": [
        "You have the durable scroll. The adventure is over, and it remembers all of it.",
        "Show this run to the Diagrid booth to claim your reward.",
    ],
    "death": [
        "You do not get back up. The adventure is over.",
        "The run is still here. It remembers every step you took to get this far.",
    ],
}


def dungeon_master(ctx: wf.DaprWorkflowContext, inp: dict):
    inp = inp or {}
    state = engine.new_state(int(inp.get("rest_seconds", 120)))

    seq = 0
    pending_beat = ""
    pending_verbatim = []
    pending_recap = None
    first_visit = True

    while True:
        # ---------------------------------------------------------------
        # 1. Narrate and publish the current scene.
        # ---------------------------------------------------------------
        narration = yield ctx.call_activity(
            activities.narrate_scene,
            input={
                "room": state["room"],
                "first_visit": first_visit,
                "beat": pending_beat,
                "carrying_lodestone": state["carrying_lodestone"],
                "recent": state["recent_ambience"],
            },
        )
        state["recent_ambience"] = (state["recent_ambience"] + [narration.get("ambience")])[-4:]
        first_visit = False  # consumed; only a move into a new room sets it again

        if state["ending"]:
            seq += 1
            ctx.set_custom_status(json.dumps(_scene(
                ctx, state, seq, narration,
                pending_verbatim + ENDINGS[state["ending"]],
                recap=pending_recap, ending=state["ending"],
            )))
            break

        seq += 1
        # The opening line leads the very first scene: one line telling the player
        # what they are looking for, before any prose.
        scene = _scene(ctx, state, seq, narration, pending_verbatim,
                       recap=pending_recap,
                       opening=world.OPENING if seq == 1 else None)
        ctx.set_custom_status(json.dumps(scene))
        pending_beat, pending_verbatim, pending_recap = "", [], None

        # ---------------------------------------------------------------
        # 2. Consume commands until one actually advances the scene.
        #    Refusals, help and unknown input re-publish the SAME scene with a
        #    notice rather than burning a narration call — and, more importantly,
        #    rather than inventing a turn that did not happen.
        # ---------------------------------------------------------------
        advanced = False
        while not advanced:
            event = yield ctx.wait_for_external_event(PLAYER_COMMAND)
            raw = (event or {}).get("command", "") if isinstance(event, dict) else str(event or "")
            intent = engine.parse(state, raw)
            kind = intent["kind"]

            if kind == "noop":
                continue

            if kind == "help":
                seq += 1
                ctx.set_custom_status(_redraw(scene, seq, HELP_LINES))
                continue

            if kind == "save_and_quit":
                yield ctx.call_activity(
                    activities.save_and_quit,
                    input={"room": state["room"], "turn": state["turn"]},
                )
                state["parked"] = True
                seq += 1
                parked = json.loads(_redraw(scene, seq, [
                    "Saved. This run is parked exactly here.",
                    "Start the app again and you will come back to this moment.",
                ]))
                parked["parked"] = True
                ctx.set_custom_status(json.dumps(parked))
                continue  # the workflow simply keeps waiting; that IS the save

            if kind == "resume":
                recap = yield ctx.call_activity(
                    activities.recap_moment,
                    input={
                        "room": state["room"],
                        "turn": state["turn"],
                        "inventory": state["inventory"],
                    },
                )
                state["parked"] = False
                pending_recap = recap
                pending_beat = ""
                advanced = True
                continue

            if kind == "look":
                advanced = True  # re-narrate, fresh prose, no state change
                continue

            if kind == "unknown":
                seq += 1
                raw_cmd = (intent.get("raw") or "").strip().lower()
                # A rest the player cannot take yet is not an unknown command:
                # say why, from the engine, rather than blaming the room.
                refusal = (engine.rest_refusal(state)
                           if any(raw_cmd.startswith(v) for v in engine.REST_VERBS)
                           else None)
                lines = refusal or ([
                    f'"{intent["raw"]}" is not something you can do here.'
                ] + HELP_LINES[:2])
                ctx.set_custom_status(_redraw(scene, seq, lines))
                continue

            # ---------------- a real move ----------------
            if kind == "move":
                before = state["room"]
                result = engine.move(state, intent["direction"])
                if not result["moved"]:
                    seq += 1
                    ctx.set_custom_status(_redraw(scene, seq, result["verbatim"]))
                    continue
                first_visit = result["first_visit"]
                yield ctx.call_activity(
                    activities.enter_room,
                    input={"room": state["room"], "from": before, "turn": state["turn"] + 1},
                )
                state["turn"] += 1
                state["log"].append([state["turn"], state["room"], f"go {intent['direction']}"])
                pending_beat = result["beat"]
                pending_verbatim = (list(result["verbatim"])
                                    + engine.room_entry_verbatim(state)
                                    + engine.apply_upkeep(state))
                advanced = True
                continue

            # ---------------- a real choice ----------------
            if kind == "choice":
                cid = intent["id"]
                result = engine.apply_choice(state, cid)
                state["turn"] += 1
                state["log"].append([state["turn"], state["room"], cid])
                verbatim = list(result["verbatim"])

                if result["activity"]:
                    yield ctx.call_activity(
                        activities.STORY_ACTIVITIES[result["activity"]],
                        input={
                            "room": state["room"],
                            "turn": state["turn"],
                            "choice": cid,
                            "seconds": state["rest_seconds"],
                        },
                    )

                # ---- the durable campfire rest -------------------------
                if result["timer"]:
                    due = ctx.current_utc_datetime + timedelta(seconds=state["rest_seconds"])
                    seq += 1
                    ctx.set_custom_status(json.dumps(_scene(
                        ctx, state, seq, narration, verbatim,
                        resting=True, rest_due=due.isoformat(),
                    )))
                    # A real workflow timer, not time.sleep. The process can die here
                    # and Catalyst will still wake this instance when it is due.
                    yield ctx.create_timer(timedelta(seconds=state["rest_seconds"]))
                    woken = yield ctx.call_activity(
                        activities.campfire_event, input={"room": state["room"]}
                    )
                    wake = engine.apply_campfire_event(state, woken["event_id"])
                    pending_beat = woken.get("prose") or wake["beat"]
                    # REPLACE, do not extend: `verbatim` still holds the "you are
                    # resting for N seconds" setup line, which was already printed on
                    # the sleeping scene and must not reappear on waking.
                    verbatim = wake["verbatim"]
                else:
                    pending_beat = result["beat"]

                pending_verbatim = verbatim + engine.apply_upkeep(state)
                advanced = True
                continue

    # -------------------------------------------------------------------
    # Workflow output: the final state of the adventure. Readable in the console.
    # -------------------------------------------------------------------
    return {
        "ending": state["ending"],
        "turns": state["turn"],
        "health": state["health"],
        "gold": state["gold"],
        "inventory": state["inventory"],
        "visited": state["visited"],
        "choices_made": state["taken"],
        "log": state["log"],
        "cheated_merchant": state["cheated_merchant"],
        "ledger_settled": state["ledger_settled"],
        "secret_vault_found": state["door_open"],
        "rests": state["rests"],
    }


def build_runtime() -> wf.WorkflowRuntime:
    """Register the workflow and every activity. Used by the worker and the CLI."""
    runtime = wf.WorkflowRuntime()
    runtime.register_workflow(dungeon_master, name="dungeon_master")
    for name, fn in activities.ALL_ACTIVITIES.items():
        runtime.register_activity(fn, name=name)
    return runtime

"""The terminal chat: the only thing the player actually runs.

DESIGN NOTES

* THE CLIENT IS A TERMINAL, NOT A GAME. It holds no game state at all. It reads the
  scene out of the workflow's custom status and writes commands back as external
  events. That is what makes "save and quit" trivially correct: there is nothing in
  this process worth saving, so stopping it loses nothing.

* ONE PROCESS, TWO ROLES. It hosts the workflow runtime (so the orchestrator and
  activities actually execute somewhere) and acts as the workflow client. Killing it
  stops the worker too — which is exactly the thing the mid-rest kill test needs to
  prove: the timer is held by Catalyst, not by this process.

* INSTANCE ID = THE SAVE SLOT. It defaults to `dm-<username>` so that simply
  starting the app again finds the same run. Nothing is written to disk: the id is
  *derived*, not stored.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
import time

# The Dapr worker logs connection churn at WARNING straight into the middle of the
# prose. A game is a UI; keep the channel clean and let real errors through.
for _noisy in ("durabletask-worker", "durabletask-client", "dapr.ext.workflow"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

import dapr.ext.workflow as wf
from dapr.ext.workflow import WorkflowStatus

from ..engine import ui
from . import config, history
from .workflow import PLAYER_COMMAND, RESUME_COMMAND, build_runtime

TERMINAL_STATES = (
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.TERMINATED,
)


def default_instance() -> str:
    if os.environ.get("DM_INSTANCE"):
        return os.environ["DM_INSTANCE"]
    try:
        who = getpass.getuser()
    except Exception:
        who = "player"
    return f"dm-{who}"


def _decode_status(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        val = json.loads(raw)
        if isinstance(val, str):          # Dapr may hand back a JSON-encoded string
            val = json.loads(val)
        return val if isinstance(val, dict) else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(scene: dict) -> None:
    # A redraw is a notice-only republish of the scene the player is already looking
    # at: no title bar, no prose, no verbatim. Just what changed, and the menu.
    if scene.get("redraw"):
        print()
        for line in scene.get("notice") or []:
            print(ui.wrap(ui.c(ui.NOTICE, line)))
        if scene.get("exits"):
            print()
            print(ui.c(ui.EXITS, "Exits: ") + ui.c(ui.EXITS, "   ".join(scene["exits"])))
        if scene.get("menu"):
            print()
            for i, label in enumerate(scene["menu"], 1):
                print(ui.c(ui.MENU, f"  {i}) {label}"))
        print()
        print(ui.c(ui.HUD, scene["hud"]))
        return

    print()
    print(ui.c(ui.TITLE, f"══ {scene['title']} " + "═" * max(0, ui.WIDTH - 4 - len(scene["title"]))))

    # VERBATIM, and first: the one line that says what the player is looking for.
    if scene.get("opening"):
        print()
        print(ui.wrap(ui.c(ui.RULE, scene["opening"])))

    if scene.get("recap"):
        print()
        print(ui.wrap(ui.c(ui.RECAP, scene["recap"])))

    nouns = scene.get("nouns") or []
    if scene.get("prose"):
        print()
        body = ui.highlight(scene["prose"], nouns)
        print(ui.wrap(ui.PROSE + body + ui.RESET if not ui.plain() else body))

    if scene.get("ambience"):
        print()
        print(ui.wrap(ui.c(ui.AMBIENCE, ui.highlight(scene["ambience"], nouns))))

    # VERBATIM BLOCK. Exactly as the engine wrote it; one colour code around each
    # whole line, never inside it.
    if scene.get("verbatim"):
        print()
        for line in scene["verbatim"]:
            colour = ui.DOOR if line.lstrip().startswith('"') else ui.RULE
            print(ui.wrap(ui.c(colour, line)))

    if scene.get("notice"):
        print()
        for line in scene["notice"]:
            print(ui.wrap(ui.c(ui.NOTICE, line)))

    if scene.get("ending"):
        return

    if scene.get("exits"):
        print()
        print(ui.c(ui.EXITS, "Exits: ") + ui.c(ui.EXITS, "   ".join(scene["exits"])))

    if scene.get("menu"):
        print()
        for i, label in enumerate(scene["menu"], 1):
            print(ui.c(ui.MENU, f"  {i}) {label}"))

    print()
    print(ui.c(ui.HUD, scene["hud"]))


def render_ending(scene: dict, instance_id: str, output: dict | None) -> None:
    colour = ui.WIN if scene.get("ending") == "vault" else ui.LOSE
    print()
    print(ui.c(colour, "═" * ui.WIDTH))
    print()
    history.render_timeline(instance_id, output)
    print()
    print(ui.c(ui.DIM, "This run is the save file. It is still there, and it is readable:"))
    print(ui.c(ui.LINK, config.console_url(instance_id)))
    print()


# ---------------------------------------------------------------------------
# Waiting
# ---------------------------------------------------------------------------

def wait_for_scene(client: wf.DaprWorkflowClient, instance_id: str, after_seq: int,
                   label: str, timeout: float = 180.0) -> tuple[dict | None, dict | None]:
    """Poll custom status until `seq` advances. Returns (scene, final_output)."""
    deadline = time.time() + timeout
    with ui.Spinner(label) as spin:
        while time.time() < deadline:
            state = client.get_workflow_state(instance_id)
            if state is None:
                time.sleep(0.4)
                continue
            scene = _decode_status(state.serialized_custom_status)
            if state.runtime_status in TERMINAL_STATES:
                out = None
                try:
                    out = json.loads(state.serialized_output) if state.serialized_output else None
                    if isinstance(out, str):
                        out = json.loads(out)
                except (ValueError, TypeError):
                    out = None
                return scene, out
            if scene and scene.get("seq", 0) > after_seq:
                return scene, None
            time.sleep(0.4)
    return None, None


def send(client: wf.DaprWorkflowClient, instance_id: str, command: str) -> None:
    client.raise_workflow_event(instance_id, PLAYER_COMMAND, data={"command": command})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BANNER = r"""
    ____                                     __  ___         __
   / __ \__  ______  ____ ____  ____  ____  /  |/  /__ ______/ /____  _____
  / / / / / / / __ \/ __ `/ _ \/ __ \/ __ \/ /|_/ / __ `/ ___/ __/ _ \/ ___/
 / /_/ / /_/ / / / / /_/ /  __/ /_/ / / / / /  / / /_/ (__  ) /_/  __/ /
/_____/\__,_/_/ /_/\__, /\___/\____/_/ /_/_/  /_/\__,_/____/\__/\___/_/
                  /____/      a durable text adventure
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dungeon-master", description=__doc__.splitlines()[0])
    ap.add_argument("--instance", default=None, help="save slot / workflow instance id")
    ap.add_argument("--new", action="store_true", help="discard the existing run and start over")
    ap.add_argument("--rest", type=int, default=None,
                    help="campfire rest length in seconds (default from DM_REST_SECONDS)")
    ap.add_argument("--worker", action="store_true", help="run as a worker only, no game")
    args = ap.parse_args(argv)

    if args.worker:
        from .worker import main as worker_main
        return worker_main()

    if not config.have_connection():
        print("No Catalyst connection found. Put DAPR_GRPC_ENDPOINT and DAPR_API_TOKEN "
              "in .env (see README).", file=sys.stderr)
        return 1

    instance_id = args.instance or default_instance()
    rest_seconds = args.rest if args.rest is not None else config.rest_seconds()

    runtime = build_runtime()
    runtime.start()
    client = wf.DaprWorkflowClient()

    try:
        return _play(client, instance_id, rest_seconds, args.new)
    finally:
        try:
            runtime.shutdown()
        except Exception:
            pass


def _next_free(client: wf.DaprWorkflowClient, instance_id: str) -> str:
    """The next unused `<slot>-N`, so the suggestion in a refusal is one you can use.

    Matches the numbering the device bridge uses, for the same reason: finished
    adventures stay put and keep their history.
    """
    import re

    base = re.sub(r"-\d+$", "", instance_id)
    for n in range(1, 500):
        if client.get_workflow_state(f"{base}-{n}") is None:
            return f"{base}-{n}"
    return f"{base}-new"


def _play(client: wf.DaprWorkflowClient, instance_id: str, rest_seconds: int, force_new: bool) -> int:
    from . import narrator

    print(ui.c(ui.TITLE, BANNER))
    print(ui.c(ui.DIM, f"  save slot: {instance_id}    narrator: {narrator.provider_label()}"))
    print(ui.c(ui.DIM, f"  {config.console_url(instance_id)}"))
    print(ui.rule_line())

    existing = client.get_workflow_state(instance_id)

    if existing is not None and force_new:
        print(ui.c(ui.NOTICE, "\nDiscarding the previous run and starting over."))
        try:
            if existing.runtime_status == WorkflowStatus.RUNNING:
                client.terminate_workflow(instance_id)
                time.sleep(2)
            client.purge_workflow(instance_id)
        except Exception as exc:
            print(ui.c(ui.NOTICE, f"(could not purge the old run: {exc})"))
        existing = None

    scene: dict | None = None
    output: dict | None = None

    if existing is not None and existing.runtime_status in TERMINAL_STATES:
        # REFUSE. Dapr lets a terminal instance id be reused, and reusing one means
        # purging it -- which in this game destroys the save file, because the save
        # file IS the history. A finished adventure holds the only record that the
        # vault was found. So an id that has been played is never silently recycled:
        # say what is there, and make the player choose.
        out = existing.serialized_output
        print()
        print(ui.c(ui.NOTICE, f"'{instance_id}' is a finished adventure "
                              f"({existing.runtime_status.name.lower()}). It is not a free slot."))
        if out:
            try:
                done = json.loads(out) or {}
                if done.get("secret_vault_found"):
                    print(ui.c(ui.RULE, "  That run found the secret vault. "
                                        "Purging it destroys the only record."))
            except (ValueError, TypeError):
                pass
        print(ui.c(ui.DIM, f"  read it:    {config.console_url(instance_id)}"))
        print(ui.c(ui.DIM, f"  play on:    --instance {_next_free(client, instance_id)}"))
        print(ui.c(ui.DIM, f"  branch it:  ./scripts/fork {instance_id}"))
        print(ui.c(ui.DIM,  "  overwrite:  --new   (purges it; this cannot be undone)"))
        return 1

    if existing is None:
        client.schedule_new_workflow(
            workflow="dungeon_master",
            input={"rest_seconds": rest_seconds},
            instance_id=instance_id,
        )
        scene, output = wait_for_scene(client, instance_id, 0, "opening the dungeon")
    else:
        # Resume. If the run is mid-rest we must NOT send anything: it is parked on a
        # durable timer and will wake on its own.
        current = _decode_status(existing.serialized_custom_status)
        if current and current.get("resting"):
            print()
            print(ui.c(ui.RULE, "You are still asleep at the campfire. The rest is a durable "
                                "workflow timer and it kept running while the app was closed."))
            print(ui.c(ui.RULE, f"It is due at {current.get('rest_due')}."))
            scene, output = wait_for_scene(
                client, instance_id, current.get("seq", 0),
                "still resting (durable timer, app restarted)",
                timeout=max(300.0, rest_seconds + 120),
            )
        else:
            send(client, instance_id, RESUME_COMMAND)
            scene, output = wait_for_scene(
                client, instance_id, (current or {}).get("seq", 0), "finding your place again")

    if scene is None:
        print(ui.c(ui.NOTICE, "The dungeon did not answer. Is a worker connected?"))
        return 1

    # ---------------- the loop ----------------
    while True:
        render(scene)

        if scene.get("ending"):
            if output is None:
                _, output = wait_for_scene(client, instance_id, scene["seq"], "sealing the record", timeout=60)
            render_ending(scene, instance_id, output)
            return 0

        if scene.get("parked"):
            print()
            print(ui.c(ui.DIM, f"Come back with:  uv run dungeon-master --instance {instance_id}"))
            print()
            return 0

        try:
            raw = input(ui.c(ui.BOLD, "\n> ") if not ui.plain() else "\n> ")
        except (EOFError, KeyboardInterrupt):
            print()
            print(ui.c(ui.DIM, "Left where you stand. The run is still open; start the app "
                               "again to come back to it."))
            return 0

        if not raw.strip():
            continue

        send(client, instance_id, raw)

        resting = False
        label = "the dungeon master is writing"
        if scene.get("resting"):
            resting = True
        timeout = 180.0

        next_scene, output = wait_for_scene(client, instance_id, scene["seq"], label, timeout)
        if next_scene is None and output is None:
            print(ui.c(ui.NOTICE, "The dungeon has gone quiet. Try again."))
            continue

        # Entering the rest: show the sleeping scene, then wait out the durable timer.
        if next_scene and next_scene.get("resting"):
            render(next_scene)
            print()
            print(ui.c(ui.DIM, "You can kill this app right now. The timer is Catalyst's, "
                               "not this process's."))
            after = next_scene["seq"]
            next_scene, output = wait_for_scene(
                client, instance_id, after,
                f"resting (durable workflow timer, due {next_scene.get('rest_due')})",
                timeout=max(300.0, (next_scene.get("rest_seconds") or 120) + 180),
            )
            if next_scene is None and output is None:
                print(ui.c(ui.NOTICE, "The rest is still running. Start the app again to rejoin it."))
                return 0

        if next_scene is None:
            # Workflow finished without one last status publish.
            return 0
        scene = next_scene


if __name__ == "__main__":
    raise SystemExit(main())

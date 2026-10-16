# dungeon-master

One text adventure, two durable shapes on [Diagrid Catalyst](https://catalyst.diagrid.io).

The same dungeon — same map, same talking door, same cursed item that doubles
as a compass, same secret — runs two ways over **one shared rules engine**:

| front end | the save file is | needs an inbound port |
|---|---|---|
| `dungeon_master.workflow` | one long-lived Dapr Workflow's own history | no |
| `dungeon_master.agent` | a Catalyst Agent's durable memory, one run per turn | yes, an app tunnel |

That contrast is the point. Everything that differs between them is durable
plumbing; the game itself is identical, because it is literally the same code.

## Quick start

```sh
make test                 # the whole rule set, no Catalyst, no key, ~1 second
```

The two front ends **cannot share one environment**: `diagrid[langgraph]` pulls
in `dapr-agents`, which pins `pydantic==2.10.5`, and the workflow front end
needs newer. They are declared as conflicting extras, so pick one:

```sh
uv sync --extra workflow      # or
uv sync --extra agent
```

`make test` and `make leakcheck` need neither — the engine has no dependencies
beyond the standard library.

**The workflow front end** — no tunnel, nothing listening, one terminal:

```sh
uv sync --extra workflow
make play-workflow
```

**The agent front end** — Catalyst calls into it, so it needs two terminals:

```sh
uv sync --extra agent
make serve-agent          # terminal 1: the agent, behind its tunnel
make play-agent           # terminal 2: play
```

You do **not** need an API key. With none set, the dungeon narrates itself in
written prose, interprets with the engine's own parser, and refuses what it
cannot place rather than improvising. With a key, a model writes each scene.

## Layout

```
dungeon_master/
  engine/      the game: map, rules, parser, leak check   <- ONE copy
  workflow/    front end 1: a Dapr Workflow
  agent/       front end 2: a Catalyst Agent over LangGraph
tests/         invariants + regressions, no Catalyst needed
prompts/       the build prompts, full and QR-sized
scripts/       refresh-connection, serve-agent, reset
```

Running the device edition at an event: see [BOOTH.md](BOOTH.md).

`engine/` has no clock, no network, no global RNG and no Catalyst in it. That
is what lets both front ends share it, what lets 400 randomised playthroughs
run in a second, and what means a rules fix lands once instead of twice.

## The rules the game holds to

Design constraints, enforced in code rather than left to care:

- **A choice you have taken disappears.** But a choice that is merely *useless
  right now* stays on the menu and says why — never hide a feature because the
  player does not happen to need it this second.
- **Exits name their destination once walked**, else "unexplored".
- **Interactable nouns are highlighted**, which is how you learn typed commands
  exist without being told.
- **The cursed item is the compass.** It tells you how far away what it wants
  is and which way to walk, and costs health every turn you carry it.
- **Any line stating a rule prints verbatim** and never reaches the narrator. A
  model handed "you have not got 5 gold" describes the purchase happening.
- **Repeated flavour varies**; a fixed per-turn line is wallpaper by turn 3.
- **A spinner while the model writes**, because silence reads as a hang.
- **The terminal shows nothing but the game** — SDK logs off unless asked.

## The secret

There is a vault behind the talking door. Finding it records a workflow step
named `secret_vault_found`, which stays in the run history long after the
terminal is closed.

Nothing a player can read explains how to open it. The *verb* is handed over on
purpose — an unguessable verb is a dead end rather than a secret — but no
string gives the door a motive, and the model is never told the condition, so
it cannot leak what it was never given.

```sh
make leakcheck
```

That enumerates every string the engine can print by **exercising** it, not by
grepping: all room prose and facts, ambience pools, every choice label, every
transition under 32 state combinations, room-entry lines, campfire events, the
tool refusals and the narrator's fallbacks — 5,810 strings — plus the model's
prompts, checked separately. It is verified to **fail on a deliberately planted
motive**, because a check that has never failed is not evidence.

## What is durable, concretely

**Workflow front end.** One orchestration holds the adventure and parks on
`wait_for_external_event` between moves, so killing the app leaves it sitting
on that line rather than rolled back to a checkpoint. The worker only dials
out. The campfire is a real `create_timer`.

**Agent front end.** The model interprets and narrates; the engine decides
outcomes with no model call at all. Each turn is its own durable run, and a
turn killed mid-node resumes rather than restarting. Two things a LangGraph
node cannot do get their own workflows: naming a step in history
(`secret_vault_found`) and creating a durable timer (`campfire_rest`).

## Forking a run (time travel)

Because the history is the save file, Catalyst can replay it up to any point
and carry on differently. `scripts/fork` lists where you could branch:

```
$ ./scripts/fork cyd-1-1
cyd-1-1 -- fork points, oldest first

  event  at        you typed               which ran
  -----  --------  ----------------------  --------------------
      3  01:35:47  south                   enter_room
      6  01:35:52  1                       take_cursed_item
      9  01:35:58  north                   enter_room
     12  01:36:23  north                   enter_room
     15  01:36:58  1                       secret_vault_found
     18  01:37:12  north                   enter_room
     21  01:40:09  1                       claim_durable_scroll
```

Then branch from one:

```
./scripts/fork cyd-1-1 18 the-other-ending
```

The new run comes up in the vault with the same health, the same gold and the
same choices already made -- and the scroll still unclaimed, so you can talk
to the dragon instead of robbing it. The original is untouched and stays
`completed`; both adventures now exist. The fork's own record says where it
came from (`rerunSourceWorkflowId`, `rerunFromEventId`).

A played instance id is never recycled. Pointing the CLI at a finished
adventure refuses rather than purging it, because purging it is what would
destroy the save file -- and says so loudly when that run found the vault:

```
'cyd-1-1' is a finished adventure (completed). It is not a free slot.
  That run found the secret vault. Purging it destroys the only record.
  read it:    https://catalyst.diagrid.io/workflows/dungeon-master/cyd-1-1?project=dungeon-master
  play on:    --instance cyd-1-5
  branch it:  ./scripts/fork cyd-1-1
  overwrite:  --new   (purges it; this cannot be undone)
```

Underneath the fork is one CLI call, which is worth seeing on its own:

```
diagrid workflow rerun --app-id dungeon-master --project dungeon-master \
  --instance-id cyd-1-1 --event-id 18 --new-workflow-id the-other-ending
```

Two things to know. A worker must be connected -- rerun, terminate and purge
all go through the app, not around it. And the `catalyst_rerun_workflow_run`
MCP tool returns `HTTP 500 unexpected end of JSON input` where the CLI works,
so the CLI is the path here (diagridio/catalyst-ai#65).

## Two screens, one adventure

The CLI and the device can play the same run at the same time. The instance id
is the whole handshake -- neither client owns the game, both only raise
`player_command` events and read the workflow's custom status, and the workflow
does not know who typed:

```sh
diagrid workflow list --app-id dungeon-master --project dungeon-master   # cyd-1-4 running
uv run dungeon-master-workflow --instance cyd-1-4
```

Both clients must act as the same App ID, which they do because both load
`.env.workflow`. A different identity cannot see the instance at all.

Each screen notices the other. The CLI polls the run while it waits at the
prompt and redraws under `(the other screen moved)`; the device asks the bridge
`GET /scene?slot=<slot>&since=<seq>` every three seconds, which answers
`{"nochange": true}` almost every time and a full screen when the run has
moved. Neither is pushed to, so a move lands on the other screen within a few
seconds rather than instantly.

That poll deliberately never *starts* an adventure, which the device's tap
handler does: a poll that created a run would wipe the ending screen and open a
fresh dungeon seconds after someone won.

It is a shared controller rather than two players: commands are consumed in
history order, so if both press `1` the first takes the choice and the second
is told that is not something it can do here. Attaching sends `__resume__`,
which prints the recap line and costs no turn.

## Known rough edges

- The agent front end needs an app tunnel, which the workflow one does not. Its
  CLI flag is `--app-id` (not `--id`), restarting a tunnel too soon fails with
  `local app connection not found`, and Catalyst health-checks with `GET /`
  which the adapter answers 404 — so the first command within a minute of
  startup can fail with `app is not in a healthy state`. It settles.
- `terminate` and `purge` need a connected worker, so the natural cleanup order
  is backwards. `make reset` starts one first.
- Both front ends default their save slot to `dm-<user>`. Same name, two
  different adventures — one in workflow history, one in agent memory.
- The agent front end is OpenAI-only; the workflow one takes either provider.
- The two front ends' dependencies conflict, so they need separate
  environments. `uv sync --extra workflow` / `--extra agent`, never both.

## Licence

Apache-2.0 — see [LICENSE](LICENSE). Apache rather than MIT because it carries
an explicit patent grant, and because Dapr itself is Apache-2.0, so this sits
in the same licence as the ecosystem it demonstrates.

## Issues this shook out

Filed upstream while building it:
[dapr/python-sdk#1259](https://github.com/dapr/python-sdk/issues/1259),
[diagridio/python-ai#429](https://github.com/diagridio/python-ai/issues/429),
[#430](https://github.com/diagridio/python-ai/issues/430),
[#431](https://github.com/diagridio/python-ai/issues/431),
[diagridio/catalyst-ai#64](https://github.com/diagridio/catalyst-ai/issues/64),
[#65](https://github.com/diagridio/catalyst-ai/issues/65).

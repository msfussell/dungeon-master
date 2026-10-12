# Project state

Written 2026-10-12. This is a handover note: enough to pick the work up cold,
in a new session, with no memory of how any of it got here. The README is the
document for someone who wants to *play* it; this one is for someone who wants
to *change* it.

---

## 1. What this is

A durable text adventure whose save file is a Dapr Workflow history on Diagrid
Catalyst. There is no database and no file on disk: the workflow's history *is*
the save, because the game state is a deterministic replay of the ordered
`player_command` events in it.

One engine, three front ends:

| Front end | Run it with | Tunnel |
| --- | --- | --- |
| Terminal, workflow | `uv run dungeon-master-workflow` | no |
| Terminal, agent (LangGraph) | `make serve-agent` then `make play-agent` | yes |
| ESP32 Cheap Yellow Display | bridge + `firmware/cyd` | no (the board calls the bridge over wifi) |

- Code: `/Users/markfussell/dev/src/catalyst/dungeon-master`
- GitHub: <https://github.com/msfussell/dungeon-master> — **public** since 2026-10-12
- Licence: Apache-2.0, "Copyright 2026 Mark Fussell" (settled 2026-10-12)

## 2. Run it

```sh
cd /Users/markfussell/dev/src/catalyst/dungeon-master

make test          # engine rules, 400 replay walks. No Catalyst, no key, ~1s
make leakcheck     # proves nothing readable gives the secret away

uv sync --extra workflow        # the two front ends CANNOT share a venv (see 5.20)
make play-workflow             # the terminal game
uv run dungeon-master-workflow --instance <id>    # join a specific adventure

uv run --extra workflow python -m dungeon_master.bridge.server   # the device bridge
./scripts/fork <instance>      # list a run's branch points; add an event id to fork
./scripts/reset selftest-      # purge runs by prefix (starts a worker first)
./scripts/refresh-connection   # prints how to regenerate .env.workflow / .env.agent
```

Device firmware (board on `/dev/cu.usbserial-210`, a CH340):

```sh
cd firmware/cyd && pio run --target upload --upload-port /dev/cu.usbserial-210
pio device monitor -p /dev/cu.usbserial-210 -b 115200     # taps log as [tap]
```

**Which changes need which rebuild.** Scene text, buttons, both HUD lines, the
map and all layout are composed *by the bridge*: restart it, no reflash. Art,
touch, calibration, wifi and the poll interval are firmware: reflash over USB.

## 3. Live state, 2026-10-12

- **Bridge** running on port 8080, pids 28235/28237. It hosts the HTTP server
  **and** the workflow worker, so killing it takes the worker with it, and every
  adventure loses its ability to start, terminate, purge or rerun until it is back.
- **Device** is slot `cyd-1`, currently on adventure `cyd-1-9`, and polls from
  its own address on the LAN — 14,104 polls in the log, so the background poll
  works in the field and not only in tests.
- **`mark-play`** — running, a terminal-only adventure, parked mid-game.
- **`cyd-1-1` … `cyd-1-8`** — completed, and **every one of them found the secret
  vault**. `cyd-1-4` was terminated deliberately to let the device move on.
- `new-fork` — a leftover from testing `workflow rerun`. Safe to purge.

## 4. Where everything is

```
dungeon_master/
  __init__.py        loads .env, .env.workflow, .env.agent BEFORE dapr (see 5.2)
  engine/            PURE. No clock, network, RNG or Catalyst. The rules live here.
    world.py         9 rooms on a 3x4 coord grid, prose, facts, verbatim lines
    engine.py        parse, move, apply_choice, upkeep, rest refusals, hud
    ui.py            terminal rendering, colour, spinner
    leakcheck.py     enumerates every reachable string and proves the secret is safe
  workflow/          front end 1: the orchestrator IS the save file
    workflow.py      the whole game loop; wait_for_external_event + create_timer
    activities.py    narrate_scene, enter_room, secret_vault_found, campfire_event...
    narrator.py      optional LLM prose; written prose is the floor, not a fallback
    cli.py           the terminal client: prompt_or_watch, render, refusals
    history.py       reads run history via the diagrid CLI for the end-of-run timeline
    worker.py        worker only, no game
  agent/             front end 2: LangGraph through diagrid[langgraph]
    graph.py         load -> interpret -> act -> narrate -> save
    aux_workflows.py the two things a graph node cannot do: a named step, a timer
  bridge/            front end 3: HTTP for the board + a hosted worker
    server.py        /ping, /scene[&since=], /command; slot->instance; fog-of-war map
    layout.py        MEASURED constants for 240x320. Do not guess these.
firmware/cyd/        PlatformIO, ESP32-2432S028R
  src/main.cpp       self-test, calibration, drawScene/drawMap, touch, the 3s poll
  src/touch.h        bit-banged XPT2046 (the registry library does not work, see 5.24)
  src/art.h          dungeon entrance on boot, dragon in the vault
  src/dragon_sprite.h  72x65, 585 bytes, converted from dragon1.png
  include/secrets.h  GITIGNORED: wifi, bridge host/port, GAME_SLOT
tools/fork.py        fork point lister + rerun wrapper
tools/png2sprite.py  PNG -> 1-bit sprite, auto-cropped to ink, ASCII preview
prompts/             the two shareable prompts, and both QR-sized versions
issue-drafts/        the six upstream issues as filed
```

## 5. Assumptions the code makes

Breaking any of these looks like a platform bug and is not one.

**Identity and connection**

1. Every client acts as App ID `dungeon-master`, because they all load
   `.env.workflow`. A different identity **cannot see the instance at all** —
   this caused the agent front end's rest-polling 404s.
2. `dungeon_master/__init__.py` loads the env files **before** dapr is imported.
   Dapr snapshots `DAPR_*` at import time (dapr/python-sdk#1259). Move that
   import and the connection breaks in a way that looks like bad credentials.
3. An `https://` gRPC endpoint is rewritten to `host:port?tls=true` there too.
4. `.env` holds `DM_PROJECT`, `DM_REST_SECONDS`, `OPENAI_API_KEY` and **no
   `DAPR_*`** — `diagrid dev run` injects those and must not be overridden.

**Runs, slots, history**

5. The instance id **is** the save file. Nothing else is persisted.
6. A terminal instance id is never reused. Dapr allows it; this game treats it
   as data loss, in both the CLI (it refuses) and the bridge (it numbers).
7. A slot is not an instance. The device's slot `cyd-1` resolves to `cyd-1-N`;
   a bare running instance named exactly the slot is adopted, for boards that
   were mid-game before numbering existed.
8. The device's slot derives from its eFuse MAC unless `GAME_SLOT` is set in
   `firmware/cyd/include/secrets.h`. So four boards take four adventures from
   one build.
9. **A worker must be connected** for start, terminate, purge and rerun.
10. `purge` needs the run finished — terminate first. `purge`/`terminate` take
    `--instance-id <id>`; `get` takes the id positionally.
11. `diagrid workflow get` returns history **newest first**, and `-o json`
    writes an empty file, so `tools/fork.py` parses YAML and reverses it.
12. A player decision appears in history as `EventRaised`/`player_command` with
    `input: {"command": "..."}`; the adjacent `TaskScheduled` carries the
    `eventId` to fork from.
13. `catalyst_rerun_workflow_run` and `catalyst_terminate_workflow_run` over MCP
    return `HTTP 500 unexpected end of JSON input` where the CLI works
    (diagridio/catalyst-ai#65). Use the CLI for both.
14. At data-sharing level `metadata`, `input`, `output` and `customStatus` are
    **withheld, not empty**, over the MCP tools. Never report that as "no output".

**Determinism**

15. The orchestrator has no clock, no RNG, no I/O and no env reads. Time is
    `ctx.current_utc_datetime`; randomness is rolled in an activity and only the
    result is applied.
16. `rest_seconds` arrives in the workflow **input**, so it is pinned in history
    and cannot drift when `.env` changes mid-rest.
17. `seq` counts publishes, so it is a pure function of the command sequence and
    stable across replay. Both clients use it to decide when to redraw, and the
    device sends it as `&since=`.
18. Overlays (map, "more") carry a **negative** `seq`. The device uses that to
    suppress polling, or a poll would replace the map three seconds after it opened.

**The secret, and the narrator**

19. `verbatim` lines never reach `narrator.py`. A model shown a rule explains it
    away and then invents the event it thinks the rule implies.
20. The door's reason is in no prompt, and the prompt forbids speculating about
    motives. `make leakcheck` proves it over every reachable string.
21. The game is fully playable with **no API key**. Written prose is the
    baseline; any provider error falls through to it silently.
22. The map is fog of war and omits the vault entirely until the door is open.

**Environments and the device**

23. The two front ends cannot share a venv: `diagrid[langgraph]` pins
    `pydantic==2.10.5` and the workflow front end needs newer. Declared as
    conflicting extras in `pyproject.toml`; `uv sync --extra workflow|agent`.
24. The engine has no dependencies beyond the standard library, so `make test`
    and `make leakcheck` need neither Catalyst nor a key.
25. `bridge/layout.py` constants are **measured**: 240x320, 34 columns at
    ~6.3px/char, HUD under ~34 characters or it is cut off.
26. The touch driver is bit-banged in `firmware/cyd/src/touch.h`. The registry's
    `XPT2046_Touchscreen` is a 2019 alpha with no `begin(SPIClass&)`.
    Calibration: `TS_MINX=1932, TS_MAXX=209, TS_MINY=101, TS_MAXY=1886,
    TS_SWAP=false`.
27. `HTTPClient::setTimeout` takes a `uint16_t`, so 65.5s is the ceiling — a
    campfire rest longer than that cannot be waited out in one POST.
28. The board is **2.4GHz only**. The Mac's LAN address goes in `secrets.h` as
    `BRIDGE_HOST`; if the Mac's IP changes, the board needs a reflash.

## 6. Two screens, one adventure

Both clients only raise `player_command` events and read custom status, so any
number of them can hold one run. The instance id is the whole handshake, and
both must act as the same App ID.

- The **CLI** polls while idle at the prompt (`prompt_or_watch`) and redraws
  under `(the other screen moved)`.
- The **device** polls `GET /scene?slot=<slot>&since=<seq>` every 3s. The bridge
  answers `{"nochange": true}` almost always, a full screen when the run moved.
- That poll never *starts* an adventure (`start_new_if_finished=False`), or it
  would wipe the ending screen and open a fresh dungeon seconds after a win. A
  tap is allowed to start one; a poll is not.
- The run id shows in the CLI prompt (`cyd-1-9 > `) and in the HUD of the
  device's map screen (tap the title bar). Same string means same adventure.
- It is a shared controller, not two players: commands are consumed in history
  order, so if both press `1` the second is told that is not something it can do.

## 7. Catalyst

- Project `dungeon-master`; App `dungeon-master`; Agent `dungeon-master-agent`
  (port 5001, needs `diagrid dev run`, and the flag is `--app-id`, not `--id`).
- Console: `https://catalyst.diagrid.io/workflows/dungeon-master/<runId>?project=dungeon-master`.
  Name goes in `?project=`, numeric uid in `?projectId=` — the wrong one
  silently falls back to the default project.
- Right after `serve-agent` starts, the first command can fail with "app is not
  in a healthy state" because Catalyst health-checks `GET /` and the adapter
  404s it. It settles by itself.

## 8. Upstream issues this shook out

[dapr/python-sdk#1259](https://github.com/dapr/python-sdk/issues/1259),
[diagridio/python-ai#429](https://github.com/diagridio/python-ai/issues/429)
(with a tested patch),
[#430](https://github.com/diagridio/python-ai/issues/430),
[#431](https://github.com/diagridio/python-ai/issues/431),
[diagridio/catalyst-ai#64](https://github.com/diagridio/catalyst-ai/issues/64),
[#65](https://github.com/diagridio/catalyst-ai/issues/65).
Full drafts in `issue-drafts/`.

## 9. Next steps

1. **Back the device poll off when idle.** 14,104 polls are 14,104
   `get_workflow_state` calls against Catalyst, and four boards would be four
   times that. Suggested: 3s for a minute after any activity, then 10-15s.
   `POLL_MS` in `firmware/cyd/src/main.cpp` (firmware change, so a reflash).
2. **Purge the leftovers** — `new-fork`, and `mark-play` when it is finished
   with. Keep every `cyd-1-N`: they all found the vault.
3. **Flash the other three boards.** Slots derive from the chip, so no per-board
   build is needed. Untested on more than one board.
4. **Split the worker out of the bridge**, or accept that restarting the bridge
   drops the worker for every adventure. Fine on a desk, wrong at a booth.
5. **`POST /attach?slot=<slot>&instance=<id>`** on the bridge, so a board can
   join an arbitrarily-named run. Today a shared run must be named `cyd-1-N` for
   the device to find it, which is why `mark-play` could not be joined.
6. **Pub/sub between the boards** — one adventure on four screens, or four that
   can see each other. The project has one managed pub/sub; separate by topic.
7. **Workflow history signing.** `enableWorkflowHistorySigning` is creation-only,
   so it needs a new project — worth it if "show this run to the booth" should
   be tamper-evident.

## 10. The repo is public

Audited before it went public, 2026-10-12: no credential has ever been
committed, in any commit. `.env*`, `firmware/cyd/include/secrets.h` and
`firmware/cyd/.pio/` are ignored — that last one matters, because a built
`firmware.bin` carries the wifi password in plaintext. `.env.example` and
`secrets.h.example` hold placeholders only.

Two things follow from being public. The game's solution is now readable in
`engine/world.py`, so `make leakcheck` protects the *playing* experience and not
the secret itself — worth remembering before the booth hands out a reward for
finding the vault. And history is public too, so a secret committed by accident
has to be treated as disclosed, not merely reverted.

## 11. How to work on this

- **Report what you actually ran, not what you expect to work.** This was the
  standing instruction from the start and it caught several things that "should"
  have worked: the MCP rerun 500, `-o json` returning empty, purge refusing a
  live run. Prove durability with timestamps, not with assertions.
- Spike an unknown before porting code onto it.
- Keep answers short. Give the command, not the tour.
- `make test` and `make leakcheck` are fast and need nothing. Run them after any
  engine change.
- Keep this file current. It is the handoff.

# Project state

Written 2026-10-11. A handover note: where the project stands, what the code
assumes, and what is worth doing next. The README is the user-facing document;
this one is for whoever picks the work up.

## What this is

A durable text adventure whose save file is a Dapr Workflow history on Diagrid
Catalyst, playable three ways from one engine:

| Front end | Entry point | Needs a tunnel |
| --- | --- | --- |
| Terminal (workflow) | `uv run dungeon-master-workflow` | no |
| Terminal (agent, LangGraph) | `uv run dungeon-master-agent` | yes |
| ESP32 Cheap Yellow Display | `dungeon_master.bridge.server` + `firmware/cyd` | no (the board calls the bridge over wifi) |

- Repo: <https://github.com/msfussell/dungeon-master> — **still private**, 18 commits, 61 files.
- Catalyst: project `dungeon-master`, App `dungeon-master`, Agent `dungeon-master-agent`.
- Licence: Apache-2.0, "Copyright 2026 Mark Fussell".

## Live right now

- Bridge running locally on port 8080 (pids 14896/14898). It hosts **both** the
  HTTP server for the device and the workflow worker, so killing it takes the
  worker with it.
- `cyd-1-5` — running, the device's current adventure, shared with a terminal.
- `mark-play` — running, a terminal-only adventure, parked where it was left.
- `new-fork` — running, a leftover from testing `workflow rerun`; safe to purge.
- `cyd-1-1` — completed, **found the secret vault**. The one history worth keeping.
- `cyd-1-2`, `cyd-1-3` completed; `cyd-1-4` terminated to let the device move to `cyd-1-5`.

## Done recently

- `scripts/fork` — lists a run's decision points (each typed command paired with
  the event id to branch from) and forks one with `diagrid workflow rerun`.
- The CLI no longer recycles a played instance id. It refuses, names what is
  there, warns when that run found the vault, and offers: read it, play on at the
  next free id, branch it, or `--new` to overwrite deliberately.
- `prompt_or_watch` — the CLI polls the run while idle at the prompt instead of
  blocking in `input()`, so a move made on the device redraws the terminal under
  `(the other screen moved)`.
- The run id is visible on both screens: in the CLI prompt (`cyd-1-5 > `) and in
  the HUD of the device's map screen (tap the title bar).

## Assumptions the code makes

Breaking any of these looks like a platform bug and is not one.

**Identity and connection**

1. Every client acts as App ID `dungeon-master`, because they all load
   `.env.workflow`. A different identity **cannot see the instance at all** —
   this is what caused the agent front end's rest-polling 404s.
2. `dungeon_master/__init__.py` loads `.env`, `.env.workflow`, `.env.agent`
   with `override=False` **before** dapr is imported. Dapr snapshots `DAPR_*` at
   import time (dapr/python-sdk#1259). Moving that import breaks the connection.
3. An `https://` gRPC endpoint is rewritten to `host:port?tls=true` in the same file.

**Runs, slots and history**

4. The instance id **is** the save file. Nothing else is persisted anywhere.
5. A terminal instance id is never reused. Dapr allows it; this game treats it as
   data loss, in both the CLI and the bridge.
6. A slot is not an instance. The device's slot (`cyd-1`) resolves to numbered
   adventures `cyd-1-N`; a bare running instance named exactly the slot is adopted
   for boards that were mid-game before numbering existed.
7. The device's slot comes from its eFuse MAC unless `GAME_SLOT` is set in
   `firmware/cyd/include/secrets.h`. That file is gitignored, as are all `.env*`.
8. **A worker must be connected** for start, terminate, purge and rerun. They go
   through the app, not around it.
9. `purge` needs the run finished — terminate first. `purge`/`terminate` take
   `--instance-id <id>`; `get` takes the id positionally.
10. `diagrid workflow get` returns history **newest first**, and `-o json`
    produces an empty file, so `scripts/fork` parses YAML and reverses it.
11. `catalyst_rerun_workflow_run` and `catalyst_terminate_workflow_run` over MCP
    return `HTTP 500 unexpected end of JSON input` where the CLI works
    (diagridio/catalyst-ai#65). Use the CLI for both.
12. At data-sharing level `metadata`, `input`, `output` and `customStatus` are
    **withheld, not empty**, over the MCP tools.

**Determinism**

13. The orchestrator has no clock, no RNG, no I/O and no env reads. Time comes
    from `ctx.current_utc_datetime`; randomness is rolled in an activity and only
    its result is applied.
14. `rest_seconds` arrives in the workflow **input**, so it is pinned in history
    and cannot drift when `.env` changes mid-rest.
15. `seq` counts publishes, so it is a pure function of the command sequence and
    is stable across replay. Both clients use it to decide when to redraw.

**The secret, and the narrator**

16. `verbatim` lines never reach `narrator.py`. A model shown a rule explains it
    away and then invents the event it thinks the rule implies.
17. The door's reason is not in any prompt, and the prompt forbids speculating
    about motives. `make leakcheck` proves nothing readable gives it away.
18. The game is fully playable with **no API key**. Written prose is the baseline,
    not a degraded mode; any provider error falls through silently.
19. The map is fog of war. It never shows the vault before the door is open, or
    the layout would replace both exploration and the lodestone.

**Environments and the device**

20. The two front ends cannot share one virtualenv — `diagrid[langgraph]` pins
    `pydantic==2.10.5`. They are declared as conflicting extras; `uv sync
    --extra workflow` or `--extra agent`.
21. The engine has no dependencies beyond the standard library, so `make test`
    and `make leakcheck` need neither Catalyst nor a key.
22. Screen layout constants in `bridge/layout.py` are **measured**, not guessed:
    240x320, 34 columns at ~6.3px per character, and the HUD must stay under ~34
    characters or it is cut off.
23. Scene text, buttons and both HUD lines are composed **by the bridge**, so most
    presentation changes need a bridge restart and no reflash. Art, calibration
    and touch handling are in the firmware and do need USB.
24. The touch driver is bit-banged in `firmware/cyd/src/touch.h`. The registry's
    `XPT2046_Touchscreen` is a 2019 alpha with no `begin(SPIClass&)` and does not
    work here. Calibration is `TS_MINX=1932, TS_MAXX=209, TS_MINY=101,
    TS_MAXY=1886, TS_SWAP=false`.

## Next steps

Roughly in the order I would do them.

1. **Decide the licence holder** — "Mark Fussell" or "Diagrid Inc." — before the
   repo goes public. One line in `LICENSE`.
2. **Make the repo public**: `gh repo edit msfussell/dungeon-master --visibility public`.
   Check `.gitignore` still covers `.env*` and `firmware/cyd/include/secrets.h`
   first; the history has never held a secret and should stay that way.
3. **Purge the test leftovers** — `new-fork`, and `mark-play` once it is finished
   with. Keep `cyd-1-1`.
4. **Flash the other three boards.** Slots derive from the chip, so they will take
   their own adventures with no per-board build. This is untested on more than one
   board.
5. **Run the bridge as its own process from the worker**, or accept that restarting
   the bridge drops the worker for everyone. Fine for a booth, wrong for a demo
   where someone else is mid-game.
6. **`POST /attach?slot=<slot>&instance=<id>`** on the bridge, so a board can join
   an arbitrarily-named run without a reflash. Today a shared run has to be named
   `cyd-1-N` for the device to find it.
7. **Pub/sub between the boards** — one adventure visible on four screens, or four
   adventures that can see each other. The project has one managed pub/sub;
   separate the boards by topic.
8. **Workflow history signing.** `enableWorkflowHistorySigning` is creation-only,
   so this needs a new project — worth it if the booth claim ("show this run")
   should be tamper-evident.
9. **Add rerun's 500 to diagridio/catalyst-ai#65**, which currently only covers
   terminate.

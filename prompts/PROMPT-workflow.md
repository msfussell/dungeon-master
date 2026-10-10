# dungeon-master — build prompt (v2)

A reusable version of the original brief, rewritten after building it three
times. Fill in the four `«...»` placeholders and paste the whole **Prompt**
section. The notes at the end record why particular lines are worded the way
they are — they are for you, not for the model.

---

## Prompt

Using the Catalyst MCP tools and your shell, build a durable text adventure
agent in Python called "dungeon-master" in project `«PROJECT»`. If that project
doesn't exist, ask me which to use — don't invent one.

### 0. Context and ground rules

- **Previous attempts:** «ONE OF: There are no previous attempts. / There is a
  previous attempt in `«PATH»`. **Do not read it** — build from this spec alone;
  if a design question comes up, decide it yourself and justify it in a comment.
  / Build on the existing `«PATH»`; it already encodes the playability rules
  below, so preserve that code rather than reimplementing it.»
- **This is a 3-minute conference booth demo, running on untrusted wifi.**
  Optimise for that: a short path to the payoff, a default campfire rest
  measured in seconds not minutes, an obvious "kill the app" moment, and no
  dependence on the network being good.
- **LLM key:** «ONE OF: Only OpenAI is set up; the key is in `«LOCATION»`. Write
  the OpenAI path only. / Both keys are in `«LOCATION»`. / I have no key —
  write your own prose and don't call a model at all.» If you write a provider
  path you cannot exercise, say so plainly in your report rather than implying
  it works.
- **The terminal shows nothing but the game.** SDK, gRPC and HTTP logs must be
  off by default, with a `--verbose` flag to bring them back. A log line in the
  middle of a sentence shows the player a bug, not a dungeon.
- **Secrets:** get the connection with `catalyst_get_connection`, write it to a
  gitignored `.env` (write `.gitignore` first, `chmod 600` the `.env`), and
  never print a token or key back to me.

### 1. The game

The game is a Dapr Workflow on Catalyst: **the workflow's own history IS the
save file.** No database, no save file on disk. A map of rooms I move through
with north/south/east/west, plus up to 3 choices per scene. Track health, gold,
inventory and every choice I make. Include a talking door, a cursed item, and a
merchant who remembers if I cheated him.

### 2. Playability rules

These are hard-won. Follow them; don't rediscover them.

- **A choice I've already taken disappears.** Never make me pick it again just
  to be told I already did it. But a choice that is merely *useless right now*
  stays on the menu and tells me why — never silently hide a feature because I
  don't happen to need it this second.
- **Exits name their destination once I've walked them**; unvisited ones say
  "unexplored".
- **Highlight the interactable nouns in the prose**, so I learn that typed
  commands exist without being told.
- **The cursed item doubles as a compass:** it tells me how close I am to what
  it wants and which way to walk. Carrying it costs health, so it's a trade.
- **Any line that states a rule or an instruction prints VERBATIM.** Never let
  the narrator re-describe it — it will paraphrase the instruction out of
  existence and invent events that didn't happen. Enforce this structurally, so
  a rule line added later is covered by default rather than by someone
  remembering to flag it.
- **Vary repeated flavour text.** A fixed per-turn line is wallpaper by turn 3.
- **Spinner while the model writes.** Silence reads as a hang.
- **Open with one line telling me what I'm looking for.**

If following one of these makes the game worse in play, don't quietly drop it —
flag it and tell me what you saw.

### 3. The secret

The talking door hides a vault. It opens when I offer it the cursed item. Put
that offer on the menu whenever I'm carrying the item **and standing where it
can be used** — don't make me guess the verb — but never explain anywhere why
the door wants it. When it opens: record a workflow step named
`secret_vault_found`, describe a dragon guarding a glowing durable scroll, and
tell me "Show this run to the Diagrid booth to claim your reward."

### 4. Durability

- **A durable campfire rest**, ending in a random event that wakes me.
  Duration configurable **in seconds**, default 120. It must be a workflow
  timer, not a sleep.
- **"save and quit" stops the app.** Starting it again resumes exactly where I
  left off, recapping the moment in one dramatic sentence.
- **At the ending, show my adventure as a timeline built by reading the actual
  workflow run history** (not reconstructed from in-process state — if the SDK
  can't give you history, use the Catalyst API or CLI and say which). Plus the
  console link:
  `https://catalyst.diagrid.io/workflows/dungeon-master/<instance-id>?project=<project>`

### 5. Definition of done

Before handing it back:

- **Play it yourself, end to end, including the secret** — and fix what playing
  reveals. Use instance IDs starting with `selftest-` for every test run.
- **Prove the named step is in the run history** — quote the history entry.
- **Prove the timer survives killing the app mid-rest** — give me timestamps:
  when the rest began, when its timer was due, when you killed the app, that
  nothing was left running, when you restarted, when it woke.
- **Prove no player-visible string explains why the door opens.** Write the
  check as a script, and **show me it fails on a deliberately planted leak** —
  a check that has never failed is not evidence.
- **Prove it is still playable with no key at all.**
- **Purge all `selftest-` runs** and confirm the project is clean.
- **Report what you actually ran, not what you expect to work.** Tell me what
  you could not test and what you left broken.

---

## Notes to self — why these lines exist

| Line | What went wrong without it |
|---|---|
| "Do not read it / Build on it" | "Hard-won — don't rediscover" was read as *reuse the code those lessons came from*. Cost a full clean-room rebuild. State the reuse policy outright. |
| "3-minute booth demo, untrusted wifi" | The reward line implies a booth but never says it. Without it, a 2-minute default rest and a long map are defensible; with it, they aren't. |
| "Only OpenAI is set up; the key is in X" | Neither key was in an env var — one was in another project's `.env`. The stated branches didn't cover reality, and an untestable Anthropic path got written twice. |
| "useless right now stays on the menu" | Taken literally, "already-taken choices disappear" generalised to "no inert choices", which hid the rest option at full health — the durable-timer showpiece became invisible. |
| "configurable in seconds, default 120" | "2 minutes, configurable" implied fractional minutes and shipped an `int("0.3")` crash. |
| "Enforce this structurally" | Verbatim discipline applied by hand covered one line and missed eight, including every "you can't afford that" message — exactly where a narrator invents a purchase that never happened. |
| "reading the actual run history" | Ambiguous between parsing history and reconstructing from state. The two answers have different dependencies; the choice shouldn't be left to chance. |
| "terminal shows nothing but the game" | First playthrough had gRPC INFO lines cutting through the prose and the spinner. |
| "show me it fails on a planted leak" | Turned a `PASS` from a claim into evidence. Both builds' checkers had false positives that only surfaced under a negative control. |
| "Play it yourself" (kept verbatim) | Highest-value line in the original. Found the log spam, the crash, and a notice claiming I was "asleep until" a time already past. |
| "`selftest-` prefix + purge" (kept verbatim) | Made cleanup auditable, and made a stray third-party run easy to spot and leave alone. |
| "Report what you actually ran" (kept verbatim) | Shaped every report, including re-verifying a subagent instead of relaying it. |

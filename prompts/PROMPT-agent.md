# dungeon-master — build prompt, AGENT version

The sibling of `dungeon-master-PROMPT.md`. That one builds the adventure as a
hand-written Dapr Workflow; this one builds it as a Catalyst **`Agent`**. Same
game, same secret, same booth line — a different durable shape underneath.

Fill in the four `«...»` placeholders and paste the whole **Prompt** section.
The notes at the end record why particular lines are worded the way they are;
every one of them is a mistake that was made and cost time. They are for you,
not for the model.

---

## Prompt

Using the Catalyst MCP tools and your shell, build a durable text adventure
called "dungeon-master" in Python, as a **Durable Agent on Diagrid Catalyst**,
in project `«PROJECT»`. If that project doesn't exist, ask me which to use —
don't invent one.

### 0. Context and ground rules

- **Previous attempts:** «ONE OF: There are no previous attempts. / There is a
  previous attempt in `«PATH»`. **Do not read it** — build from this spec alone.
  / Build on `«PATH»`; reuse its deterministic engine and map, and replace only
  the durable plumbing.»
- **This is a 3-minute booth demo on untrusted wifi.** Be honest with me about
  the cost: an Agent needs an inbound endpoint, so this version has a tunnel the
  workflow version does not. If that makes it the wrong demo, say so.
- **LLM key:** «ONE OF: Only OpenAI is set up; the key is in `«LOCATION»`. /
  Both keys are in `«LOCATION»`. / I have no key.» If you write a provider path
  you cannot exercise, say so plainly rather than implying it works.
- **Spike before you port.** Prove the risky platform facts with a throwaway
  agent that has no game in it — that it registers and serves, that a turn
  killed mid-node resumes, that a step can be named, that a durable timer is
  reachable. Only then write the game. If a mechanism doesn't work, I would
  rather know in ten minutes than after a thousand lines.
- **Secrets:** get the connection with `catalyst_get_connection`, write
  gitignored env files (`.gitignore` first, `chmod 600`), never print a token.

### 1. The shape

A Catalyst `Agent` is a resource that fronts an agent **my app runs** —
Catalyst does not host the loop. Use the `diagrid[...]` adapter so the agent
runs as a durable workflow, and front it with an `Agent` resource whose
endpoint Catalyst can reach. On a laptop that means an app tunnel.

**The split is the whole design.** The model may be wrong about what I *meant*.
It is never allowed to be wrong about what *happened*.

| step | may the model act? | what it does |
|---|---|---|
| interpret | yes | map my free text to exactly one listed action |
| **act** | **no** | the deterministic engine decides outcomes. No model call at all |
| narrate | yes | write prose from facts it is handed |

Every result carries two separate fields: `beat`, prose the narrator may
rewrite, and `verbatim`, lines printed exactly and never shown to the model.

### 2. The game

Rooms I move through with north/south/east/west, plus up to 3 choices per
scene. Track health, gold, inventory and every choice I make. Include a talking
door, a cursed item, and a merchant who remembers if I cheated him.

### 3. Playability rules

Hard-won. Follow them; don't rediscover them.

- **A choice I've already taken disappears.** Never make me pick it again to be
  told I already did. But a choice that is merely *useless right now* stays on
  the menu and says why — never hide a feature because I don't happen to need
  it this second.
- **Exits name their destination once I've walked them**; unvisited say
  "unexplored".
- **Highlight the interactable nouns**, so I learn typed commands exist without
  being told.
- **The cursed item doubles as a compass:** how close I am to what it wants,
  and which way to walk. Carrying it costs health, so it's a trade.
- **Any line stating a rule or instruction prints VERBATIM**, and never reaches
  the model. Enforce it structurally, so a rule line added later is covered by
  default rather than by someone remembering.
- **Vary repeated flavour text.** A fixed per-turn line is wallpaper by turn 3.
- **Spinner while the model writes.** Silence reads as a hang.
- **The terminal shows nothing but the game.** SDK, gRPC and HTTP logs off by
  default, with a flag to restore them.
- **Open with one line telling me what I'm looking for.**
- **Fully playable with no key at all:** interpret with the engine's own parser,
  narrate with written prose, and refuse what you cannot place rather than
  letting the model improvise.

If following one of these makes the game worse in play, flag it — don't quietly
drop it.

### 4. The secret

The talking door hides a vault. It opens when I offer it the cursed item. Put
that offer on the menu whenever I'm carrying the item **and standing where it
can be used** — don't make me guess the verb — but never explain anywhere why
the door wants it, and **never tell the model the condition**: it cannot leak
what it was not given. When it opens: record a step named `secret_vault_found`,
describe a dragon guarding a glowing durable scroll, and tell me "Show this run
to the Diagrid booth to claim your reward."

### 5. Durability — and three things the agent framework will not do for you

**A step named `secret_vault_found`.** Expect every node to execute through one
generic activity, with the node's own name surviving only inside a payload that
is withheld at the default data-sharing level. If that is what you find, a node
of that name does **not** put it in the history — give the moment its own
one-step **workflow**, which appears under its own function name and is
readable by anyone without raising my organization's data-sharing level.

**A durable campfire rest**, ending in a random event that wakes me,
configurable **in seconds**, default 120. A node runs *inside* an activity and
so cannot create a timer: make the rest its own **workflow** that a node starts
and the client waits on. Register these alongside the agent on its own workflow
runtime, so this stays one process. The rest must survive every one of my
processes being killed for its whole duration.

**The client is a different identity from the agent.** Dapr scopes state keys
and the workflow API per App ID, so my terminal cannot read the agent's memory
or its runs — it gets 404, silently if you let it. Anything the client needs,
it asks the **agent** for. The save is the agent's durable memory; each turn is
its own durable run. "save and quit" is just an exit; starting again resumes,
recapping the moment in one dramatic sentence. **Quitting during a rest must
still collect the waking event on my next turn**, whenever that is.

At the ending, show my adventure as a timeline built by reading the run history
back from Catalyst, plus the console link.

### 6. Definition of done

- **Play it yourself, end to end, including the secret** — and fix what playing
  reveals. Use instance IDs starting with `selftest-`.
- **Show me a turn killed mid-node RESUMING, not restarting** — name which
  nodes re-ran and which were replayed from history.
- **Quote the named step out of the run history.**
- **Kill every process mid-rest and show the timer still fired**, with
  timestamps: when the rest began, when it was due, when you killed what, that
  nothing was left running, when you restarted, when it woke.
- **Prove it is playable with no key at all.**
- **Prove no player-visible string explains why the door opens.** Enumerate the
  strings by exercising the engine rather than grepping it, check the model's
  prompts separately, scan a real transcript — and **show the check failing on
  a deliberately planted motive.**
- **Purge all `selftest-` runs** and confirm the project is clean.
- **Report what you actually ran, not what you expect to work.** Say what you
  could not test and what you left broken.

---

## Notes to self — why these lines exist

| Line | What went wrong without it |
|---|---|
| "Spike before you port" | The three load-bearing facts below are all invisible until you run something. Finding them after porting the game means rewriting the plumbing underneath it. |
| "a node of that name does **not** put it in the history" | Every LangGraph node ran as `execute_node_activity`, with `node_name` only inside a payload withheld at the `metadata` data-sharing level. A node named `secret_vault_found` satisfied the requirement on paper and not at all in practice. |
| "a node runs inside an activity and so cannot create a timer" | The obvious design — a node that awaits the rest — cannot be written. Discovered by trying. |
| "The client is a different identity" | Cost two separate bugs. `--new` silently did nothing, because Dapr prefixes state keys with the writing App ID. Then the client polled the rest workflow, got `404 ERR_INSTANCE_ID_NOT_FOUND`, swallowed it, spun for ten minutes and never delivered the waking event. |
| "Quitting during a rest must still collect the waking event" | Forced the fix into the agent's `load` step rather than the client's patience, which is where it belonged all along. |
| "never tell the model the condition" | The only airtight defence. A prompt that withholds the rule cannot leak it; a prompt that states it and forbids mentioning it is one paraphrase from giving the game away. |
| "`beat` and `verbatim` as separate fields" | With one field, a model asked to re-describe "you have not got 5 gold" narrates the purchase succeeding. |
| "useless right now stays on the menu" | "Taken choices disappear" generalised to "no inert choices", which hid `rest` at full health — making the durable-timer showpiece invisible until something hurt you. |
| "configurable **in seconds**" | "2 minutes, configurable" implied fractional minutes and shipped an `int("0.3")` crash. |
| "an Agent needs an inbound endpoint… if that makes it the wrong demo, say so" | The tunnel is the agent version's real cost: a flag spelled `--app-id` not `--id`, `local app connection not found` when restarting too soon, and a `GET /` health check the adapter answers 404 so the first call after startup fails. None of it exists in the workflow version. |
| "name which nodes re-ran and which were replayed" | "It resumed" is a claim. "`quick` did not re-run, `slow` was retried, `finish` saw both results" is evidence. |
| "Enumerate the strings by exercising the engine" | A grep over source misses what the engine composes at runtime, and a transcript scan misses what no one happened to type. Both, plus a planted motive to prove the check can fail. |
| "Report what you actually ran" | Kept a subagent's confident report from being relayed unverified. |

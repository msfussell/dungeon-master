# Two booth prompts, sized for QR codes

| file | bytes | QR |
|---|---|---|
| `qr-prompt-workflow.txt` | 2939 | v40, 177×177 modules |
| `qr-prompt-agent.txt` | 2945 | v40, 177×177 modules |

Byte-mode QR at error-correction level L caps at **2953 bytes**, so both sit
within ~15 bytes of the ceiling. That has two consequences worth knowing before
you print anything.

**They are the densest QR codes that exist.** 177×177 modules. Print each one
at **12 cm square or larger**, pure black on white, with a 4-module quiet zone,
and they scan fine from 20–30 cm on a modern phone. Printed at 5 cm on a glossy
badge they will not scan at all.

**Do not edit them without re-measuring.** One extra sentence pushes them over
the cap and the encoder will silently drop to a longer-mode failure or refuse.

```sh
wc -c qr-prompt-*.txt        # must stay under 2953
qrencode -l L -s 8 -m 4 -o workflow.png < qr-prompt-workflow.txt
qrencode -l L -s 8 -m 4 -o agent.png    < qr-prompt-agent.txt
```

`qrencode` is not installed on this machine (`brew install qrencode`), so the
codes have not been generated or test-scanned here — only the payload sizes are
verified.

## The better booth pattern, if you will take advice

Put a **short URL** in the QR instead of the prompt text, pointing at a raw
gist of the matching full-length prompt. Then:

- the code is version 3-5 instead of 40, and scans instantly across a table
- the prompt can be any length, so none of the reasoning has to be cut
- you can fix a typo without reprinting the sign

| QR | points at | bytes |
|---|---|---|
| workflow | `dungeon-master-PROMPT.md` | 8021 |
| agent | `dungeon-master-PROMPT-agent.md` | 10716 |

Those two are a matched pair: same game, same playability rules, same secret
and booth line, different durable shape underneath, and each ends with a table
of what went wrong without each line. They are the version to share with anyone
who is going to *build* from it rather than scan it in passing.

The two `qr-prompt-*.txt` files exist for the case where you want the prompt to
work with no network and no shortener.

## What each one is

**`qr-prompt-workflow.txt`** — the adventure as one long-lived Dapr Workflow.
Its history *is* the save file; the orchestration parks on
`wait_for_external_event` between moves; the worker only dials out, so there is
no inbound port. Leads with determinism and seeded dice, because that is what
breaks first. **Use this one for the demo**: fewer moving parts, no tunnel.

**`qr-prompt-agent.txt`** — the same dungeon as a Catalyst `Agent` fronting a
LangGraph app. Leads with the split that keeps it honest (the model may be wrong
about what you *meant*, never about what *happened*), then the two things a
LangGraph node cannot do — name a step in history, or create a timer — and the
cross-identity trap that the terminal cannot read the agent's memory or runs.
Better agent story, more to go wrong on conference wifi.

Both share the game, the playability rules, the secret and the booth line, so a
visitor who scans either gets a playable dungeon with the same ending.

## Cut for space

Each prompt is within 15 bytes of the hard cap, so rationale lost to
instruction. Dropped from the long version: why a fixed per-turn line is
wallpaper by turn 3; why silence reads as a hang; the predecessor-reuse policy;
the booth-demo framing; and the table of what went wrong without each line.
`dungeon-master-PROMPT.md` keeps all of it.

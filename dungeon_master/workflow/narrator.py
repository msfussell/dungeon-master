"""The narrator: optional LLM prose, with written prose as the floor.

DESIGN NOTES

* THE GAME MUST BE FULLY PLAYABLE WITH NO API KEY. So the written prose in world.py
  is not a degraded mode, it is the baseline, and the LLM is a reworder on top of it.
  Every call site has a fallback that is a complete, shippable sentence. Any provider
  exception, timeout or empty response falls through to it silently — a text adventure
  that shows you a stack trace has already lost.

* VERBATIM LINES NEVER REACH THIS MODULE. That is the whole defence against the
  failure the spec warns about: a model handed "you lose 3 health" will cheerfully
  render it as "you feel somewhat worse", and handed a rule will explain the rule
  away and then invent the event it thinks the rule implies. The orchestrator keeps
  `verbatim` and `beat` in separate fields and only ever sends `beat`. The system
  prompt additionally forbids inventing numbers and outcomes, as a second line of
  defence, not the first.

* THE DOOR'S REASON IS NOT IN THE PROMPT. The model cannot leak an explanation it was
  never given. The prompt also explicitly forbids speculating about it, because a
  model asked to describe a door that wants a stone will otherwise reach for a reason
  unprompted.
"""

from __future__ import annotations

import os

from ..engine import world

_TIMEOUT = float(os.environ.get("DM_LLM_TIMEOUT", "25"))

# How much prose to ask for. A 78-column terminal can take 2-4 sentences; a
# 240x320 panel cannot -- after the title, the HUD, the buttons and the rule
# lines there can be as little as 90px left, which is five short lines. Asking
# for prose that cannot be shown just produces text the player never reads, so
# the length is a property of the display, set by whoever is serving it.
PROSE_LENGTH = os.environ.get("DM_PROSE_LENGTH", "2-4 sentences")

_SYSTEM_TEMPLATE = """You are the narrator of a terse, dry, slightly menacing dungeon crawl.

Rules you must obey:
- Write {prose_length}. No more. Second person, present tense.
- Describe ONLY what the FACTS and the BEAT give you. Do not invent events, items,
  characters, exits, numbers, health changes, gold, or outcomes. If it is not in the
  facts, it did not happen.
- Never state or imply a number. No health totals, no gold amounts, no distances,
  no prices. The game prints those itself.
- Never give the player instructions, and never tell them what they should do next.
- Do not speculate about anyone's or anything's motives or reasons. In particular,
  if a door wants something, you do not know why, you do not guess, and you do not
  hint. Describe only what it does.
- No headings, no lists, no quotation marks around the whole thing, no meta-commentary
  about being a narrator. Just the prose.
"""


def _provider() -> str | None:
    """Whichever key is available. OpenAI wins if both are set, arbitrarily."""
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def provider_label() -> str:
    p = _provider()
    if p == "openai":
        return f"openai:{os.environ.get('DM_OPENAI_MODEL', 'gpt-4o-mini')}"
    if p == "anthropic":
        return f"anthropic:{os.environ.get('DM_ANTHROPIC_MODEL', 'claude-opus-5-5')}"
    return "written prose (no LLM key found)"


def _call_openai(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(timeout=_TIMEOUT, max_retries=1)
    resp = client.chat.completions.create(
        model=os.environ.get("DM_OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=220,
        temperature=0.9,  # flavour should vary between visits
    )
    return (resp.choices[0].message.content or "").strip()


def _call_anthropic(prompt: str) -> str:
    # NOTE: current Claude models reject `temperature`, so it is deliberately not
    # sent here. This path is written but UNEXERCISED: no Anthropic key is available
    # in this environment.
    import anthropic

    client = anthropic.Anthropic(timeout=_TIMEOUT, max_retries=1)
    resp = client.messages.create(
        model=os.environ.get("DM_ANTHROPIC_MODEL", "claude-opus-5-5"),
        max_tokens=220,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return "\n".join(parts).strip()


def _complete(prompt: str) -> str | None:
    p = _provider()
    try:
        if p == "openai":
            return _call_openai(prompt) or None
        if p == "anthropic":
            return _call_anthropic(prompt) or None
    except Exception:
        # Silent fallback. The written prose is always good enough to ship.
        return None
    return None


# ---------------------------------------------------------------------------
# The three things we ask the narrator for
# ---------------------------------------------------------------------------

def narrate_scene(req: dict) -> str:
    """Prose for one scene. `req` carries only facts and beats, never verbatim lines."""
    room_id = req["room"]
    r = world.room(room_id)
    first = req.get("first_visit", False)
    beat = req.get("beat", "")

    fallback_parts = []
    if beat:
        fallback_parts.append(beat)
    if first:
        fallback_parts.append(r["prose"])
    elif not beat:
        fallback_parts.append(r["prose"])
    fallback = " ".join(fallback_parts).strip() or r["prose"]

    prompt = (
        f"ROOM: {r['title']}\n"
        f"FACTS (the only things present): {r['facts']}\n"
        f"FIRST TIME HERE: {'yes' if first else 'no'}\n"
        f"BEAT (what just happened, if anything): {beat or 'nothing; the player is just looking around'}\n"
        f"TONE HINT: {'the player is carrying something that is hurting them' if req.get('carrying_lodestone') else 'ordinary dread'}\n\n"
        "Write the scene."
    )
    out = _complete(prompt)
    return out or fallback


def narrate_recap(req: dict) -> str:
    """One dramatic sentence, for resuming a saved run."""
    r = world.room(req["room"])
    fallback = (
        f"You come back to yourself in {r['title']}, exactly where you stopped, "
        "and the dark has not moved an inch in your absence."
    )
    prompt = (
        "The player is resuming a saved adventure.\n"
        f"ROOM: {r['title']}\n"
        f"FACTS: {r['facts']}\n"
        f"THEY HAVE: {req.get('inventory') or 'nothing'}\n"
        f"TURNS PLAYED SO FAR: {req.get('turn', 0)}\n\n"
        "Write EXACTLY ONE dramatic sentence that drops them back into this moment, "
        "as if the story had been stopped mid-breath and has just started again. "
        "Address them as 'you' and put them physically back in the room. "
        "One sentence. No numbers. No instructions."
    )
    out = _complete(prompt)
    if not out:
        return fallback
    # Enforce "one sentence" ourselves rather than trusting the model to count.
    first_sentence = out.replace("\n", " ").strip()
    for stop in (". ", "! ", "? "):
        if stop in first_sentence:
            first_sentence = first_sentence.split(stop)[0] + stop.strip()
            break
    return first_sentence


def narrate_waking(req: dict) -> str:
    """Prose for the random event that ends the campfire rest."""
    event = req["event"]
    fallback = event["beat"]
    prompt = (
        "The player has been asleep at a campfire in a dungeon and is being woken.\n"
        f"ROOM: {world.room(req['room'])['title']}\n"
        f"WHAT WAKES THEM (the only thing that happens): {event['beat']}\n\n"
        "Write the waking. Do not add a second event. No numbers."
    )
    out = _complete(prompt)
    return out or fallback


# Rendered once, with the configured length.
SYSTEM_PROMPT = _SYSTEM_TEMPLATE.replace("{prose_length}", PROSE_LENGTH)

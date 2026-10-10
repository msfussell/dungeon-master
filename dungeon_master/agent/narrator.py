"""The model's two jobs: read my English, and write the prose.

It is given facts and asked to say them well. It is never given a verbatim
line, never told the state of the secret, and never asked to decide anything.

With no key, every entry point returns written prose instead. The fallbacks are
meant to be read, not to be placeholders -- the dungeon is fully playable with
no model at all, it is just quieter.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

NARRATE_SYSTEM = """You are the narrator of a spare, grown-up fantasy text adventure.

Rules you never break:
- Two or three sentences. Never more. No preamble, no lists.
- Second person, present tense. Dry, concrete, physical detail.
- Never invent items, exits, characters or numbers. You are given the facts;
  say them well, do not add to them.
- Never list the player's options back to them; the game prints those itself.
- Never mention game mechanics: no health points, no turns, no "choices".
- Never hint at secrets or hidden conditions, and never speculate about why
  anything in this place wants anything. If you are told a thing refused the
  player, say it refused and say nothing about why.
"""

INTERPRET_SYSTEM = """You turn a player's words into one action in a text adventure.

Reply with JSON only: {"action": "...", "argument": "..."}

Allowed actions:
  walk     argument: north | south | east | west
  choose   argument: the exact text of one listed choice
  look     argument: ""
  status   argument: ""
  help     argument: ""
  rest     argument: ""
  save_and_quit  argument: ""

Pick the single closest action. Choose `choose` only for a choice that is
actually listed. If nothing fits, reply {"action": "none", "argument": ""}.
Never invent an action that is not in the list.
"""


def have_model() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def model_name() -> str:
    if not have_model():
        return "none (written prose)"
    return os.environ.get("DM_MODEL", "gpt-4o-mini")


def _chat(system: str, user: str, max_tokens: int, temperature: float) -> str | None:
    if not have_model():
        return None
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model_name(), max_tokens=max_tokens,
                         temperature=temperature, timeout=30, max_retries=1)
        return (llm.invoke([("system", system), ("human", user)]).content or "").strip()
    except Exception as exc:
        logger.warning("model call failed, falling back: %s", exc)
        return None


def interpret(scene: dict, raw: str) -> dict | None:
    """Map free text to one action. Returns None when the model cannot help."""
    menu = "\n".join(f"- {m}" for m in scene.get("menu") or []) or "- (none)"
    exits = ", ".join(scene.get("exits") or []) or "(none)"
    out = _chat(
        INTERPRET_SYSTEM,
        f"Room: {scene.get('title')}\nExits: {exits}\nChoices listed:\n{menu}\n\n"
        f"The player typed: {raw!r}",
        max_tokens=100, temperature=0.0)
    if not out:
        return None
    try:
        text = out[out.find("{"): out.rfind("}") + 1]
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    action = str(data.get("action") or "").strip().lower()
    if action in ("", "none"):
        return None
    return {"action": action, "argument": str(data.get("argument") or "")}


def narrate(scene: dict, beat: str, arrived: bool) -> str:
    """Write the scene. `beat` is prose; verbatim lines never come through here."""
    facts = [f"Room: {scene.get('title')}.",
             f"What is there: {scene.get('facts')}"]
    inv = scene.get("inventory") or []
    facts.append(f"Carrying: {', '.join(inv) if inv else 'nothing worth naming'}.")
    if arrived:
        facts.append("The traveller has just walked in; describe the room itself.")
    if scene.get("carrying_lodestone"):
        # The compass is built on cold. A narrator calling the lodestone warm
        # contradicts the only navigational aid in the game.
        facts.append("The ashen lodestone is ALWAYS cold, never warm. Do not say "
                     "how near or far anything is from it.")
    if scene.get("health", 99) <= 8:
        facts.append("The traveller is badly hurt; let that show.")
    if beat:
        facts.append(f"What just happened: {beat}")

    fallback = (scene.get("prose") or "") if arrived else (beat or scene.get("prose") or "")
    if arrived and beat:
        fallback = f"{scene.get('prose')} {beat}"
    return _chat(NARRATE_SYSTEM, "Narrate this beat.\n\n" + "\n".join(facts),
                 max_tokens=220, temperature=0.9) or fallback


def recap(scene: dict, last: str) -> str:
    """One dramatic sentence when a saved adventure is resumed."""
    where = scene.get("title") or "somewhere"
    return _chat(
        NARRATE_SYSTEM,
        "Write ONE dramatic sentence that drops the reader straight back into "
        "this exact moment, as if the story never paused. One sentence.\n\n"
        f"They left off in {where}. The moment they froze in: {last}",
        max_tokens=120, temperature=0.9) or (
        f"You come back to yourself in {where}, exactly where you stopped, with "
        "the dark still holding its breath.")

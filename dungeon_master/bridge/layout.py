"""Reshape a scene for a small screen.

The terminal renders a scene at 78 columns and lets it be as tall as it likes.
A 2.8" 240x320 panel at a readable font is about 24 columns by 16 rows, so a
full scene is roughly twice what fits. Something has to give, and *what* gives
is a design decision rather than an accident of truncation:

  1. Rule lines (`verbatim`) are never dropped and never truncated. They are
     the game speaking as referee -- "there is no way north", "you have not got
     5 gold" -- and a player who does not read them is being lied to about what
     happened. If they alone overfill the screen, they still all go.
  2. Button labels are never dropped. They are the only way to play.
  3. Prose is what gives. It is atmosphere, so it is wrapped, trimmed to the
     space left over, and marked as trimmed so the device can offer "more".

That ordering is the small-screen consequence of the verbatim rule the game is
built on, and it is the whole reason this module exists instead of the device
just calling textwrap.
"""

from __future__ import annotations

import re
import textwrap

# MEASURED on the panel, not guessed. TFT_eSPI font 2 here reports height 16,
# and a real sentence measured 183px for 29 characters -- about 6.3px each.
#
# These numbers mirror the firmware's drawing constants exactly. When the two
# disagree the prose gets clipped, which is the whole class of bug this module
# exists to prevent, so they are written out in pixels rather than in rows.
SCR_W, SCR_H = 240, 320
MARGIN = 6
TITLE_H = 22          # the room name bar
HUD_H = 18            # the health/gold line
ROW_H = 18            # a 16px font plus leading
BTN_H = 26            # button height -- smaller than it was, to buy text rows
BTN_GAP = 3
CHAR_W = 6.3

# Usable text width, 228px, which is about 36 characters. 34 leaves headroom
# for a capital-heavy line, since the font is proportional ("M" 10px, "i" 4px).
COLS = 34

# Rows the vault's picture occupies -- the dragon sprite is 65px tall, so four
# 18px rows. Text shares the screen with it rather than being replaced by it,
# and the firmware reserves the same number; disagreeing clips the prose.
ART_ROWS = 4


def text_rows(buttons: list[dict]) -> int:
    """How many 18px rows are left for rule lines and prose.

    This is the budget the whole module turns on, and it is not a constant: it
    shrinks as the scene offers more buttons. Four button rows leave nine text
    rows; six leave five.
    """
    btn_px = button_rows(buttons) * (BTN_H + BTN_GAP)
    return max(0, (SCR_H - TITLE_H - HUD_H - btn_px) // ROW_H)


def wrap(text: str, cols: int = COLS) -> list[str]:
    """Wrap one paragraph. Empty text gives no lines, not one blank line."""
    if not (text or "").strip():
        return []
    return textwrap.wrap(text.strip(), width=cols) or []


def button_rows(buttons: list[dict]) -> int:
    """How many rows a button set costs.

    Directions are short ("N  Hall of Teeth") and go two per row; numbered
    choices are long ("bed down at the campfire and rest") and get a full row
    each. Mixing the two is what lets the screen use its whole width instead of
    truncating every choice to half of it.
    """
    wide = sum(1 for b in buttons if b.get("wide"))
    narrow = len(buttons) - wide
    return wide + (narrow + 1) // 2


def compose(title: str, rule_lines: list[str], prose: str,
            buttons: list[dict], cols: int = COLS, art_rows: int = 0) -> dict:
    """Everything the device needs to draw one screen, and nothing else.

    Returns pre-wrapped lines so the device does no text measurement at all.
    """
    rule: list[str] = []
    for line in rule_lines or []:
        rule.extend(wrap(line, cols))

    budget = text_rows(buttons) - len(rule) - art_rows

    # Fill the budget with as many WHOLE sentences as fit.
    #
    # The first attempt wrapped the lot and then popped lines back to a
    # sentence end, which could throw away four usable rows to land on a full
    # stop. Adding sentences one at a time instead uses the space and still
    # never shows half a sentence -- a description that stops after a complete
    # thought reads as brevity; one that stops after "the air heavy with
    # moisture and" reads as a bug.
    sentences = re.findall(r"[^.!?]+[.!?]+[\s]*|[^.!?]+$", (prose or "").strip())
    prose_lines: list[str] = []
    trimmed = False
    if budget <= 0:
        # The rule lines alone fill the screen. They still all go: see the
        # module docstring. The prose waits for the player to ask.
        trimmed = bool((prose or "").strip())
    else:
        kept = ""
        for sentence in sentences:
            # Join on a single space: stripping each candidate would otherwise
            # weld "floor." to "A cold" and read as a typo.
            candidate = " ".join((kept + " " + sentence).split())
            lines = wrap(candidate, cols)
            if len(lines) > budget:
                trimmed = True
                break
            kept, prose_lines = candidate, lines
        if not prose_lines and sentences:
            # Even the first sentence overflows the space the rule lines left.
            # Show NOTHING rather than a fragment: half a sentence on screen
            # reads as a broken program, and the rule lines above it have
            # already said what actually happened. The "more" button carries
            # the prose for anyone who wants it.
            trimmed = True

    return {
        "title": title,
        "rule": rule,
        "prose": prose_lines,
        "more": trimmed,
        "buttons": buttons,
    }

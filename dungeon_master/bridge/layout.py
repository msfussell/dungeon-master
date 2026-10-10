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

import textwrap

# MEASURED on the panel, not guessed. TFT_eSPI font 2 on this board reports
# height=16 and a real sentence at 183px for 29 characters -- about 6.3px per
# character. With a 6px margin each side that is 228px of usable width, so:
#
#   228 / 6.3 ~= 36 characters
#
# Wrapping at 24 (the first guess) wasted a third of the width AND produced so
# many extra lines that the bottom of the prose was clipped. 34 is 36 with a
# little headroom for a capital-heavy line, since the font is proportional
# ("M" is 10px, "i" is 4px).
COLS = 34
ROWS = 15          # 320px / 18px rows, taking a 16px font plus leading

# Rows the chrome always costs: the title bar and the HUD line.
CHROME_ROWS = 3


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
            buttons: list[dict], cols: int = COLS, rows: int = ROWS) -> dict:
    """Everything the device needs to draw one screen, and nothing else.

    Returns pre-wrapped lines so the device does no text measurement at all.
    """
    rule: list[str] = []
    for line in rule_lines or []:
        rule.extend(wrap(line, cols))

    budget = rows - CHROME_ROWS - button_rows(buttons) - len(rule)

    prose_lines = wrap(prose, cols)
    trimmed = False
    if budget <= 0:
        # The rule lines alone fill the screen. They still all go: see the
        # module docstring. The prose waits for the player to ask.
        prose_lines, trimmed = [], bool(prose_lines)
    elif len(prose_lines) > budget:
        prose_lines, trimmed = prose_lines[:budget], True

    return {
        "title": title,
        "rule": rule,
        "prose": prose_lines,
        "more": trimmed,
        "buttons": buttons,
    }

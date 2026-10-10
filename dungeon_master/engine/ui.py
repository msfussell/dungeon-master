"""Terminal presentation: colour, noun highlighting, and the spinner.

DESIGN NOTES

* HIGHLIGHTED NOUNS ARE THE TUTORIAL. The spec's rule is to highlight the
  interactable nouns so the player learns that typed commands exist without being
  told. Each room declares its own nouns in world.py and they are highlighted here,
  in the prose only.

* VERBATIM LINES ARE NOT TOUCHED. Noun highlighting inserts escape codes mid-string,
  so it is applied to narrated prose and ambience only. A verbatim line gets one
  colour code before it and a reset after it, and its own characters are passed
  through untouched.

* THE SPINNER. Silence while the model writes reads as a hang, so there is always a
  spinner. It writes to stderr with \\r, so piping stdout stays clean — which is also
  what makes the self-test harness readable.
"""

from __future__ import annotations

import itertools
import re
import sys
import threading
import time

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"

TITLE = "\033[1;38;5;223m"
PROSE = "\033[38;5;252m"
AMBIENCE = "\033[2;38;5;245m"
NOUN = "\033[1;38;5;80m"       # interactable nouns
RULE = "\033[38;5;215m"        # verbatim rule / instruction lines
DOOR = "\033[1;38;5;141m"
MENU = "\033[38;5;151m"
EXITS = "\033[38;5;110m"
HUD = "\033[1;38;5;180m"
NOTICE = "\033[38;5;209m"
RECAP = "\033[1;3;38;5;189m"
WIN = "\033[1;38;5;121m"
LOSE = "\033[1;38;5;203m"
LINK = "\033[4;38;5;117m"

WIDTH = 78


def _no_colour() -> bool:
    import os
    return bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()


_PLAIN = None


def plain() -> bool:
    global _PLAIN
    if _PLAIN is None:
        _PLAIN = _no_colour()
    return _PLAIN


def c(code: str, text: str) -> str:
    return text if plain() else f"{code}{text}{RESET}"


def highlight(text: str, nouns: list[str]) -> str:
    """Bold-cyan the interactable nouns, longest first so 'lodestone' wins over 'stone'."""
    if not text or not nouns:
        return text
    if plain():
        return text
    for noun in sorted(nouns, key=len, reverse=True):
        pattern = re.compile(rf"\b({re.escape(noun)}s?)\b", re.IGNORECASE)
        text = pattern.sub(lambda m: f"{NOUN}{m.group(1)}{RESET}{PROSE}", text)
    return text


def wrap(text: str, width: int = WIDTH, indent: str = "") -> str:
    """Wrap on visible characters, ignoring ANSI escapes when measuring."""
    words = text.split()
    lines, cur, cur_len = [], [], 0
    for w in words:
        vis = len(re.sub(r"\033\[[0-9;]*m", "", w))
        if cur and cur_len + 1 + vis > width:
            lines.append(" ".join(cur))
            cur, cur_len = [w], vis
        else:
            cur.append(w)
            cur_len += (1 if cur_len else 0) + vis
    if cur:
        lines.append(" ".join(cur))
    return ("\n" + indent).join(lines)


def rule_line(char: str = "─") -> str:
    return c(DIM, char * WIDTH)


class Spinner:
    """A spinner for every wait, because silence reads as a hang."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str = "the dungeon master is writing"):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if sys.stderr.isatty():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        else:
            # Not a tty (harness, pipe): still say something, once.
            sys.stderr.write(f"[{self.label}...]\n")
            sys.stderr.flush()
        return self

    def _run(self):
        t0 = time.time()
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            elapsed = time.time() - t0
            tail = f" {elapsed:.0f}s" if elapsed > 3 else ""
            sys.stderr.write(f"\r\033[2m{frame} {self.label}{tail}\033[0m\033[K")
            sys.stderr.flush()
            time.sleep(0.08)

    def update(self, label: str):
        self.label = label

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()
        return False

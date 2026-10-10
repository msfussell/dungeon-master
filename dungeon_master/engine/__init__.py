"""The game itself: map, rules, parser, and the no-leak check.

Nothing here touches a clock, a network, a global RNG or Catalyst. That is what
lets both front ends share it, and what lets the whole rule set be exercised in
a second with no workflow runs at all -- see tests/.
"""

from . import engine, ui, world  # noqa: F401

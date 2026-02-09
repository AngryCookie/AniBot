from __future__ import annotations

from enum import Enum


class BettingMatchStatus(str, Enum):
    scheduled = "scheduled"
    open = "open"
    closed = "closed"
    resolved = "resolved"


class BettingBetStatus(str, Enum):
    pending = "pending"
    won = "won"
    lost = "lost"

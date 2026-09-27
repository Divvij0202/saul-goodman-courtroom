"""Payoff model: U = V * win - c * spent - mu * sanctions (general-sum).

Owner: Engineer 6, consumed by Engineer 5's game-theory layer.
"""

from __future__ import annotations

from courtroom.agents.base import COST_WEIGHT, SANCTION_WEIGHT
from courtroom.contracts import Ledger, Side, VerdictOutcome

WIN_VALUE = 10.0


def utilities(outcome: VerdictOutcome, ledgers: dict[Side, Ledger]) -> dict[Side, float]:
    winner = outcome.favours
    return {
        side: round(
            WIN_VALUE * (side is winner) - COST_WEIGHT * ledgers[side].spent - SANCTION_WEIGHT * ledgers[side].sanctions,
            6,
        )
        for side in Side
    }

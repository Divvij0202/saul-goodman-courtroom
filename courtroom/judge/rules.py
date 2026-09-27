"""Constants and exact numeric helpers of the rule engine.

Owner: Engineer 3 (Deterministic Judge).

All verdict-relevant arithmetic uses ``fractions.Fraction``. Floats appear only
in display fields. ``q()`` converts a float via its shortest ``repr``, so
``q(0.7) == Fraction(7, 10)`` exactly on every platform.
"""

from __future__ import annotations

import math
from fractions import Fraction

from courtroom.contracts import CaseType, StandardOfProof

ZERO = Fraction(0)
ONE = Fraction(1)

LLR_SCALE = Fraction(3)  # K: log-odds contributed by a unit-weight item
CORROBORATION_ALPHA = Fraction(1, 2)  # alpha: max corroboration bonus (+50 %)
CONTRADICTION_BETA = Fraction(4, 5)  # beta: pairwise contradiction pressure
MAX_CONTRADICTION_DISCOUNT = Fraction(9, 10)
IMPEACHMENT_FACTOR = Fraction(1, 2)  # credibility halves per successful impeachment
RELEVANCE_FLOOR = Fraction(1, 20)
DIRECTED_VERDICT_THRESHOLD = ZERO  # DV-1: any element with L_e < 0

PRIOR_LOG_ODDS: dict[CaseType, Fraction] = {
    CaseType.CRIMINAL: Fraction(-1),  # presumption of innocence (p ~= 0.27)
    CaseType.CIVIL: ZERO,
}

THRESHOLD_LOG_ODDS: dict[StandardOfProof, Fraction] = {
    StandardOfProof.BEYOND_REASONABLE_DOUBT: Fraction(11, 5),  # p ~= 0.90
    StandardOfProof.CLEAR_AND_CONVINCING: Fraction(11, 10),  # p ~= 0.75
    StandardOfProof.PREPONDERANCE: ZERO,  # strictly more likely than not
}

STRICT_STANDARDS = frozenset({StandardOfProof.PREPONDERANCE})

# Sanction points (utility penalties) and fines (budget units).
SANCTION_OVERRULED_OBJECTION = 0.25
SANCTION_BAD_FAITH_EVIDENCE = 2.0
SANCTION_VIOLATION = 1.0
FINE_VIOLATION = 1.0
OBJECTION_COST = 0.5
IMPEACHMENT_COST = 1.0
MOTION_COST = 0.5
CONTEMPT_VIOLATIONS = 3


def q(x: float | int | str | Fraction) -> Fraction:
    """Exact rational from a decimal-looking number."""
    if isinstance(x, Fraction):
        return x
    if isinstance(x, float):
        return Fraction(repr(x))
    return Fraction(x)


def fmt(x: Fraction) -> str:
    return f"{x.numerator}/{x.denominator}" if x.denominator != 1 else str(x.numerator)


def sigmoid(log_odds: float) -> float:
    """Display-only conversion; never used for a decision."""
    if log_odds >= 0:
        return 1.0 / (1.0 + math.exp(-log_odds))
    z = math.exp(log_odds)
    return z / (1.0 + z)


def threshold_met(log_odds: Fraction, standard: StandardOfProof) -> bool:
    tau = THRESHOLD_LOG_ODDS[standard]
    return log_odds > tau if standard in STRICT_STANDARDS else log_odds >= tau

"""Game-theoretic analysis: payoffs, exact Nash equilibria, dynamics, stress (Engineer 5)."""

from courtroom.gametheory.dynamics import replicator
from courtroom.gametheory.nash import GameAnalysis, analyze, support_enumeration, verify_equilibrium
from courtroom.gametheory.payoff import PayoffTable, StressReport, estimate_payoffs, stress, tournament

__all__ = [
    "GameAnalysis",
    "PayoffTable",
    "StressReport",
    "analyze",
    "estimate_payoffs",
    "replicator",
    "stress",
    "support_enumeration",
    "tournament",
    "verify_equilibrium",
]

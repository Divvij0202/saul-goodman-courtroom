"""Agent protocol, the public scoring oracle, and the noisy perception channel.

Owner: Engineer 4 (Strategic Agents).
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from typing import Protocol

from courtroom.contracts import (
    Action,
    CaseFile,
    EvidenceItem,
    ObjectionGround,
    PartyView,
    PerceivedItem,
    Side,
)
from courtroom.judge.admissibility import ground_is_valid
from courtroom.judge.rules import THRESHOLD_LOG_ODDS
from courtroom.judge.scoring import score_record

# Conversion of heuristic quantities into utility units (shared by all policies).
LOGODDS_VALUE = 1.5  # utility per unit of capped log-odds potential
COST_WEIGHT = 0.3  # utility per unit of budget spent (must match gametheory.payoff)
SANCTION_WEIGHT = 1.0  # utility per sanction point (must match gametheory.payoff)
POTENTIAL_HEADROOM = 1.0  # log-odds above threshold still worth securing


class Agent(Protocol):
    name: str

    def act(self, view: PartyView, oracle: Oracle) -> Action: ...

    def opening_statement(self, side: Side) -> str: ...


class ScoreCache:
    """Memoises exact scoring per (admitted set, impeachments). One per trial."""

    def __init__(self, case: CaseFile) -> None:
        self.case = case
        self._cache: dict[tuple[frozenset[str], tuple[tuple[str, int], ...]], dict[str, float]] = {}

    def log_odds(self, admitted: Iterable[str], impeachments: Mapping[str, int]) -> dict[str, float]:
        key = (frozenset(admitted), tuple(sorted((k, v) for k, v in impeachments.items() if v)))
        if key not in self._cache:
            exact = score_record(self.case, key[0], dict(key[1])).log_odds
            self._cache[key] = {k: float(v) for k, v in exact.items()}
        return self._cache[key]


class Oracle:
    """Read-only 'what if' interface to the (public, deterministic) scoring rule.

    The judge is transparent, so agents may simulate it. They cannot see hidden
    defects of opposing evidence or the opponent's future choices.
    """

    def __init__(self, cache: ScoreCache, admitted: Iterable[str], impeachments: Mapping[str, int]) -> None:
        self._cache = cache
        self._admitted = frozenset(admitted)
        self._impeachments = dict(impeachments)
        self._tau = float(THRESHOLD_LOG_ODDS[cache.case.standard])

    def log_odds(self, add: Iterable[str] = (), impeach: str | None = None) -> dict[str, float]:
        imp = dict(self._impeachments)
        if impeach is not None:
            imp[impeach] = imp.get(impeach, 0) + 1
        return self._cache.log_odds(self._admitted | frozenset(add), imp)

    def potential(self, log_odds: Mapping[str, float]) -> float:
        """Sum over elements of log-odds capped slightly above the threshold."""
        cap = self._tau + POTENTIAL_HEADROOM
        return sum(min(v, cap) for v in log_odds.values())

    def gain(self, side: Side, add: Iterable[str] = (), impeach: str | None = None) -> float:
        """Change in the side's favour (log-odds potential) if the hypothetical happened."""
        delta = self.potential(self.log_odds(add, impeach)) - self.potential(self.log_odds())
        return delta if side is Side.PROSECUTION else -delta


PRIOR_DEFECT_RATE = 0.15  # lawyers' prior that any given ground applies to an exhibit


def defect_posteriors(accuracy: float) -> tuple[float, float]:
    """Bayesian posterior P(defect | signal) for a positive and a negative signal.

    Channel: true-positive rate = ``accuracy``; false-positive rate = (1 - accuracy) / 4
    (spurious red flags are rarer than missed ones). Prior = ``PRIOR_DEFECT_RATE``.
    """
    tpr, fpr, pi = accuracy, (1.0 - accuracy) / 4.0, PRIOR_DEFECT_RATE
    positive = tpr * pi / (tpr * pi + fpr * (1 - pi))
    negative = (1 - tpr) * pi / ((1 - tpr) * pi + (1 - fpr) * (1 - pi))
    return positive, negative


def perceive(item: EvidenceItem, case: CaseFile, rng: random.Random) -> PerceivedItem:
    """Noisy observation of an opposing item's latent defects.

    For each ground the observer receives a binary red-flag signal through the
    channel described in ``defect_posteriors`` and holds the Bayesian posterior.
    Relevance is public (support is visible once offered), so it is known exactly.
    """
    acc = case.perception_accuracy
    fpr = (1.0 - acc) / 4.0
    positive, negative = defect_posteriors(acc)
    beliefs: dict[ObjectionGround, float] = {}
    for ground in ObjectionGround:
        truth = ground_is_valid(item, ground, case.case_type)
        if ground is ObjectionGround.RELEVANCE:
            beliefs[ground] = 1.0 if truth else 0.0
            continue
        flagged = rng.random() < (acc if truth else fpr)
        beliefs[ground] = round(positive if flagged else negative, 6)
    return PerceivedItem(
        evidence_id=item.id,
        title=item.title,
        kind=item.kind,
        support=dict(item.support),
        defect_belief=beliefs,
    )

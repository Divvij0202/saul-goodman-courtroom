"""Strategy profiles and the utility-driven counsel agent.

Owner: Engineer 4.

A single ``CounselAgent`` class is parameterised by a ``StrategyProfile``.
The aggressive/conservative distinction is data, not code, which keeps the
game-theoretic comparison fair: both profiles use the same oracle and the same
decision procedure, and differ only in their risk parameters.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from courtroom.agents.base import COST_WEIGHT, LOGODDS_VALUE, SANCTION_WEIGHT, Oracle
from courtroom.contracts import (
    Action,
    ActionType,
    EvidenceItem,
    Frozen,
    ObjectionGround,
    PartyView,
    Phase,
    Side,
)
from courtroom.judge.admissibility import BAD_FAITH_GROUNDS, valid_grounds
from courtroom.judge.rules import (
    IMPEACHMENT_COST,
    MOTION_COST,
    OBJECTION_COST,
    SANCTION_BAD_FAITH_EVIDENCE,
    SANCTION_OVERRULED_OBJECTION,
)


class StrategyProfile(Frozen):
    name: str
    label: str
    description: str
    max_known_defects: int  # present own items with at most this many sustainable defects
    min_gain: float  # minimum log-odds potential gain to spend a turn
    objection_belief: float  # object only if P(defect) >= this
    objection_min_impact: float  # ...and the item would move the potential at least this much
    reserve_fraction: float  # budget fraction held back for objections
    blanket_objection_impact: float | None = None  # object to any exhibit this impactful, whatever the belief
    adaptive: bool = False  # use expected-value reasoning with a learned opponent model
    always_move_dv: bool = False  # move for a directed verdict even if it looks hopeless


AGGRESSIVE = StrategyProfile(
    name="aggressive",
    label="Aggressive",
    description="Offers everything that helps, including defective items; objects on thin suspicion.",
    max_known_defects=2,
    min_gain=1e-9,
    objection_belief=0.35,
    objection_min_impact=0.0,
    reserve_fraction=0.0,
    blanket_objection_impact=1.0,
    always_move_dv=True,
)
CONSERVATIVE = StrategyProfile(
    name="conservative",
    label="Conservative",
    description="Offers only clean evidence with material impact; objects only when confident and it matters.",
    max_known_defects=0,
    min_gain=0.15,
    objection_belief=0.70,
    objection_min_impact=0.25,
    reserve_fraction=0.25,
)
ADAPTIVE = StrategyProfile(
    name="adaptive",
    label="Adaptive (EV)",
    description="Expected-value maximiser; learns the opponent's objection rate (Beta posterior).",
    max_known_defects=2,
    min_gain=0.0,
    objection_belief=0.0,
    objection_min_impact=0.0,
    reserve_fraction=0.10,
    adaptive=True,
)
PROFILES: dict[str, StrategyProfile] = {p.name: p for p in (AGGRESSIVE, CONSERVATIVE, ADAPTIVE)}


@dataclass(frozen=True, slots=True)
class _Option:
    value: float
    key: str
    action: Action


class CounselAgent:
    def __init__(self, profile: StrategyProfile, name: str | None = None) -> None:
        self.profile = profile
        self.name = name or profile.name

    def opening_statement(self, side: Side) -> str:
        role = "The People" if side is Side.PROSECUTION else "The defense"
        return f"{role} proceed with a {self.profile.label.lower()} posture: {self.profile.description}"

    # ------------------------------------------------------------------ dispatch

    def act(self, view: PartyView, oracle: Oracle) -> Action:
        if view.window == "motion":
            return self._motion(view)
        if view.window == "response":
            return self._respond(view, oracle)
        return self._primary(view, oracle)

    # ------------------------------------------------------------------ windows

    def _motion(self, view: PartyView) -> Action:
        weakest = min(float(e.log_odds_float) for e in view.snapshot.elements)
        move = (self.profile.always_move_dv or weakest < 0.0) and view.budget >= MOTION_COST
        if move:
            return Action(
                actor=view.side,
                type=ActionType.MOTION_DIRECTED_VERDICT,
                rationale=f"Weakest element at log-odds {weakest:.2f}; moving for directed verdict.",
            )
        return Action(actor=view.side, type=ActionType.PASS, rationale="Directed verdict unlikely; proceeding.")

    def _respond(self, view: PartyView, oracle: Oracle) -> Action:
        pending = view.pending
        if pending is None or view.budget < OBJECTION_COST:
            return Action(actor=view.side, type=ActionType.PASS, rationale="No objection.")
        impact = max(0.0, oracle.gain(view.side.opponent, add=[pending.evidence_id]))
        ground, belief = max(pending.defect_belief.items(), key=lambda kv: (kv[1], -list(ObjectionGround).index(kv[0])))
        if self.profile.adaptive:
            ev = (
                belief * impact * LOGODDS_VALUE
                - (1 - belief) * SANCTION_OVERRULED_OBJECTION * SANCTION_WEIGHT
                - OBJECTION_COST * COST_WEIGHT
            )
            should = ev > 0
            why = f"EV(object on {ground.value}) = {ev:+.2f} (belief {belief:.2f}, impact {impact:.2f})"
        else:
            blanket = self.profile.blanket_objection_impact
            should = (belief >= self.profile.objection_belief and impact >= self.profile.objection_min_impact) or (
                blanket is not None and impact >= blanket
            )
            why = f"belief {belief:.2f} vs {self.profile.objection_belief:.2f}, impact {impact:.2f}"
        if should:
            return Action(
                actor=view.side,
                type=ActionType.OBJECT,
                evidence_id=pending.evidence_id,
                ground=ground,
                rationale=f"Objection, {ground.value}: {why}.",
            )
        return Action(actor=view.side, type=ActionType.PASS, rationale=f"Let it in: {why}.")

    def _primary(self, view: PartyView, oracle: Oracle) -> Action:
        options = self._presentation_options(view, oracle) + self._impeachment_options(view, oracle)
        viable = [o for o in options if o.value > self.profile.min_gain]
        if not viable:
            return Action(actor=view.side, type=ActionType.REST, rationale="Nothing left worth the cost. Rest.")
        best = min(viable, key=lambda o: (-o.value, o.key))
        return best.action

    # ------------------------------------------------------------------ option generation

    def _spendable(self, view: PartyView) -> float:
        return view.budget - self.profile.reserve_fraction * view.reserve_basis

    def _opponent_objection_rate(self, view: PartyView) -> float:
        # Beta(1, 1) prior updated with observed objections per response window.
        return (view.opponent_objections + 1) / (view.opponent_response_windows + 2)

    def _presentation_options(self, view: PartyView, oracle: Oracle) -> list[_Option]:
        out: list[_Option] = []
        spendable = self._spendable(view)
        for item in view.own_evidence:
            if item.id in view.presented or item.presentation_cost > spendable:
                continue
            if view.phase is Phase.REBUTTAL and item.id not in view.rebuttal_targets:
                continue
            defects = valid_grounds(item, view.case_type)
            if len(defects) > self.profile.max_known_defects:
                continue
            gain = oracle.gain(view.side, add=[item.id])
            if gain <= 0:
                continue
            value = self._value_presentation(view, item, gain, defects)
            out.append(
                _Option(
                    value=value,
                    key=item.id,
                    action=Action(
                        actor=view.side,
                        type=ActionType.PRESENT_EVIDENCE,
                        evidence_id=item.id,
                        rationale=(
                            f"Offer {item.id}: +{gain:.2f} potential"
                            + (f", known defects {[d.value for d in defects]}" if defects else "")
                            + f" (value {value:.2f})."
                        ),
                    ),
                )
            )
        return out

    def _value_presentation(
        self, view: PartyView, item: EvidenceItem, gain: float, defects: tuple[ObjectionGround, ...]
    ) -> float:
        if not self.profile.adaptive:
            return gain
        p_obj = self._opponent_objection_rate(view) if defects else 0.0
        bad_faith = any(d in BAD_FAITH_GROUNDS for d in defects)
        return (
            (1 - p_obj) * gain * LOGODDS_VALUE
            - item.presentation_cost * COST_WEIGHT
            - (p_obj * SANCTION_BAD_FAITH_EVIDENCE * SANCTION_WEIGHT if bad_faith else 0.0)
        )

    def _impeachment_options(self, view: PartyView, oracle: Oracle) -> list[_Option]:
        if self._spendable(view) < IMPEACHMENT_COST:
            return []
        own = {i.id: i for i in view.own_evidence}
        out: list[_Option] = []
        for item_id, witness_id in view.impeachment_options:
            item = own.get(item_id)
            if item is None or witness_id not in item.impeaches:
                continue
            gain = oracle.gain(view.side, impeach=witness_id)
            if gain <= 0:
                continue
            value = gain * LOGODDS_VALUE - IMPEACHMENT_COST * COST_WEIGHT if self.profile.adaptive else gain
            out.append(
                _Option(
                    value=value,
                    key=f"~{item_id}:{witness_id}",
                    action=Action(
                        actor=view.side,
                        type=ActionType.IMPEACH,
                        evidence_id=item_id,
                        witness_id=witness_id,
                        rationale=f"Impeach {witness_id} with {item_id}: +{gain:.2f} potential.",
                    ),
                )
            )
        return out


class MixedAgent:
    """Plays Aggressive with probability ``p`` (drawn once per trial from the seed)."""

    def __init__(self, p_aggressive: float, rng: random.Random) -> None:
        self.p_aggressive = p_aggressive
        chosen = AGGRESSIVE if rng.random() < p_aggressive else CONSERVATIVE
        self._inner = CounselAgent(chosen)
        self.realised = chosen.name
        self.name = f"mixed:{p_aggressive:g}"

    def opening_statement(self, side: Side) -> str:
        return f"[mixed strategy realised as {self.realised}] " + self._inner.opening_statement(side)

    def act(self, view: PartyView, oracle: Oracle) -> Action:
        return self._inner.act(view, oracle)

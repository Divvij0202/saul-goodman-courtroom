"""Procedural finite-state machine and party ledgers.

Owner: Engineer 2 (Procedure & Objection Arbiter).

The state object is the only mutable thing in a trial. It knows *whose turn it
is* and *what is legal*, but nothing about evidentiary weight (that belongs to
the judge).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from courtroom.contracts import CaseFile, EvidenceKind, Ledger, Phase, Side, Window

# The phases in which a party puts on evidence, and who leads each one.
CASE_PHASES: dict[Phase, Side] = {
    Phase.PROSECUTION_CASE: Side.PROSECUTION,
    Phase.DEFENSE_CASE: Side.DEFENSE,
    Phase.REBUTTAL: Side.PROSECUTION,
}
PRIMARY_ACTIONS = frozenset({"present_evidence", "impeach", "pass", "rest"})
RESPONSE_ACTIONS = frozenset({"object", "pass"})
MOTION_ACTIONS = frozenset({"motion_directed_verdict", "pass"})
ALLOWED: dict[Window, frozenset[str]] = {
    "primary": PRIMARY_ACTIONS,
    "response": RESPONSE_ACTIONS,
    "motion": MOTION_ACTIONS,
}
STALL_LIMIT = 2  # consecutive primary passes deemed a rest


@dataclass
class MutableLedger:
    side: Side
    budget_start: float
    budget: float
    spent: float = 0.0
    sanctions: float = 0.0
    violations: int = 0
    presented: int = 0
    admitted: int = 0
    excluded: int = 0
    objections: int = 0
    sustained: int = 0
    overruled: int = 0
    impeachments: int = 0
    response_windows: int = 0

    def charge(self, amount: float) -> float:
        """Spend up to ``amount``; returns what was actually charged (never negative budget)."""
        paid = min(amount, self.budget)
        self.budget = round(self.budget - paid, 6)
        self.spent = round(self.spent + paid, 6)
        return paid

    def freeze(self) -> Ledger:
        return Ledger(
            side=self.side,
            budget_start=self.budget_start,
            budget=self.budget,
            spent=self.spent,
            sanctions=self.sanctions,
            violations=self.violations,
            presented=self.presented,
            admitted=self.admitted,
            excluded=self.excluded,
            objections=self.objections,
            sustained=self.sustained,
            overruled=self.overruled,
            impeachments=self.impeachments,
        )


@dataclass
class ProcedureState:
    case: CaseFile
    phase: Phase = Phase.OPENING
    pending: str | None = None  # evidence id awaiting a response window
    presented: list[str] = field(default_factory=list)
    admitted: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    impeachments: dict[str, int] = field(default_factory=dict)
    used_impeachments: set[tuple[str, str]] = field(default_factory=set)
    turns_used: dict[Phase, int] = field(default_factory=dict)
    consecutive_passes: int = 0
    motion_made: bool = False
    directed: tuple[bool, str | None] = (False, None)
    ledgers: dict[Side, MutableLedger] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ledgers:
            self.ledgers = {s: MutableLedger(side=s, budget_start=self.case.budget, budget=self.case.budget) for s in Side}

    # ------------------------------------------------------------------ turn logic

    def expected(self) -> tuple[Side, Window] | None:
        """Who must act next and in which window, or ``None`` if the judge acts."""
        if self.phase in CASE_PHASES:
            lead = CASE_PHASES[self.phase]
            return (lead.opponent, "response") if self.pending else (lead, "primary")
        if self.phase is Phase.DIRECTED_VERDICT_REVIEW:
            return (Side.DEFENSE, "motion")
        return None

    def turn_cap(self, phase: Phase | None = None) -> int:
        phase = phase or self.phase
        return self.case.rebuttal_turns if phase is Phase.REBUTTAL else self.case.max_primary_turns

    def turns_left(self) -> int:
        return max(0, self.turn_cap() - self.turns_used.get(self.phase, 0))

    def consume_primary_turn(self) -> None:
        self.turns_used[self.phase] = self.turns_used.get(self.phase, 0) + 1

    def next_phase_after_rest(self) -> Phase:
        match self.phase:
            case Phase.PROSECUTION_CASE:
                return Phase.DIRECTED_VERDICT_REVIEW
            case Phase.DEFENSE_CASE:
                return Phase.REBUTTAL if self.case.rebuttal_turns > 0 else Phase.DELIBERATION
            case _:
                return Phase.DELIBERATION

    def enter(self, phase: Phase) -> None:
        self.phase = phase
        self.pending = None
        self.consecutive_passes = 0

    # ------------------------------------------------------------------ record queries

    def testified_witnesses(self, side: Side) -> tuple[str, ...]:
        """Witnesses whose testimony for ``side`` has been admitted."""
        out: set[str] = set()
        for eid in self.admitted:
            item = self.case.item(eid)
            if item and item.owner is side and item.kind is EvidenceKind.TESTIMONY and item.witness_id:
                out.add(item.witness_id)
        return tuple(sorted(out))

    def rebuttal_targets(self) -> tuple[str, ...]:
        """Prosecution items that may be offered in rebuttal: those contradicting admitted defense evidence."""
        admitted_defense = {eid for eid in self.admitted if (it := self.case.item(eid)) is not None and it.owner is Side.DEFENSE}
        targets = set()
        for a, b in self.case.contradiction_edges():
            for mine, theirs in ((a, b), (b, a)):
                item = self.case.item(mine)
                if item and item.owner is Side.PROSECUTION and theirs in admitted_defense and mine not in self.presented:
                    targets.add(mine)
        return tuple(sorted(targets))

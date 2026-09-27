"""Pydantic v2 data contracts shared by every subsystem.

Owner: Engineer 1 (Contracts & Case Library).

Rules for this module:
* Pure data. No behaviour beyond validation and trivial derived properties.
* Every model is frozen; mutation happens only by constructing new objects.
* Numbers that feed the judge are floats with <= 4 decimals so they convert
  exactly to rationals via ``Fraction(repr(x))``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

__all__ = [
    "DEFAULT_COST",
    "Action",
    "ActionType",
    "CaseFile",
    "CaseType",
    "Contribution",
    "ElementScore",
    "EventKind",
    "EvidenceGraph",
    "EvidenceItem",
    "EvidenceKind",
    "Frozen",
    "GraphEdge",
    "GraphNode",
    "Ledger",
    "LegalElement",
    "ObjectionGround",
    "PartyView",
    "PerceivedItem",
    "Phase",
    "RuleFiring",
    "ScoreSnapshot",
    "Side",
    "StandardOfProof",
    "TrialEvent",
    "TrialResult",
    "Verdict",
    "VerdictOutcome",
    "Window",
    "Witness",
]

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- enums


class Side(StrEnum):
    PROSECUTION = "prosecution"
    DEFENSE = "defense"

    @property
    def opponent(self) -> Side:
        return Side.DEFENSE if self is Side.PROSECUTION else Side.PROSECUTION


class CaseType(StrEnum):
    CRIMINAL = "criminal"
    CIVIL = "civil"


class StandardOfProof(StrEnum):
    BEYOND_REASONABLE_DOUBT = "beyond_reasonable_doubt"
    CLEAR_AND_CONVINCING = "clear_and_convincing"
    PREPONDERANCE = "preponderance"


class EvidenceKind(StrEnum):
    DOCUMENT = "document"
    DIGITAL_LOG = "digital_log"
    PHYSICAL = "physical"
    FINANCIAL_RECORD = "financial_record"
    TESTIMONY = "testimony"
    EXPERT = "expert"


class ObjectionGround(StrEnum):
    HEARSAY = "hearsay"
    RELEVANCE = "relevance"
    AUTHENTICATION = "authentication"
    ILLEGALLY_OBTAINED = "illegally_obtained"
    LATE_DISCLOSURE = "late_disclosure"
    SPECULATION = "speculation"


class Phase(StrEnum):
    OPENING = "opening"
    PROSECUTION_CASE = "prosecution_case"
    DIRECTED_VERDICT_REVIEW = "directed_verdict_review"
    DEFENSE_CASE = "defense_case"
    REBUTTAL = "rebuttal"
    DELIBERATION = "deliberation"
    CLOSED = "closed"


class ActionType(StrEnum):
    PRESENT_EVIDENCE = "present_evidence"
    OBJECT = "object"
    IMPEACH = "impeach"
    MOTION_DIRECTED_VERDICT = "motion_directed_verdict"
    PASS = "pass"
    REST = "rest"


class EventKind(StrEnum):
    PHASE_CHANGE = "phase_change"
    ACTION = "action"
    RULING = "ruling"
    VIOLATION = "violation"
    DIRECTED_VERDICT = "directed_verdict"
    WATCHDOG = "watchdog"
    VERDICT = "verdict"


class VerdictOutcome(StrEnum):
    GUILTY = "guilty"
    NOT_GUILTY = "not_guilty"
    LIABLE = "liable"
    NOT_LIABLE = "not_liable"
    DIRECTED_ACQUITTAL = "directed_acquittal"

    @property
    def favours(self) -> Side:
        return Side.PROSECUTION if self in (VerdictOutcome.GUILTY, VerdictOutcome.LIABLE) else Side.DEFENSE


Window = Literal["primary", "response", "motion"]

# Canonical per-kind presentation cost (litigation budget units).
DEFAULT_COST: dict[EvidenceKind, float] = {
    EvidenceKind.DOCUMENT: 1.0,
    EvidenceKind.DIGITAL_LOG: 1.0,
    EvidenceKind.PHYSICAL: 1.0,
    EvidenceKind.FINANCIAL_RECORD: 1.0,
    EvidenceKind.TESTIMONY: 1.5,
    EvidenceKind.EXPERT: 2.0,
}


def _four_decimals(v: float) -> float:
    if round(v, 4) != v:
        raise ValueError(f"{v!r} has more than 4 decimals; judge inputs must be exact decimals")
    return v


# --------------------------------------------------------------------------- case file


class LegalElement(Frozen):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    description: str


class Witness(Frozen):
    id: str = Field(pattern=r"^[A-Za-z0-9_\-]+$")
    name: str
    role: str
    credibility: float = Field(ge=0.0, le=1.0)
    bias_note: str | None = None

    @field_validator("credibility")
    @classmethod
    def _exact_credibility(cls, v: float) -> float:
        return _four_decimals(v)


class EvidenceItem(Frozen):
    id: str = Field(pattern=r"^[A-Za-z0-9_\-]+$")
    title: str
    description: str
    kind: EvidenceKind
    owner: Side
    fact_id: str
    support: dict[str, float]
    reliability: float = Field(ge=0.0, le=1.0)
    witness_id: str | None = None
    hearsay: bool = False
    authenticated: bool = True
    lawfully_obtained: bool = True
    disclosed: bool = True
    personal_knowledge: bool = True
    contradicts: tuple[str, ...] = ()
    impeaches: tuple[str, ...] = ()
    cost: float | None = Field(default=None, ge=0.0)

    @field_validator("reliability")
    @classmethod
    def _exact_reliability(cls, v: float) -> float:
        return _four_decimals(v)

    @field_validator("support")
    @classmethod
    def _support_range(cls, v: dict[str, float]) -> dict[str, float]:
        for key, val in v.items():
            if not -1.0 <= val <= 1.0:
                raise ValueError(f"support[{key}]={val} outside [-1, 1]")
            _four_decimals(val)
        return v

    @model_validator(mode="after")
    def _testimony_needs_witness(self) -> EvidenceItem:
        if self.kind is EvidenceKind.TESTIMONY and self.witness_id is None:
            raise ValueError(f"testimony {self.id} must reference a witness")
        return self

    @property
    def presentation_cost(self) -> float:
        return self.cost if self.cost is not None else DEFAULT_COST[self.kind]


class CaseFile(Frozen):
    id: str = Field(pattern=r"^[a-z0-9_\-]+$")
    title: str
    synopsis: str
    case_type: CaseType
    standard: StandardOfProof
    charge: str
    elements: tuple[LegalElement, ...] = Field(min_length=1)
    witnesses: tuple[Witness, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    budget: float = Field(default=10.0, gt=0)
    max_primary_turns: int = Field(default=8, ge=1, le=64)
    rebuttal_turns: int = Field(default=2, ge=0, le=16)
    perception_accuracy: float = Field(default=0.8, ge=0.5, le=1.0)
    tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _referential_integrity(self) -> CaseFile:
        element_ids = {e.id for e in self.elements}
        witness_ids = {w.id for w in self.witnesses}
        evidence_ids = [e.id for e in self.evidence]
        if len(element_ids) != len(self.elements):
            raise ValueError("duplicate element ids")
        if len(witness_ids) != len(self.witnesses):
            raise ValueError("duplicate witness ids")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("duplicate evidence ids")
        known = set(evidence_ids)
        for item in self.evidence:
            unknown_elements = set(item.support) - element_ids
            if unknown_elements:
                raise ValueError(f"{item.id} supports unknown elements {sorted(unknown_elements)}")
            if item.witness_id is not None and item.witness_id not in witness_ids:
                raise ValueError(f"{item.id} references unknown witness {item.witness_id}")
            for other in item.contradicts:
                if other == item.id or other not in known:
                    raise ValueError(f"{item.id} contradicts invalid item {other}")
            for w in item.impeaches:
                if w not in witness_ids:
                    raise ValueError(f"{item.id} impeaches unknown witness {w}")
        return self

    # Convenience lookups (pure).
    def item(self, evidence_id: str) -> EvidenceItem | None:
        return next((e for e in self.evidence if e.id == evidence_id), None)

    def witness(self, witness_id: str) -> Witness | None:
        return next((w for w in self.witnesses if w.id == witness_id), None)

    def contradiction_edges(self) -> list[tuple[str, str]]:
        """Undirected, deduplicated, sorted contradiction edges."""
        edges = {tuple(sorted((i.id, j))) for i in self.evidence for j in i.contradicts}
        return sorted((a, b) for a, b in edges)


# --------------------------------------------------------------------------- actions


class Action(Frozen):
    """An agent's requested move. Deliberately permissive: bad-faith or malformed
    actions must be *representable* so the procedure layer can reject and penalise
    them instead of crashing."""

    actor: Side
    type: ActionType
    evidence_id: str | None = None
    witness_id: str | None = None
    ground: ObjectionGround | None = None
    rationale: str = ""


# --------------------------------------------------------------------------- judge output


class RuleFiring(Frozen):
    rule_id: str
    detail: str


class Contribution(Frozen):
    evidence_id: str
    element_id: str
    support: float
    strength: float
    contradiction_discount: float
    corroboration_factor: float
    weight: float
    log_odds: float
    counted: bool  # False when superseded by a stronger item on the same fact


class ElementScore(Frozen):
    element_id: str
    log_odds: str  # exact rational, e.g. "11/5"
    log_odds_float: float
    probability: float
    threshold: str
    threshold_probability: float
    met: bool
    contributions: tuple[Contribution, ...]


class ScoreSnapshot(Frozen):
    elements: tuple[ElementScore, ...]
    burden_index: float  # probability of the weakest element
    weakest_element: str
    all_met: bool


class Verdict(Frozen):
    outcome: VerdictOutcome
    reason: str
    decisive_element: str | None
    snapshot: ScoreSnapshot
    rules: tuple[RuleFiring, ...]


# --------------------------------------------------------------------------- agent view


class PerceivedItem(Frozen):
    """An opponent item as seen through the noisy perception channel."""

    evidence_id: str
    title: str
    kind: EvidenceKind
    support: dict[str, float]
    defect_belief: dict[ObjectionGround, float]


class PartyView(Frozen):
    side: Side
    phase: Phase
    window: Window
    case_id: str
    case_type: CaseType
    standard: StandardOfProof
    element_ids: tuple[str, ...]
    own_evidence: tuple[EvidenceItem, ...]
    presented: tuple[str, ...]
    admitted: tuple[str, ...]
    excluded: tuple[str, ...]
    pending: PerceivedItem | None
    snapshot: ScoreSnapshot
    budget: float
    reserve_basis: float  # starting budget
    opponent_budget: float
    turns_left: int
    impeachment_options: tuple[tuple[str, str], ...]  # (own item id, opposing witness id), unused and testified
    rebuttal_targets: tuple[str, ...]
    opponent_objections: int
    opponent_response_windows: int


# --------------------------------------------------------------------------- trial record


class Ledger(Frozen):
    side: Side
    budget_start: float
    budget: float
    spent: float
    sanctions: float
    violations: int
    presented: int
    admitted: int
    excluded: int
    objections: int
    sustained: int
    overruled: int
    impeachments: int


class TrialEvent(Frozen):
    seq: int
    phase: Phase
    kind: EventKind
    actor: Side | None = None
    action: Action | None = None
    summary: str
    subject: str | None = None  # evidence id this event is about, if any
    status: Literal["offered", "admitted", "excluded", "impeached"] | None = None
    rules: tuple[RuleFiring, ...] = ()
    burden_index: float | None = None
    element_probabilities: dict[str, float] = Field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""


class GraphNode(Frozen):
    id: str
    label: str
    owner: Side
    kind: EvidenceKind
    status: Literal["unpresented", "admitted", "excluded"]
    weight: float


class GraphEdge(Frozen):
    source: str
    target: str
    relation: Literal["contradicts", "corroborates"]


class EvidenceGraph(Frozen):
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


class TrialResult(Frozen):
    case_id: str
    case_title: str
    seed: int
    prosecution_strategy: str
    defense_strategy: str
    events: tuple[TrialEvent, ...]
    verdict: Verdict
    ledgers: dict[Side, Ledger]
    utilities: dict[Side, float]
    digest: str
    graph: EvidenceGraph

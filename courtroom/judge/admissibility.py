"""Admissibility law: which objection grounds are valid against which item.

Owner: Engineer 3. This is the single source of truth. Agents call it to reason
about their *own* evidence (a lawyer knows the rules of evidence), and the
objection arbiter calls it to rule.
"""

from __future__ import annotations

from courtroom.contracts import (
    CaseFile,
    CaseType,
    EvidenceItem,
    EvidenceKind,
    ObjectionGround,
    RuleFiring,
    Side,
)
from courtroom.judge.rules import RELEVANCE_FLOOR, q

RULE_IDS: dict[ObjectionGround, str] = {
    ObjectionGround.HEARSAY: "OBJ-HEARSAY",
    ObjectionGround.RELEVANCE: "OBJ-RELEVANCE",
    ObjectionGround.AUTHENTICATION: "OBJ-AUTH",
    ObjectionGround.ILLEGALLY_OBTAINED: "OBJ-EXCLUSIONARY",
    ObjectionGround.LATE_DISCLOSURE: "OBJ-DISCLOSURE",
    ObjectionGround.SPECULATION: "OBJ-SPECULATION",
}

# Grounds whose success implies the presenter acted in bad faith (it knew).
BAD_FAITH_GROUNDS = frozenset({ObjectionGround.ILLEGALLY_OBTAINED, ObjectionGround.LATE_DISCLOSURE})


def ground_is_valid(item: EvidenceItem, ground: ObjectionGround, case_type: CaseType) -> bool:
    match ground:
        case ObjectionGround.HEARSAY:
            return item.hearsay
        case ObjectionGround.RELEVANCE:
            return max((abs(q(v)) for v in item.support.values()), default=q(0)) < RELEVANCE_FLOOR
        case ObjectionGround.AUTHENTICATION:
            return not item.authenticated
        case ObjectionGround.ILLEGALLY_OBTAINED:
            # The exclusionary rule restrains the state: prosecution evidence, criminal cases only.
            return not item.lawfully_obtained and item.owner is Side.PROSECUTION and case_type is CaseType.CRIMINAL
        case ObjectionGround.LATE_DISCLOSURE:
            return not item.disclosed
        case ObjectionGround.SPECULATION:
            return item.kind is EvidenceKind.TESTIMONY and not item.personal_knowledge


def valid_grounds(item: EvidenceItem, case_type: CaseType) -> tuple[ObjectionGround, ...]:
    """All grounds on which an objection to ``item`` would be sustained, in enum order."""
    return tuple(g for g in ObjectionGround if ground_is_valid(item, g, case_type))


def rule_on_objection(item: EvidenceItem, ground: ObjectionGround, case: CaseFile) -> tuple[bool, RuleFiring]:
    sustained = ground_is_valid(item, ground, case.case_type)
    verb = "SUSTAINED" if sustained else "OVERRULED"
    return sustained, RuleFiring(
        rule_id=RULE_IDS[ground],
        detail=f"Objection ({ground.value}) to {item.id} {verb}.",
    )

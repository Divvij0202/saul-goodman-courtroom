"""Procedural validation: every action is checked against a typed rule table.

Owner: Engineer 2.

``validate`` never raises and never mutates. It returns ``None`` for a legal
action or a ``Violation`` naming the first rule broken (rules are checked in a
fixed order, so the result is deterministic).
"""

from __future__ import annotations

from dataclasses import dataclass

from courtroom.contracts import Action, ActionType, Phase, Side
from courtroom.judge.rules import IMPEACHMENT_COST, MOTION_COST, OBJECTION_COST
from courtroom.procedure.state import ALLOWED, ProcedureState

VIOLATION_RULES: dict[str, str] = {
    "V-TURN": "Actor is not the party entitled to act.",
    "V-WINDOW": "Action type not permitted in the current window.",
    "V-MISSING-FIELD": "A required field is missing.",
    "V-UNKNOWN-EVIDENCE": "Referenced evidence does not exist.",
    "V-NOT-OWNER": "A party may only offer its own evidence.",
    "V-DUPLICATE": "Evidence already offered, or impeachment already made.",
    "V-BUDGET": "Insufficient litigation budget.",
    "V-REBUTTAL-SCOPE": "Rebuttal evidence must contradict admitted defense evidence.",
    "V-OBJ-TARGET": "Objection must target the pending item (contemporaneous-objection rule).",
    "V-IMPEACH-TARGET": "Only an opposing witness who has testified may be impeached.",
    "V-AGENT-FAULT": "The agent failed to produce a well-formed action.",
}


@dataclass(frozen=True, slots=True)
class Violation:
    rule_id: str
    detail: str


def _v(rule_id: str, extra: str = "") -> Violation:
    return Violation(rule_id, VIOLATION_RULES[rule_id] + (f" ({extra})" if extra else ""))


def validate(action: Action, state: ProcedureState, expected_side: Side, window: str) -> Violation | None:
    case = state.case
    ledger = state.ledgers.get(action.actor)

    if action.actor is not expected_side or ledger is None:
        return _v("V-TURN", f"expected {expected_side.value}, got {action.actor}")
    if action.type.value not in ALLOWED[window]:  # type: ignore[index]
        return _v("V-WINDOW", f"{action.type.value} in {window} window")

    match action.type:
        case ActionType.PRESENT_EVIDENCE:
            if not action.evidence_id:
                return _v("V-MISSING-FIELD", "evidence_id")
            item = case.item(action.evidence_id)
            if item is None:
                return _v("V-UNKNOWN-EVIDENCE", action.evidence_id)
            if item.owner is not action.actor:
                return _v("V-NOT-OWNER", item.id)
            if item.id in state.presented:
                return _v("V-DUPLICATE", item.id)
            if ledger.budget < item.presentation_cost:
                return _v("V-BUDGET", f"needs {item.presentation_cost}, has {ledger.budget}")
            if state.phase is Phase.REBUTTAL and item.id not in state.rebuttal_targets():
                return _v("V-REBUTTAL-SCOPE", item.id)

        case ActionType.IMPEACH:
            if not action.evidence_id or not action.witness_id:
                return _v("V-MISSING-FIELD", "evidence_id and witness_id")
            item = case.item(action.evidence_id)
            if item is None:
                return _v("V-UNKNOWN-EVIDENCE", action.evidence_id)
            if item.owner is not action.actor:
                return _v("V-NOT-OWNER", item.id)
            if action.witness_id not in state.testified_witnesses(action.actor.opponent):
                return _v("V-IMPEACH-TARGET", action.witness_id)
            if (item.id, action.witness_id) in state.used_impeachments:
                return _v("V-DUPLICATE", f"{item.id} vs {action.witness_id}")
            if ledger.budget < IMPEACHMENT_COST:
                return _v("V-BUDGET", "impeachment")

        case ActionType.OBJECT:
            if action.ground is None:
                return _v("V-MISSING-FIELD", "ground")
            if state.pending is None or (action.evidence_id not in (None, state.pending)):
                return _v("V-OBJ-TARGET", str(action.evidence_id))
            if ledger.budget < OBJECTION_COST:
                return _v("V-BUDGET", "objection")

        case ActionType.MOTION_DIRECTED_VERDICT:
            if ledger.budget < MOTION_COST:
                return _v("V-BUDGET", "motion")

        case ActionType.PASS | ActionType.REST:
            pass

    return None

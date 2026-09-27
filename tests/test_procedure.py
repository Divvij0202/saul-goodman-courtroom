"""Engineer 2: procedural FSM, validator rule table, deadlock and bad-faith handling."""

from __future__ import annotations

import itertools
import random

import pytest

from courtroom.agents import AGGRESSIVE, CONSERVATIVE, CounselAgent, ScriptedAgent
from courtroom.cases import CASES
from courtroom.contracts import Action, ActionType, EventKind, ObjectionGround, Phase, Side
from courtroom.engine import Court
from courtroom.procedure import ProcedureState, validate
from tests.conftest import item, make_case

P, D = Side.PROSECUTION, Side.DEFENSE


def rules_fired(result) -> list[str]:
    return [r.rule_id for ev in result.events for r in ev.rules]


@pytest.fixture
def state():
    case = make_case((item("P1"), item("P2", cost=50.0), item("D1", D, support={"e1": -0.5})), budget=5.0)
    st = ProcedureState(case)
    st.enter(Phase.PROSECUTION_CASE)
    return st


@pytest.mark.parametrize(
    ("action", "rule"),
    [
        (Action(actor=D, type=ActionType.PRESENT_EVIDENCE, evidence_id="D1"), "V-TURN"),
        (Action(actor=P, type=ActionType.OBJECT, ground=ObjectionGround.HEARSAY), "V-WINDOW"),
        (Action(actor=P, type=ActionType.MOTION_DIRECTED_VERDICT), "V-WINDOW"),
        (Action(actor=P, type=ActionType.PRESENT_EVIDENCE), "V-MISSING-FIELD"),
        (Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="GHOST"), "V-UNKNOWN-EVIDENCE"),
        (Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="D1"), "V-NOT-OWNER"),
        (Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="P2"), "V-BUDGET"),
        (Action(actor=P, type=ActionType.IMPEACH, evidence_id="P1", witness_id="W"), "V-IMPEACH-TARGET"),
    ],
)
def test_validator_rule_table(state, action: Action, rule: str) -> None:
    v = validate(action, state, P, "primary")
    assert v is not None and v.rule_id == rule


def test_duplicate_presentation(state) -> None:
    state.presented.append("P1")
    v = validate(Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="P1"), state, P, "primary")
    assert v is not None and v.rule_id == "V-DUPLICATE"


def test_objection_must_target_pending_item(state) -> None:
    state.pending = "P1"
    bad = Action(actor=D, type=ActionType.OBJECT, ground=ObjectionGround.HEARSAY, evidence_id="P2")
    assert validate(bad, state, D, "response").rule_id == "V-OBJ-TARGET"  # type: ignore[union-attr]
    good = Action(actor=D, type=ActionType.OBJECT, ground=ObjectionGround.HEARSAY)
    assert validate(good, state, D, "response") is None


def test_objection_to_an_objection_is_structurally_impossible(state) -> None:
    """After a ruling the window closes; the next actor is the lead in a primary window."""
    state.pending = "P1"
    assert state.expected() == (D, "response")
    state.pending = None
    assert state.expected() == (P, "primary")
    # an OBJECT in a primary window is a violation, never a new response window
    assert (
        validate(Action(actor=P, type=ActionType.OBJECT, ground=ObjectionGround.HEARSAY), state, P, "primary").rule_id
        == "V-WINDOW"
    )  # type: ignore[union-attr]


def test_rebuttal_scope(state) -> None:
    state.enter(Phase.REBUTTAL)
    v = validate(Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="P1"), state, P, "primary")
    assert v is not None and v.rule_id == "V-REBUTTAL-SCOPE"


def test_three_violations_trigger_contempt() -> None:
    """Interleaving legal moves defeats the stall rule, so contempt must catch the pattern."""
    case = CASES["helix-espionage"]
    junk = Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="GHOST")
    legal = [Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id=e) for e in ("P-VPN", "P-BADGE", "P-CCTV")]
    defense_passes = [Action(actor=D, type=ActionType.PASS)] * 3
    script = [junk, legal[0], junk, legal[1], junk, legal[2]]
    result = Court(case, ScriptedAgent(script), ScriptedAgent(defense_passes), seed=0).run()
    fired = rules_fired(result)
    assert fired.count("V-UNKNOWN-EVIDENCE") == 3
    assert "CONTEMPT-1" in fired
    assert result.ledgers[P].violations == 3 and result.ledgers[P].sanctions >= 3
    assert result.ledgers[P].presented == 2  # contempt ended the case before the third legal offer


def test_consecutive_passes_deemed_rest() -> None:
    case = CASES["helix-espionage"]
    passes = [Action(actor=P, type=ActionType.PASS)] * 10
    result = Court(case, ScriptedAgent(passes), CounselAgent(CONSERVATIVE), seed=0).run()
    assert "STALL-1" in rules_fired(result)
    assert result.verdict.outcome.value == "directed_acquittal"


def test_turn_cap_forces_rest() -> None:
    case = make_case(tuple(item(f"P{i}", support={"e1": 0.2}) for i in range(6)), max_primary_turns=2, budget=50)
    result = Court(case, CounselAgent(AGGRESSIVE), CounselAgent(CONSERVATIVE), seed=0).run()
    assert "TURN-CAP" in rules_fired(result)
    assert result.ledgers[P].presented == 2


def test_budget_never_negative_even_when_fined() -> None:
    case = make_case((item("P1"),), budget=0.5)
    junk = [Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="P1")] * 3
    result = Court(case, ScriptedAgent(junk), CounselAgent(CONSERVATIVE), seed=0).run()
    assert result.ledgers[P].budget >= 0
    assert "V-BUDGET" in rules_fired(result)


def test_every_phase_sequence_is_legal() -> None:
    legal = {
        Phase.OPENING: {Phase.PROSECUTION_CASE},
        Phase.PROSECUTION_CASE: {Phase.DIRECTED_VERDICT_REVIEW},
        Phase.DIRECTED_VERDICT_REVIEW: {Phase.DEFENSE_CASE, Phase.DELIBERATION},
        Phase.DEFENSE_CASE: {Phase.REBUTTAL, Phase.DELIBERATION},
        Phase.REBUTTAL: {Phase.DELIBERATION},
    }
    for case in CASES.values():
        for p in ("aggressive", "conservative", "chaos"):
            from courtroom.engine import run_trial

            r = run_trial(case, p, "chaos", seed=3)
            phases = [ev.phase for ev in r.events if ev.kind is EventKind.PHASE_CHANGE]
            for a, b in itertools.pairwise(phases):
                assert b in legal[a], f"{case.id}: illegal transition {a} -> {b}"


def test_scripted_objection_flow_sustained_and_sanctioned() -> None:
    case = make_case((item("P1", lawfully_obtained=False, support={"e1": 0.9}),))
    pros = ScriptedAgent([Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="P1")])
    defense = ScriptedAgent([Action(actor=D, type=ActionType.OBJECT, ground=ObjectionGround.ILLEGALLY_OBTAINED)])
    r = Court(case, pros, defense, seed=0).run()
    fired = rules_fired(r)
    assert "OBJ-EXCLUSIONARY" in fired and "SANCTION-BF" in fired
    assert r.ledgers[P].excluded == 1 and r.ledgers[P].sanctions == 2.0
    assert r.verdict.outcome.value == "directed_acquittal"


def test_overruled_objection_costs_objector() -> None:
    case = make_case((item("P1", support={"e1": 0.9}),))
    pros = ScriptedAgent([Action(actor=P, type=ActionType.PRESENT_EVIDENCE, evidence_id="P1")])
    defense = ScriptedAgent([Action(actor=D, type=ActionType.OBJECT, ground=ObjectionGround.HEARSAY)])
    r = Court(case, pros, defense, seed=0).run()
    assert "SANCTION-OVR" in rules_fired(r)
    assert r.ledgers[D].overruled == 1 and r.ledgers[D].sanctions == 0.25
    assert "P1" in [n.id for n in r.graph.nodes if n.status == "admitted"]


def test_rng_isolation_between_trials() -> None:
    case = CASES["helix-espionage"]
    a = Court(case, CounselAgent(AGGRESSIVE), CounselAgent(AGGRESSIVE), seed=1).run()
    random.seed(12345)  # global RNG must not influence outcomes
    b = Court(case, CounselAgent(AGGRESSIVE), CounselAgent(AGGRESSIVE), seed=1).run()
    assert a.digest == b.digest

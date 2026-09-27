"""Engineer 3: deterministic judge — admissibility, exact scoring, directed verdict, verdict."""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from courtroom.cases import CASES, generate_case
from courtroom.contracts import CaseType, EvidenceKind, ObjectionGround, Side, StandardOfProof, VerdictOutcome, Witness
from courtroom.judge import Judge, score_record, valid_grounds
from courtroom.judge.rules import PRIOR_LOG_ODDS, THRESHOLD_LOG_ODDS, q, threshold_met
from tests.conftest import item, make_case

# ----------------------------------------------------------------- numerics


def test_q_is_exact_decimal() -> None:
    assert q(0.7) == Fraction(7, 10)
    assert q(0.1) + q(0.2) == Fraction(3, 10)  # the classic float trap, avoided


def test_threshold_comparisons() -> None:
    brd = THRESHOLD_LOG_ODDS[StandardOfProof.BEYOND_REASONABLE_DOUBT]
    assert threshold_met(brd, StandardOfProof.BEYOND_REASONABLE_DOUBT)  # >= for criminal
    assert not threshold_met(Fraction(0), StandardOfProof.PREPONDERANCE)  # strict > for civil
    assert threshold_met(Fraction(1, 10**9), StandardOfProof.PREPONDERANCE)


# ----------------------------------------------------------------- admissibility


@pytest.mark.parametrize(
    ("kwargs", "ground"),
    [
        ({"hearsay": True}, ObjectionGround.HEARSAY),
        ({"authenticated": False}, ObjectionGround.AUTHENTICATION),
        ({"lawfully_obtained": False}, ObjectionGround.ILLEGALLY_OBTAINED),
        ({"disclosed": False}, ObjectionGround.LATE_DISCLOSURE),
        ({"support": {"e1": 0.04}}, ObjectionGround.RELEVANCE),
    ],
)
def test_each_objection_ground(kwargs: dict, ground: ObjectionGround) -> None:
    it = item("P1", **kwargs)
    assert valid_grounds(it, CaseType.CRIMINAL) == (ground,)


def test_clean_item_has_no_valid_grounds() -> None:
    assert valid_grounds(item("P1"), CaseType.CRIMINAL) == ()


def test_speculation_only_for_testimony() -> None:
    doc = item("P1", personal_knowledge=False)
    testimony = item("P2", kind=EvidenceKind.TESTIMONY, witness_id="W", personal_knowledge=False)
    assert ObjectionGround.SPECULATION not in valid_grounds(doc, CaseType.CRIMINAL)
    assert ObjectionGround.SPECULATION in valid_grounds(testimony, CaseType.CRIMINAL)


def test_exclusionary_rule_binds_only_the_state_in_criminal_cases() -> None:
    p = item("P1", lawfully_obtained=False)
    d = item("D1", Side.DEFENSE, lawfully_obtained=False)
    assert ObjectionGround.ILLEGALLY_OBTAINED in valid_grounds(p, CaseType.CRIMINAL)
    assert ObjectionGround.ILLEGALLY_OBTAINED not in valid_grounds(d, CaseType.CRIMINAL)
    assert ObjectionGround.ILLEGALLY_OBTAINED not in valid_grounds(p, CaseType.CIVIL)


# ----------------------------------------------------------------- scoring


def test_zero_evidence_is_prior_only() -> None:
    case = CASES["edge-empty-docket"]
    scores = score_record(case, [])
    assert all(v == PRIOR_LOG_ODDS[CaseType.CRIMINAL] for v in scores.log_odds.values())
    assert not scores.snapshot.all_met


def test_single_perfect_item_cannot_convict_beyond_reasonable_doubt() -> None:
    case = make_case((item("P1", support={"e1": 1.0}, reliability=1.0),))
    lo = score_record(case, ["P1"]).log_odds["e1"]
    assert lo == Fraction(2)  # -1 prior + 3 * 1
    assert lo < THRESHOLD_LOG_ODDS[StandardOfProof.BEYOND_REASONABLE_DOUBT]


def test_threshold_exactly_met_and_barely_missed() -> None:
    # Two independent items, corroboration 5/4 each: L = -1 + 2 * 3 * (s*r*5/4) = -1 + 7.5*s*r.
    # s*r = 0.28 gives L = 11/10 exactly (clear-and-convincing threshold).
    std = StandardOfProof.CLEAR_AND_CONVINCING
    exact = make_case(
        (item("A", support={"e1": 0.4}, reliability=0.7), item("B", support={"e1": 0.4}, reliability=0.7)), standard=std
    )
    lo = score_record(exact, ["A", "B"]).log_odds["e1"]
    assert lo == Fraction(11, 10)
    assert Judge(exact).deliberate(["A", "B"], {}).outcome is VerdictOutcome.GUILTY
    shy = make_case(
        (item("A", support={"e1": 0.4}, reliability=0.6999), item("B", support={"e1": 0.4}, reliability=0.7)), standard=std
    )
    assert Judge(shy).deliberate(["A", "B"], {}).outcome is VerdictOutcome.NOT_GUILTY


def test_permutation_invariance(simple_case) -> None:
    ids = ["P1", "P2", "D1"]
    base = score_record(simple_case, ids).log_odds
    rng = random.Random(0)
    for _ in range(20):
        rng.shuffle(ids)
        assert score_record(simple_case, list(ids)).log_odds == base
    reordered = simple_case.model_copy(update={"evidence": tuple(reversed(simple_case.evidence))})
    assert score_record(reordered, ids).log_odds == base


@pytest.mark.parametrize("seed", range(60))
def test_monotonicity_of_non_contradicting_support(seed: int) -> None:
    """Admitting a positive, non-contradicting item never lowers any element's log-odds."""
    case = generate_case(seed, contradiction_rate=0.0)
    rng = random.Random(seed)
    ids = [e.id for e in case.evidence]
    admitted = [i for i in ids if rng.random() < 0.5]
    before = score_record(case, admitted).log_odds
    for cand in case.evidence:
        if cand.id in admitted or any(v < 0 for v in cand.support.values()):
            continue
        after = score_record(case, [*admitted, cand.id]).log_odds
        assert all(after[e] >= before[e] for e in before), cand.id


def test_symmetric_contradiction_cancels_exactly() -> None:
    case = CASES["edge-mutual-exclusion"]
    scores = score_record(case, ["P-A", "D-B"])
    assert scores.log_odds["command"] == 0  # perfectly symmetric -> exactly zero
    assert Judge(case).deliberate(["P-A", "D-B"], {}).outcome is VerdictOutcome.NOT_LIABLE  # strict preponderance


def test_contradiction_discounts_the_weaker_item_more() -> None:
    case = make_case(
        (
            item("S", support={"e1": 0.8}, reliability=0.9, contradicts=("W",)),
            item("W", Side.DEFENSE, support={"e1": -0.8}, reliability=0.3),
        )
    )
    contrib = {c.evidence_id: c for c in score_record(case, ["S", "W"]).snapshot.elements[0].contributions}
    assert contrib["W"].contradiction_discount > contrib["S"].contradiction_discount


def test_cumulative_evidence_counts_a_fact_once() -> None:
    case = CASES["aurora-defi"]
    one = score_record(case, ["P-TXS"]).log_odds["execution"]
    both = score_record(case, ["P-TXS", "P-TXS-DUP"]).log_odds["execution"]
    assert one == both


def test_corroboration_bonus_is_bounded() -> None:
    items = tuple(item(f"P{i}", support={"e1": 0.1}, reliability=1.0) for i in range(30))
    case = make_case(items)
    contribs = score_record(case, [i.id for i in items]).snapshot.elements[0].contributions
    assert all(c.corroboration_factor < 1.5 for c in contribs)


def test_impeachment_halves_witness_credibility() -> None:
    case = make_case(
        (item("T", kind=EvidenceKind.TESTIMONY, witness_id="W", support={"e1": 0.8}),),
        witnesses=(Witness(id="W", name="w", role="r", credibility=0.8),),
    )
    base = score_record(case, ["T"]).log_odds["e1"]
    once = score_record(case, ["T"], {"W": 1}).log_odds["e1"]
    assert once - PRIOR_LOG_ODDS[CaseType.CRIMINAL] == (base - PRIOR_LOG_ODDS[CaseType.CRIMINAL]) / 2


# ----------------------------------------------------------------- directed verdict & verdict


def test_dv2_fires_sua_sponte_without_supporting_evidence() -> None:
    judge = Judge(CASES["edge-defense-only"])
    granted, element, rules = judge.directed_verdict_review([], {}, moved=False)
    assert granted and element == "trade" and rules[-1].rule_id == "DV-2"


def test_dv1_requires_motion() -> None:
    case = make_case((item("P1", support={"e1": 0.1}, reliability=0.5), item("D1", Side.DEFENSE, support={"e1": -0.9})))
    judge = Judge(case)
    assert judge.directed_verdict_review(["P1", "D1"], {}, moved=False)[0] is False
    granted, _, rules = judge.directed_verdict_review(["P1", "D1"], {}, moved=True)
    assert granted and rules[-1].rule_id == "DV-1"


def test_conjunctive_element_test() -> None:
    case = make_case(
        (*(item(f"A{i}", support={"a": 1.0}) for i in range(3)), item("B0", support={"b": 0.2})),
        elements=("a", "b"),
    )
    v = Judge(case).deliberate(["A0", "A1", "A2", "B0"], {})
    assert v.outcome is VerdictOutcome.NOT_GUILTY and v.decisive_element == "b"


def test_judge_is_pure(simple_case) -> None:
    j = Judge(simple_case)
    assert j.deliberate(["P1", "P2"], {}) == j.deliberate(["P2", "P1"], {})

"""Engineer 1: data contracts, case library, generator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from courtroom.cases import CASES, generate_case
from courtroom.contracts import EvidenceKind, Side
from tests.conftest import item, make_case


def test_library_cases_are_valid_and_synthetic() -> None:
    assert {"helix-espionage", "aurora-defi", "kestrel-av", "edge-empty-docket"} <= set(CASES)
    for case in CASES.values():
        assert case.synopsis
        assert all(-1 <= v <= 1 for e in case.evidence for v in e.support.values())


def test_unknown_element_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown elements"):
        make_case((item("P1", support={"nope": 0.5}),))


def test_duplicate_evidence_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate evidence"):
        make_case((item("P1"), item("P1")))


def test_dangling_contradiction_rejected() -> None:
    with pytest.raises(ValidationError, match="contradicts invalid"):
        make_case((item("P1", contradicts=("GHOST",)),))


def test_self_contradiction_rejected() -> None:
    with pytest.raises(ValidationError, match="contradicts invalid"):
        make_case((item("P1", contradicts=("P1",)),))


def test_testimony_requires_witness() -> None:
    with pytest.raises(ValidationError, match="must reference a witness"):
        item("T1", kind=EvidenceKind.TESTIMONY)


def test_judge_inputs_must_be_exact_decimals() -> None:
    with pytest.raises(ValidationError, match="4 decimals"):
        item("P1", reliability=0.123456)


def test_support_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        item("P1", support={"e1": 1.5})


def test_contracts_are_frozen() -> None:
    it = item("P1")
    with pytest.raises(ValidationError):
        it.reliability = 0.1  # type: ignore[misc]


def test_contradiction_edges_symmetric_and_deduplicated() -> None:
    case = make_case((item("A", contradicts=("B",)), item("B", Side.DEFENSE, contradicts=("A",))))
    assert case.contradiction_edges() == [("A", "B")]


@pytest.mark.parametrize("seed", range(150))
def test_generator_produces_valid_deterministic_cases(seed: int) -> None:
    a, b = generate_case(seed), generate_case(seed)
    assert a == b
    assert a.id == f"gen-{seed}"
    for e in a.evidence:
        assert e.owner in (Side.PROSECUTION, Side.DEFENSE)

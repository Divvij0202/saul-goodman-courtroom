from __future__ import annotations

from typing import Any

import pytest

from courtroom.contracts import (
    CaseFile,
    CaseType,
    EvidenceItem,
    EvidenceKind,
    LegalElement,
    Side,
    StandardOfProof,
    Witness,
)


def item(
    id: str, owner: Side = Side.PROSECUTION, support: dict[str, float] | None = None, reliability: float = 1.0, **kw: Any
) -> EvidenceItem:
    return EvidenceItem(
        id=id,
        title=kw.pop("title", id),
        description=kw.pop("description", id),
        kind=kw.pop("kind", EvidenceKind.DOCUMENT),
        owner=owner,
        fact_id=kw.pop("fact_id", id),
        support=support if support is not None else {"e1": 1.0},
        reliability=reliability,
        **kw,
    )


def make_case(
    evidence: tuple[EvidenceItem, ...] = (),
    *,
    case_type: CaseType = CaseType.CRIMINAL,
    standard: StandardOfProof = StandardOfProof.BEYOND_REASONABLE_DOUBT,
    elements: tuple[str, ...] = ("e1",),
    witnesses: tuple[Witness, ...] = (),
    **kw: Any,
) -> CaseFile:
    return CaseFile(
        id=kw.pop("id", "t-case"),
        title="Test case",
        synopsis="Synthetic unit-test case.",
        case_type=case_type,
        standard=standard,
        charge="test",
        elements=tuple(LegalElement(id=e, name=e, description=e) for e in elements),
        witnesses=witnesses,
        evidence=evidence,
        **kw,
    )


@pytest.fixture
def simple_case() -> CaseFile:
    return make_case(
        (
            item("P1", support={"e1": 0.8}, reliability=0.9),
            item("P2", support={"e1": 0.6}, reliability=0.8),
            item("D1", Side.DEFENSE, support={"e1": -0.5}, reliability=0.9, contradicts=("P1",)),
        )
    )

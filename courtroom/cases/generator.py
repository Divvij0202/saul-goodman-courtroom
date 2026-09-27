"""Procedural synthetic case generator for Monte-Carlo stress and fuzz testing.

Owner: Engineer 1. Deterministic in ``seed``. Produces valid ``CaseFile`` objects
spanning the full parameter space, including degenerate corners (no evidence,
dense contradiction graphs, every item defective).
"""

from __future__ import annotations

import random

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

_THEMES = (
    ("satellite telemetry spoofing", ("spoofing", "control", "harm")),
    ("smart-contract governance capture", ("vote_buying", "proposal_control", "loss")),
    ("warehouse robot sabotage", ("tampering", "identity", "damage")),
    ("biometric data broker leak", ("collection", "sale", "consent_absent")),
    ("quantum-key escrow breach", ("access", "copying", "intent")),
)


def _dec(x: float) -> float:
    return round(x, 2)


def generate_case(
    seed: int,
    n_elements: int | None = None,
    n_prosecution: int | None = None,
    n_defense: int | None = None,
    defect_rate: float | None = None,
    contradiction_rate: float | None = None,
) -> CaseFile:
    rng = random.Random(f"case-gen:{seed}")
    theme, element_names = rng.choice(_THEMES)
    n_el = n_elements if n_elements is not None else rng.randint(1, 3)
    n_p = n_prosecution if n_prosecution is not None else rng.randint(0, 9)
    n_d = n_defense if n_defense is not None else rng.randint(0, 7)
    p_defect = defect_rate if defect_rate is not None else rng.choice((0.0, 0.2, 0.4, 0.9))
    p_contra = contradiction_rate if contradiction_rate is not None else rng.choice((0.0, 0.1, 0.3))
    case_type = rng.choice(list(CaseType))
    standard = (
        rng.choice((StandardOfProof.BEYOND_REASONABLE_DOUBT, StandardOfProof.CLEAR_AND_CONVINCING))
        if case_type is CaseType.CRIMINAL
        else StandardOfProof.PREPONDERANCE
    )

    elements = tuple(
        LegalElement(
            id=element_names[i % len(element_names)] + ("" if i < len(element_names) else f"_{i}"),
            name=element_names[i % len(element_names)].replace("_", " ").title(),
            description=f"Element {i + 1} of the {theme} charge.",
        )
        for i in range(n_el)
    )
    witnesses: list[Witness] = []
    items: list[EvidenceItem] = []
    n_facts = max(1, (n_p + n_d) * 3 // 4)

    for idx in range(n_p + n_d):
        owner = Side.PROSECUTION if idx < n_p else Side.DEFENSE
        sign = 1 if owner is Side.PROSECUTION else -1
        kind = rng.choice(list(EvidenceKind))
        k = rng.randint(1, n_el)
        targets = rng.sample([e.id for e in elements], k)
        support = {t: _dec(sign * rng.uniform(0.05, 1.0)) for t in targets}
        if rng.random() < 0.08:  # occasional irrelevant or self-defeating item
            support = {targets[0]: _dec(rng.uniform(-0.04, 0.04))}
        witness_id = None
        if kind is EvidenceKind.TESTIMONY:
            witness_id = f"W{idx}"
            witnesses.append(
                Witness(id=witness_id, name=f"Witness {idx}", role="Synthetic", credibility=_dec(rng.uniform(0.3, 1.0)))
            )
        items.append(
            EvidenceItem(
                id=f"{owner.value[0].upper()}{idx}",
                title=f"Synthetic {kind.value.replace('_', ' ')} #{idx}",
                description=f"Procedurally generated exhibit for {theme}.",
                kind=kind,
                owner=owner,
                fact_id=f"F{rng.randrange(n_facts)}",
                support=support,
                reliability=_dec(rng.uniform(0.2, 1.0)),
                witness_id=witness_id,
                hearsay=rng.random() < p_defect / 2,
                authenticated=rng.random() >= p_defect / 2,
                lawfully_obtained=rng.random() >= p_defect / 2,
                disclosed=rng.random() >= p_defect / 3,
                personal_knowledge=rng.random() >= p_defect / 3,
            )
        )

    # Contradictions (between opposing items) and impeachment links.
    ids = [i.id for i in items]
    contra: dict[str, list[str]] = {i: [] for i in ids}
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if items[a].owner is not items[b].owner and rng.random() < p_contra:
                contra[items[a].id].append(items[b].id)
    witness_ids = [w.id for w in witnesses]
    final: list[EvidenceItem] = []
    for item in items:
        opposing_witnesses = [w for w in witness_ids if any(o.witness_id == w and o.owner is not item.owner for o in items)]
        impeaches = tuple(rng.sample(opposing_witnesses, 1)) if opposing_witnesses and rng.random() < 0.15 else ()
        final.append(item.model_copy(update={"contradicts": tuple(contra[item.id]), "impeaches": impeaches}))

    return CaseFile(
        id=f"gen-{seed}",
        title=f"Generated case #{seed}: {theme}",
        synopsis=f"Procedurally generated {case_type.value} case about {theme}.",
        case_type=case_type,
        standard=standard,
        charge=theme,
        elements=elements,
        witnesses=tuple(witnesses),
        evidence=tuple(final),
        budget=float(rng.choice((4, 8, 12))),
        max_primary_turns=rng.randint(1, 10),
        rebuttal_turns=rng.randint(0, 3),
        perception_accuracy=rng.choice((0.5, 0.8, 1.0)),
        tags=("generated",),
    )

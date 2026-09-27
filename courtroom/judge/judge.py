"""The deterministic judge: rulings, directed verdict, deliberation.

Owner: Engineer 3. Stateless: every method is a pure function of its arguments.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from courtroom.contracts import (
    CaseFile,
    CaseType,
    EvidenceItem,
    ObjectionGround,
    RuleFiring,
    Verdict,
    VerdictOutcome,
)
from courtroom.judge.admissibility import rule_on_objection
from courtroom.judge.rules import (
    DIRECTED_VERDICT_THRESHOLD,
    THRESHOLD_LOG_ODDS,
    ZERO,
    fmt,
    q,
)
from courtroom.judge.scoring import ExactScores, score_record


class Judge:
    """Rule engine. Holds only the (immutable) case file."""

    def __init__(self, case: CaseFile) -> None:
        self.case = case

    # ------------------------------------------------------------------ rulings

    def rule_on_objection(self, item: EvidenceItem, ground: ObjectionGround) -> tuple[bool, RuleFiring]:
        return rule_on_objection(item, ground, self.case)

    def rule_on_impeachment(self, impeaching: EvidenceItem, witness_id: str) -> tuple[bool, RuleFiring]:
        ok = witness_id in impeaching.impeaches
        return ok, RuleFiring(
            rule_id="IMP-1",
            detail=(
                f"{impeaching.id} {'impeaches' if ok else 'does not bear on the credibility of'} "
                f"witness {witness_id}; credibility {'halved' if ok else 'unchanged'}."
            ),
        )

    def score(self, admitted: Iterable[str], impeachments: Mapping[str, int]) -> ExactScores:
        return score_record(self.case, admitted, impeachments)

    # ------------------------------------------------------------------ directed verdict

    def directed_verdict_review(
        self, admitted: Iterable[str], impeachments: Mapping[str, int], moved: bool
    ) -> tuple[bool, str | None, list[RuleFiring]]:
        """Return (granted, failing element, rules fired). DV-2 always runs; DV-1 only on motion."""
        admitted = tuple(admitted)
        scores = self.score(admitted, impeachments)
        rules: list[RuleFiring] = []

        for element in self.case.elements:
            has_positive = any(
                (item := self.case.item(i)) is not None and q(item.support.get(element.id, 0.0)) > ZERO for i in admitted
            )
            if not has_positive:
                rules.append(
                    RuleFiring(
                        rule_id="DV-2",
                        detail=f"No admitted evidence supports element '{element.id}'. Directed acquittal sua sponte.",
                    )
                )
                return True, element.id, rules
        rules.append(RuleFiring(rule_id="DV-2", detail="Every element has some admitted supporting evidence."))

        if moved:
            for element in self.case.elements:
                lo = scores.log_odds[element.id]
                if lo < DIRECTED_VERDICT_THRESHOLD:
                    rules.append(
                        RuleFiring(
                            rule_id="DV-1",
                            detail=(
                                f"Element '{element.id}' log-odds {fmt(lo)} < {fmt(DIRECTED_VERDICT_THRESHOLD)}: "
                                "no reasonable fact-finder could find it proven. Motion GRANTED."
                            ),
                        )
                    )
                    return True, element.id, rules
            rules.append(RuleFiring(rule_id="DV-1", detail="All elements at or above log-odds 0. Motion DENIED."))
        return False, None, rules

    # ------------------------------------------------------------------ verdict

    def deliberate(
        self,
        admitted: Iterable[str],
        impeachments: Mapping[str, int],
        directed: tuple[bool, str | None] = (False, None),
    ) -> Verdict:
        scores = self.score(admitted, impeachments)
        snap = scores.snapshot
        tau = THRESHOLD_LOG_ODDS[self.case.standard]
        rules = [
            RuleFiring(
                rule_id="STD-1",
                detail=f"Standard: {self.case.standard.value}; threshold log-odds {fmt(tau)}.",
            )
        ]
        for es in snap.elements:
            rules.append(
                RuleFiring(
                    rule_id="ELEM-1",
                    detail=f"Element '{es.element_id}': log-odds {es.log_odds} vs {es.threshold} -> {'MET' if es.met else 'NOT MET'}.",
                )
            )

        criminal = self.case.case_type is CaseType.CRIMINAL
        granted, failing = directed
        if granted:
            rules.append(RuleFiring(rule_id="VER-DV", detail="Judgment entered on the directed verdict."))
            return Verdict(
                outcome=VerdictOutcome.DIRECTED_ACQUITTAL,
                reason=f"Directed verdict: prosecution failed to make a prima facie case on '{failing}'.",
                decisive_element=failing,
                snapshot=snap,
                rules=tuple(rules),
            )
        if snap.all_met:
            outcome = VerdictOutcome.GUILTY if criminal else VerdictOutcome.LIABLE
            rules.append(RuleFiring(rule_id="VER-1", detail="Every element met the standard (conjunctive test)."))
            return Verdict(
                outcome=outcome,
                reason=f"All {len(snap.elements)} elements proven to the {self.case.standard.value} standard.",
                decisive_element=snap.weakest_element,
                snapshot=snap,
                rules=tuple(rules),
            )
        outcome = VerdictOutcome.NOT_GUILTY if criminal else VerdictOutcome.NOT_LIABLE
        failing_el = next(es for es in snap.elements if not es.met)
        rules.append(RuleFiring(rule_id="VER-2", detail=f"Element '{failing_el.element_id}' not proven. Burden not carried."))
        return Verdict(
            outcome=outcome,
            reason=f"Element '{failing_el.element_id}' not proven to the {self.case.standard.value} standard.",
            decisive_element=failing_el.element_id,
            snapshot=snap,
            rules=tuple(rules),
        )

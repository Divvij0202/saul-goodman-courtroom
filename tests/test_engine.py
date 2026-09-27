"""Engineer 6: orchestration, determinism, audit chain, fault isolation."""

from __future__ import annotations

import itertools

import pytest

from courtroom.agents import CONSERVATIVE, CounselAgent
from courtroom.cases import CASES
from courtroom.contracts import Side, VerdictOutcome
from courtroom.engine import WIN_VALUE, Court, run_trial, verify_chain
from courtroom.engine import trial as trial_module

STRATS = ("aggressive", "conservative", "adaptive", "chaos", "mixed:0.5")


@pytest.mark.parametrize(("case_id", "p", "d"), [(c, p, d) for c in CASES for p, d in itertools.product(STRATS, STRATS)])
def test_every_library_case_and_pairing_terminates_cleanly(case_id: str, p: str, d: str) -> None:
    r = run_trial(CASES[case_id], p, d, seed=11)
    assert r.verdict.outcome in VerdictOutcome
    assert verify_chain(r.events)
    assert r.events[-1].kind.value == "verdict"


def test_bit_for_bit_determinism() -> None:
    case = CASES["helix-espionage"]
    for seed in range(5):
        a = run_trial(case, "adaptive", "aggressive", seed)
        b = run_trial(case, "adaptive", "aggressive", seed)
        assert a.model_dump_json() == b.model_dump_json()


def test_seed_changes_stochastic_outcomes() -> None:
    case = CASES["helix-espionage"]
    digests = {run_trial(case, "aggressive", "aggressive", s).digest for s in range(10)}
    assert len(digests) > 1


def test_tampering_breaks_the_chain() -> None:
    r = run_trial(CASES["helix-espionage"], "aggressive", "conservative", 0)
    events = list(r.events)
    events[5] = events[5].model_copy(update={"summary": "the defense concedes everything"})
    assert not verify_chain(events)


@pytest.mark.parametrize("case_id", ["edge-empty-docket", "edge-defense-only"])
def test_no_inculpatory_evidence_means_directed_acquittal(case_id: str) -> None:
    for p, d in itertools.product(STRATS, STRATS):
        assert run_trial(CASES[case_id], p, d, 0).verdict.outcome is VerdictOutcome.DIRECTED_ACQUITTAL


class Crasher:
    name = "crasher"

    def opening_statement(self, side: Side) -> str:
        raise RuntimeError("boom")

    def act(self, view, oracle):
        raise RuntimeError("agent exploded")


class WrongType:
    name = "wrong-type"

    def opening_statement(self, side: Side) -> str:
        return "..."

    def act(self, view, oracle):
        return {"type": "present_evidence"}


def test_crashing_agent_is_contained() -> None:
    """Crashes in opening_statement() and act() must both be absorbed."""
    result = Court(CASES["helix-espionage"], CounselAgent(CONSERVATIVE), Crasher(), seed=0).run()  # type: ignore[arg-type]
    fired = [ru.rule_id for ev in result.events for ru in ev.rules]
    assert "V-AGENT-FAULT" in fired
    assert "no opening statement" in result.events[0].summary
    assert verify_chain(result.events)


def test_non_action_return_is_a_violation() -> None:
    court = Court(CASES["helix-espionage"], WrongType(), CounselAgent(CONSERVATIVE), seed=0)  # type: ignore[arg-type]
    result = court.run()
    # Each malformed return is a violation treated as PASS; two in a row trip the stall rule.
    assert result.ledgers[Side.PROSECUTION].violations == 2
    assert "STALL-1" in [ru.rule_id for ev in result.events for ru in ev.rules]
    assert result.verdict.outcome is VerdictOutcome.DIRECTED_ACQUITTAL


def test_watchdog_caps_trial_length(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "MAX_EVENTS", 12)
    r = run_trial(CASES["helix-espionage"], "aggressive", "aggressive", 0)
    assert any(ev.kind.value == "watchdog" for ev in r.events)
    assert r.events[-1].kind.value == "verdict"


def test_utilities_formula() -> None:
    r = run_trial(CASES["helix-espionage"], "aggressive", "conservative", 0)
    for side in Side:
        lg = r.ledgers[side]
        won = r.verdict.outcome.favours is side
        assert r.utilities[side] == pytest.approx(WIN_VALUE * won - 0.3 * lg.spent - 1.0 * lg.sanctions)


def test_graph_statuses_consistent_with_events() -> None:
    r = run_trial(CASES["helix-espionage"], "aggressive", "aggressive", 2)
    final = {}
    for ev in r.events:
        if ev.subject and ev.status in ("admitted", "excluded"):
            final[ev.subject] = ev.status
    for node in r.graph.nodes:
        assert node.status == final.get(node.id, "unpresented")

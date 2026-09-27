"""Trial orchestrator: drives agents through the procedure FSM and records everything.

Owner: Engineer 6.

Robustness guarantees (all covered by tests):
* No exception raised by an agent escapes; it becomes violation V-AGENT-FAULT.
* Every loop iteration either consumes a primary turn, closes a response or
  motion window, or changes phase, so the trial always terminates. A global
  event cap (WATCHDOG) backs this up.
* Identical (case, strategies, seed) inputs produce an identical event hash chain.
"""

from __future__ import annotations

import math
import random

from courtroom.agents import Agent, Oracle, ScoreCache, make_agent, perceive
from courtroom.contracts import (
    Action,
    ActionType,
    CaseFile,
    EventKind,
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    PartyView,
    PerceivedItem,
    Phase,
    RuleFiring,
    Side,
    TrialEvent,
    TrialResult,
    Verdict,
    Window,
)
from courtroom.engine.audit import GENESIS, chain
from courtroom.engine.utility import utilities
from courtroom.judge import Judge
from courtroom.judge.admissibility import BAD_FAITH_GROUNDS
from courtroom.judge.rules import (
    CONTEMPT_VIOLATIONS,
    FINE_VIOLATION,
    IMPEACHMENT_COST,
    MOTION_COST,
    OBJECTION_COST,
    SANCTION_BAD_FAITH_EVIDENCE,
    SANCTION_OVERRULED_OBJECTION,
    SANCTION_VIOLATION,
    THRESHOLD_LOG_ODDS,
)
from courtroom.procedure import ProcedureState, Violation, validate
from courtroom.procedure.state import STALL_LIMIT
from courtroom.procedure.validator import VIOLATION_RULES

MAX_EVENTS = 400


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


class Court:
    def __init__(
        self,
        case: CaseFile,
        prosecution: Agent,
        defense: Agent,
        seed: int = 0,
        prosecution_strategy: str | None = None,
        defense_strategy: str | None = None,
    ) -> None:
        self.case = case
        self.agents: dict[Side, Agent] = {Side.PROSECUTION: prosecution, Side.DEFENSE: defense}
        self.strategy_names = {
            Side.PROSECUTION: prosecution_strategy or prosecution.name,
            Side.DEFENSE: defense_strategy or defense.name,
        }
        self.seed = seed
        self.judge = Judge(case)
        self.state = ProcedureState(case)
        self.cache = ScoreCache(case)
        self._perception_rng = random.Random(f"{seed}:perception")
        self._perceived: PerceivedItem | None = None
        self._events: list[TrialEvent] = []
        self._last_hash = GENESIS

    # ------------------------------------------------------------------ event plumbing

    def _probabilities(self) -> tuple[float, dict[str, float]]:
        lo = self.cache.log_odds(self.state.admitted, self.state.impeachments)
        probs = {k: round(_sigmoid(v), 6) for k, v in lo.items()}
        return min(probs.values()), probs

    def _emit(
        self,
        kind: EventKind,
        summary: str,
        actor: Side | None = None,
        action: Action | None = None,
        rules: tuple[RuleFiring, ...] | list[RuleFiring] = (),
        subject: str | None = None,
        status: str | None = None,
    ) -> None:
        burden, probs = self._probabilities()
        event = TrialEvent(
            seq=len(self._events),
            phase=self.state.phase,
            kind=kind,
            actor=actor,
            action=action,
            summary=summary,
            subject=subject,
            status=status,  # type: ignore[arg-type]
            rules=tuple(rules),
            burden_index=round(burden, 6),
            element_probabilities=probs,
        )
        event = chain(event, self._last_hash)
        self._last_hash = event.hash
        self._events.append(event)

    def _enter(self, phase: Phase, reason: str) -> None:
        self.state.enter(phase)
        self._emit(EventKind.PHASE_CHANGE, f"Phase -> {phase.value}. {reason}".strip())

    # ------------------------------------------------------------------ views

    def _view(self, side: Side, window: Window) -> PartyView:
        st = self.state
        opp = side.opponent
        own = tuple(i for i in self.case.evidence if i.owner is side)
        options = tuple(
            (item.id, w) for w in st.testified_witnesses(opp) for item in own if (item.id, w) not in st.used_impeachments
        )
        return PartyView(
            side=side,
            phase=st.phase,
            window=window,
            case_id=self.case.id,
            case_type=self.case.case_type,
            standard=self.case.standard,
            element_ids=tuple(e.id for e in self.case.elements),
            own_evidence=own,
            presented=tuple(st.presented),
            admitted=tuple(st.admitted),
            excluded=tuple(st.excluded),
            pending=self._perceived if window == "response" else None,
            snapshot=self.judge.score(st.admitted, st.impeachments).snapshot,
            budget=st.ledgers[side].budget,
            reserve_basis=st.ledgers[side].budget_start,
            opponent_budget=st.ledgers[opp].budget,
            turns_left=st.turns_left(),
            impeachment_options=options,
            rebuttal_targets=st.rebuttal_targets() if side is Side.PROSECUTION else (),
            opponent_objections=st.ledgers[opp].objections,
            opponent_response_windows=st.ledgers[opp].response_windows,
        )

    # ------------------------------------------------------------------ main loop

    def run(self) -> TrialResult:
        st = self.state
        opening = " | ".join(f"{s.value}: {self._opening(s)}" for s in Side)
        self._emit(EventKind.PHASE_CHANGE, f"Court is in session: {self.case.title}. {opening}")
        self._enter(Phase.PROSECUTION_CASE, "The prosecution may present its case.")

        while st.phase not in (Phase.DELIBERATION, Phase.CLOSED):
            if len(self._events) >= MAX_EVENTS:
                self._emit(
                    EventKind.WATCHDOG,
                    "Event cap reached; the court proceeds directly to deliberation.",
                    rules=[RuleFiring(rule_id="WATCHDOG-1", detail=f"{MAX_EVENTS} events exceeded.")],
                )
                st.enter(Phase.DELIBERATION)
                break
            side, window = st.expected()  # type: ignore[misc]
            if window == "primary" and st.turns_left() == 0:
                self._rest(side, RuleFiring(rule_id="TURN-CAP", detail=f"{side.value} exhausted its {st.turn_cap()} turns."))
                continue
            if window == "response":
                st.ledgers[side].response_windows += 1
            action, violation = self._solicit(side, window)
            if violation is not None:
                self._penalise(side, window, violation, action)
            else:
                assert action is not None
                self._dispatch(side, window, action)

        return self._deliberate()

    def _opening(self, side: Side) -> str:
        try:
            return str(self.agents[side].opening_statement(side))[:500]
        except Exception as exc:
            return f"(no opening statement: {type(exc).__name__})"

    def _solicit(self, side: Side, window: Window) -> tuple[Action | None, Violation | None]:
        view = self._view(side, window)
        oracle = Oracle(self.cache, self.state.admitted, self.state.impeachments)
        try:
            action = self.agents[side].act(view, oracle)
            if not isinstance(action, Action):
                raise TypeError(f"agent returned {type(action).__name__}, not Action")
        except Exception as exc:
            return None, Violation("V-AGENT-FAULT", f"{VIOLATION_RULES['V-AGENT-FAULT']} ({type(exc).__name__}: {exc})")
        return action, validate(action, self.state, side, window)

    # ------------------------------------------------------------------ penalties

    def _penalise(self, side: Side, window: Window, violation: Violation, action: Action | None) -> None:
        st = self.state
        ledger = st.ledgers[side]
        ledger.violations += 1
        ledger.sanctions += SANCTION_VIOLATION
        fine = ledger.charge(FINE_VIOLATION)
        self._emit(
            EventKind.VIOLATION,
            f"{side.value} committed a procedural violation; treated as PASS, fined {fine:g}.",
            actor=side,
            action=action,
            rules=[RuleFiring(rule_id=violation.rule_id, detail=violation.detail)],
        )
        if window == "response":
            self._admit_pending(waived=True)
        elif window == "motion":
            self._directed_verdict_review(moved=False)
        else:
            st.consume_primary_turn()
            st.consecutive_passes += 1
            if ledger.violations >= CONTEMPT_VIOLATIONS:
                self._rest(
                    side,
                    RuleFiring(
                        rule_id="CONTEMPT-1",
                        detail=f"{ledger.violations} violations: counsel held in contempt; case deemed rested.",
                    ),
                )
            elif st.consecutive_passes >= STALL_LIMIT:
                self._rest(side, RuleFiring(rule_id="STALL-1", detail="Consecutive passes deemed a rest."))

    # ------------------------------------------------------------------ dispatch

    def _dispatch(self, side: Side, window: Window, action: Action) -> None:
        st = self.state
        ledger = st.ledgers[side]
        match action.type:
            case ActionType.PRESENT_EVIDENCE:
                item = self.case.item(action.evidence_id)  # type: ignore[arg-type]
                assert item is not None
                ledger.charge(item.presentation_cost)
                ledger.presented += 1
                st.presented.append(item.id)
                st.pending = item.id
                st.consume_primary_turn()
                st.consecutive_passes = 0
                self._perceived = perceive(item, self.case, self._perception_rng)
                self._emit(
                    EventKind.ACTION,
                    f"{side.value} offers {item.id}: {item.title}.",
                    side,
                    action,
                    subject=item.id,
                    status="offered",
                )

            case ActionType.OBJECT:
                self._rule_on_objection(side, action)

            case ActionType.IMPEACH:
                item = self.case.item(action.evidence_id)  # type: ignore[arg-type]
                witness = action.witness_id
                assert item is not None and witness is not None
                ledger.charge(IMPEACHMENT_COST)
                st.used_impeachments.add((item.id, witness))
                st.consume_primary_turn()
                st.consecutive_passes = 0
                ok, rule = self.judge.rule_on_impeachment(item, witness)
                if ok:
                    st.impeachments[witness] = st.impeachments.get(witness, 0) + 1
                    ledger.impeachments += 1
                else:
                    ledger.sanctions += SANCTION_OVERRULED_OBJECTION
                self._emit(
                    EventKind.RULING,
                    f"{side.value} impeaches {witness} with {item.id}: {'effective' if ok else 'improper'}.",
                    side,
                    action,
                    [rule],
                    subject=witness,
                    status="impeached" if ok else None,
                )

            case ActionType.MOTION_DIRECTED_VERDICT:
                ledger.charge(MOTION_COST)
                st.motion_made = True
                self._emit(EventKind.ACTION, f"{side.value} moves for a directed verdict.", side, action)
                self._directed_verdict_review(moved=True)

            case ActionType.PASS:
                if window == "response":
                    self._emit(EventKind.ACTION, f"{side.value} does not object.", side, action)
                    self._admit_pending(waived=False)
                elif window == "motion":
                    self._emit(EventKind.ACTION, f"{side.value} makes no motion.", side, action)
                    self._directed_verdict_review(moved=False)
                else:
                    st.consume_primary_turn()
                    st.consecutive_passes += 1
                    self._emit(EventKind.ACTION, f"{side.value} passes.", side, action)
                    if st.consecutive_passes >= STALL_LIMIT:
                        self._rest(side, RuleFiring(rule_id="STALL-1", detail="Consecutive passes deemed a rest."))

            case ActionType.REST:
                self._emit(EventKind.ACTION, f"{side.value} rests.", side, action)
                self._rest(side, None)

    def _rule_on_objection(self, side: Side, action: Action) -> None:
        st = self.state
        item = self.case.item(st.pending)  # type: ignore[arg-type]
        assert item is not None and action.ground is not None
        objector = st.ledgers[side]
        presenter = st.ledgers[item.owner]
        objector.charge(OBJECTION_COST)
        objector.objections += 1
        sustained, rule = self.judge.rule_on_objection(item, action.ground)
        rules = [rule]
        if sustained:
            st.excluded.append(item.id)
            presenter.excluded += 1
            objector.sustained += 1
            if action.ground in BAD_FAITH_GROUNDS:
                presenter.sanctions += SANCTION_BAD_FAITH_EVIDENCE
                rules.append(
                    RuleFiring(
                        rule_id="SANCTION-BF", detail=f"{item.owner.value} sanctioned for offering {item.id} in bad faith."
                    )
                )
        else:
            st.admitted.append(item.id)
            presenter.admitted += 1
            objector.overruled += 1
            objector.sanctions += SANCTION_OVERRULED_OBJECTION
            rules.append(
                RuleFiring(
                    rule_id="SANCTION-OVR",
                    detail=f"Overruled objection costs {side.value} {SANCTION_OVERRULED_OBJECTION} sanction points.",
                )
            )
        st.pending = None
        self._perceived = None
        self._emit(
            EventKind.RULING,
            f"Objection ({action.ground.value}) by {side.value}: {'SUSTAINED, ' + item.id + ' excluded' if sustained else 'OVERRULED, ' + item.id + ' admitted'}.",
            side,
            action,
            rules,
            subject=item.id,
            status="excluded" if sustained else "admitted",
        )

    def _admit_pending(self, waived: bool) -> None:
        st = self.state
        if st.pending is None:
            return
        item = self.case.item(st.pending)
        assert item is not None
        st.admitted.append(item.id)
        st.ledgers[item.owner].admitted += 1
        st.pending = None
        self._perceived = None
        self._emit(
            EventKind.RULING,
            f"{item.id} admitted without objection.",
            rules=[RuleFiring(rule_id="ADM-WAIVER", detail=f"No (valid) objection to {item.id}; any defect is waived.")],
            subject=item.id,
            status="admitted",
        )

    def _rest(self, side: Side, forced: RuleFiring | None) -> None:
        st = self.state
        if st.pending is not None:  # defensive: never strand a pending item
            self._admit_pending(waived=True)
        if forced is not None:
            self._emit(EventKind.RULING, f"{side.value} is deemed to have rested.", side, rules=[forced])
        nxt = st.next_phase_after_rest()
        self._enter(nxt, f"{side.value} rested.")

    def _directed_verdict_review(self, moved: bool) -> None:
        st = self.state
        granted, element, rules = self.judge.directed_verdict_review(st.admitted, st.impeachments, moved)
        st.directed = (granted, element)
        self._emit(
            EventKind.DIRECTED_VERDICT,
            f"Directed verdict {'GRANTED on ' + str(element) if granted else 'denied'}.",
            rules=rules,
        )
        self._enter(Phase.DELIBERATION if granted else Phase.DEFENSE_CASE, "")

    # ------------------------------------------------------------------ verdict

    def _deliberate(self) -> TrialResult:
        st = self.state
        if st.phase is not Phase.DELIBERATION:
            st.enter(Phase.DELIBERATION)
        verdict: Verdict = self.judge.deliberate(st.admitted, st.impeachments, st.directed)
        self._emit(
            EventKind.VERDICT,
            f"VERDICT: {verdict.outcome.value.upper().replace('_', ' ')}. {verdict.reason}",
            rules=verdict.rules,
        )
        st.enter(Phase.CLOSED)
        ledgers = {s: st.ledgers[s].freeze() for s in Side}
        return TrialResult(
            case_id=self.case.id,
            case_title=self.case.title,
            seed=self.seed,
            prosecution_strategy=self.strategy_names[Side.PROSECUTION],
            defense_strategy=self.strategy_names[Side.DEFENSE],
            events=tuple(self._events),
            verdict=verdict,
            ledgers=ledgers,
            utilities=utilities(verdict.outcome, ledgers),
            digest=self._last_hash,
            graph=self._graph(verdict),
        )

    def _graph(self, verdict: Verdict) -> EvidenceGraph:
        st = self.state
        weight: dict[str, float] = {}
        for es in verdict.snapshot.elements:
            for c in es.contributions:
                if c.counted:
                    weight[c.evidence_id] = round(weight.get(c.evidence_id, 0.0) + abs(c.log_odds), 4)
        nodes = tuple(
            GraphNode(
                id=i.id,
                label=i.title,
                owner=i.owner,
                kind=i.kind,
                status="admitted" if i.id in st.admitted else "excluded" if i.id in st.excluded else "unpresented",
                weight=weight.get(i.id, 0.0),
            )
            for i in self.case.evidence
        )
        edges = [GraphEdge(source=a, target=b, relation="contradicts") for a, b in self.case.contradiction_edges()]
        admitted = [i for i in self.case.evidence if i.id in st.admitted]
        for x_idx, x in enumerate(admitted):
            for y in admitted[x_idx + 1 :]:
                if x.fact_id == y.fact_id:
                    continue
                if any(
                    x.support.get(e, 0) * y.support.get(e, 0) > 0 and min(abs(x.support[e]), abs(y.support[e])) >= 0.5
                    for e in x.support
                ):
                    edges.append(GraphEdge(source=x.id, target=y.id, relation="corroborates"))
        return EvidenceGraph(nodes=nodes, edges=tuple(edges))


def run_trial(case: CaseFile, prosecution: str, defense: str, seed: int = 0) -> TrialResult:
    """Convenience entry point used by the CLI, API, and tournament."""
    p_agent = make_agent(prosecution, random.Random(f"{seed}:agent:prosecution"))
    d_agent = make_agent(defense, random.Random(f"{seed}:agent:defense"))
    return Court(case, p_agent, d_agent, seed, prosecution, defense).run()


def threshold_probability(case: CaseFile) -> float:
    return _sigmoid(float(THRESHOLD_LOG_ODDS[case.standard]))

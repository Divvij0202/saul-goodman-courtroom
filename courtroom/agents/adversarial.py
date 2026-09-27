"""Robustness agents: Chaos (fuzzing) and Scripted (deterministic test fixtures).

Owner: Engineer 4.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from courtroom.agents.base import Oracle
from courtroom.contracts import Action, ActionType, ObjectionGround, PartyView, Side


class AgentCrash(RuntimeError):
    """Raised deliberately by the Chaos agent to test fault isolation."""


class ChaosAgent:
    """Emits random, frequently illegal actions, and occasionally raises.

    The engine must survive this agent with no uncaught exception, finite
    trial length, and a well-formed verdict.
    """

    name = "chaos"

    def __init__(self, rng: random.Random, crash_rate: float = 0.05) -> None:
        self.rng = rng
        self.crash_rate = crash_rate

    def opening_statement(self, side: Side) -> str:
        return "Counsel appears to have no strategy whatsoever."

    def act(self, view: PartyView, oracle: Oracle) -> Action:
        r = self.rng
        if r.random() < self.crash_rate:
            raise AgentCrash("chaos agent crashed on purpose")
        own_ids = [e.id for e in view.own_evidence]
        junk_ids = ["NOPE-404", *view.admitted, *own_ids]
        return Action(
            actor=r.choice([view.side, view.side, view.side, view.side.opponent]),
            type=r.choice(list(ActionType)),
            evidence_id=r.choice([None, *junk_ids]) if junk_ids else None,
            witness_id=r.choice([None, "W-GHOST", *[w for _, w in view.impeachment_options]]),
            ground=r.choice([None, *ObjectionGround]),
            rationale="¯\\_(ツ)_/¯",
        )


class ScriptedAgent:
    """Replays a fixed list of actions (then rests/passes). Used by tests and demos."""

    def __init__(self, script: Sequence[Action], name: str = "scripted") -> None:
        self._script = list(script)
        self.name = name

    def opening_statement(self, side: Side) -> str:
        return "Scripted counsel."

    def act(self, view: PartyView, oracle: Oracle) -> Action:
        if self._script:
            return self._script.pop(0)
        kind = ActionType.REST if view.window == "primary" else ActionType.PASS
        return Action(actor=view.side, type=kind)

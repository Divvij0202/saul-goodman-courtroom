"""Strategy-name to agent factory. Names are part of the public API (CLI, HTTP, web UI)."""

from __future__ import annotations

import random

from courtroom.agents.adversarial import ChaosAgent
from courtroom.agents.base import Agent
from courtroom.agents.policies import PROFILES, CounselAgent, MixedAgent

STRATEGY_NAMES: tuple[str, ...] = ("aggressive", "conservative", "adaptive", "chaos")


def describe_strategies() -> list[dict[str, str]]:
    out = [{"name": p.name, "label": p.label, "description": p.description} for p in PROFILES.values()]
    out.append({"name": "chaos", "label": "Chaos", "description": "Random, often illegal actions (robustness fuzzing)."})
    out.append({"name": "mixed:<p>", "label": "Mixed", "description": "Aggressive with probability p, else Conservative."})
    return out


def make_agent(strategy: str, rng: random.Random) -> Agent:
    """Build an agent. ``rng`` must be the side-specific trial RNG so results are reproducible."""
    if strategy in PROFILES:
        return CounselAgent(PROFILES[strategy])
    if strategy == "chaos":
        return ChaosAgent(rng)
    if strategy.startswith("mixed:"):
        p = float(strategy.split(":", 1)[1])
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"mixed probability must be in [0, 1], got {p}")
        return MixedAgent(p, rng)
    raise ValueError(f"unknown strategy {strategy!r}; choose from {STRATEGY_NAMES} or mixed:<p>")

"""Strategic counsel agents (Engineer 4)."""

from courtroom.agents.adversarial import AgentCrash, ChaosAgent, ScriptedAgent
from courtroom.agents.base import Agent, Oracle, ScoreCache, perceive
from courtroom.agents.policies import (
    ADAPTIVE,
    AGGRESSIVE,
    CONSERVATIVE,
    PROFILES,
    CounselAgent,
    MixedAgent,
    StrategyProfile,
)
from courtroom.agents.registry import STRATEGY_NAMES, describe_strategies, make_agent

__all__ = [
    "ADAPTIVE",
    "AGGRESSIVE",
    "CONSERVATIVE",
    "PROFILES",
    "STRATEGY_NAMES",
    "Agent",
    "AgentCrash",
    "ChaosAgent",
    "CounselAgent",
    "MixedAgent",
    "Oracle",
    "ScoreCache",
    "ScriptedAgent",
    "StrategyProfile",
    "describe_strategies",
    "make_agent",
    "perceive",
]

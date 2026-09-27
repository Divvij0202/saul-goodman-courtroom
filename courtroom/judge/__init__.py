"""Deterministic rule-based judge (Engineer 3)."""

from courtroom.judge.admissibility import valid_grounds
from courtroom.judge.judge import Judge
from courtroom.judge.scoring import ExactScores, score_record

__all__ = ["ExactScores", "Judge", "score_record", "valid_grounds"]

"""Monte-Carlo payoff estimation, tournaments, and robustness stress runs.

Owner: Engineer 5.

Every estimate is a deterministic function of (case, strategies, seeds): the
same call returns the same matrix on any machine, which makes the published
equilibria reproducible.
"""

from __future__ import annotations

import statistics
import time
import traceback
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor

from pydantic import BaseModel, ConfigDict

from courtroom.cases import CASES, generate_case, get_case
from courtroom.contracts import CaseFile, Side, VerdictOutcome
from courtroom.engine import MAX_EVENTS, run_trial, verify_chain
from courtroom.gametheory.nash import GameAnalysis, analyze


class Cell(BaseModel):
    model_config = ConfigDict(frozen=True)
    row: str
    col: str
    n: int
    mean_row: float
    mean_col: float
    se_row: float
    se_col: float
    prosecution_win_rate: float
    mean_burden: float


class PayoffTable(BaseModel):
    model_config = ConfigDict(frozen=True)
    case_id: str
    row_strategies: list[str]
    col_strategies: list[str]
    seeds: list[int]
    cells: list[Cell]
    analysis: GameAnalysis


def _cell(args: tuple[CaseFile, str, str, tuple[int, ...]]) -> Cell:
    case, row, col, seeds = args
    up, ud, wins, burden = [], [], 0, []
    for s in seeds:
        r = run_trial(case, row, col, seed=s)
        up.append(r.utilities[Side.PROSECUTION])
        ud.append(r.utilities[Side.DEFENSE])
        wins += r.verdict.outcome.favours is Side.PROSECUTION
        burden.append(r.verdict.snapshot.burden_index)
    n = len(seeds)

    def se(xs: list[float]) -> float:
        return statistics.stdev(xs) / n**0.5 if n > 1 else 0.0

    return Cell(
        row=row,
        col=col,
        n=n,
        mean_row=round(statistics.fmean(up), 6),
        mean_col=round(statistics.fmean(ud), 6),
        se_row=round(se(up), 6),
        se_col=round(se(ud), 6),
        prosecution_win_rate=round(wins / n, 6),
        mean_burden=round(statistics.fmean(burden), 6),
    )


def estimate_payoffs(
    case: CaseFile,
    strategies: Sequence[str] = ("aggressive", "conservative"),
    col_strategies: Sequence[str] | None = None,
    seeds: Sequence[int] = tuple(range(40)),
    workers: int = 1,
) -> PayoffTable:
    rows = list(strategies)
    cols = list(col_strategies or strategies)
    jobs = [(case, r, c, tuple(seeds)) for r in rows for c in cols]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            cells = list(pool.map(_cell, jobs))
    else:
        cells = [_cell(j) for j in jobs]
    grid = {(c.row, c.col): c for c in cells}
    A = [[grid[(r, c)].mean_row for c in cols] for r in rows]
    B = [[grid[(r, c)].mean_col for c in cols] for r in rows]
    return PayoffTable(
        case_id=case.id,
        row_strategies=rows,
        col_strategies=cols,
        seeds=list(seeds),
        cells=cells,
        analysis=analyze(rows, cols, A, B),
    )


def tournament(
    case_ids: Sequence[str] | None = None,
    strategies: Sequence[str] = ("aggressive", "conservative", "adaptive"),
    seeds: Sequence[int] = tuple(range(20)),
    workers: int = 1,
) -> list[PayoffTable]:
    ids = list(case_ids or CASES)
    return [estimate_payoffs(get_case(cid), strategies, seeds=seeds, workers=workers) for cid in ids]


# --------------------------------------------------------------------------- stress / fuzz


class StressReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    trials: int
    crashes: int
    invariant_failures: int
    failures: list[str]
    verdicts: dict[str, int]
    max_events: int
    mean_ms: float
    deterministic_replays: int


def stress(
    n_cases: int = 100,
    strategies: Sequence[str] = ("aggressive", "conservative", "adaptive", "chaos", "mixed:0.5"),
    replay_every: int = 10,
) -> StressReport:
    """Fuzz the engine over generated cases x strategy pairs and check invariants.

    Invariants: no exception; hash chain valid; event count <= MAX_EVENTS + small
    constant; budgets never negative; verdict favours the defense whenever no
    prosecution item was admitted; replays give identical digests.
    """
    failures: list[str] = []
    verdicts: Counter[str] = Counter()
    crashes = inv = trials = replays = max_ev = 0
    elapsed = 0.0
    for seed in range(n_cases):
        case = generate_case(seed)
        for p in strategies:
            for d in strategies:
                trials += 1
                t0 = time.perf_counter()
                try:
                    r = run_trial(case, p, d, seed=seed)
                except Exception:
                    crashes += 1
                    failures.append(f"CRASH {case.id} {p} v {d}: {traceback.format_exc(limit=3)}")
                    continue
                elapsed += time.perf_counter() - t0
                verdicts[r.verdict.outcome.value] += 1
                max_ev = max(max_ev, len(r.events))
                problems = []
                if not verify_chain(r.events):
                    problems.append("hash chain broken")
                if len(r.events) > MAX_EVENTS + 10:
                    problems.append(f"{len(r.events)} events")
                if any(lg.budget < 0 for lg in r.ledgers.values()):
                    problems.append("negative budget")
                admitted_p = [n for n in r.graph.nodes if n.owner is Side.PROSECUTION and n.status == "admitted"]
                if not admitted_p and r.verdict.outcome in (VerdictOutcome.GUILTY, VerdictOutcome.LIABLE):
                    problems.append("conviction without admitted prosecution evidence")
                if replay_every and trials % replay_every == 0:
                    replays += 1
                    if run_trial(case, p, d, seed=seed).digest != r.digest:
                        problems.append("non-deterministic replay")
                if problems:
                    inv += 1
                    failures.append(f"INVARIANT {case.id} {p} v {d}: {problems}")
    ok = trials - crashes
    return StressReport(
        trials=trials,
        crashes=crashes,
        invariant_failures=inv,
        failures=failures[:50],
        verdicts=dict(verdicts),
        max_events=max_ev,
        mean_ms=round(1000 * elapsed / ok, 3) if ok else 0.0,
        deterministic_replays=replays,
    )

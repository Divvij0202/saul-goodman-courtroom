"""Two-population replicator dynamics ("evolution of legal culture").

Owner: Engineer 5. Display-oriented, so floats are fine here: the exact claims
live in ``nash.py``.

x_i' = x_i ((A y)_i - x.A y),   y_j' = y_j ((x B)_j - x.B y)
"""

from __future__ import annotations

from collections.abc import Sequence


def replicator(
    A: Sequence[Sequence[float]],
    B: Sequence[Sequence[float]],
    x0: Sequence[float],
    y0: Sequence[float],
    steps: int = 400,
    dt: float = 0.05,
) -> list[tuple[list[float], list[float]]]:
    m, n = len(A), len(A[0])
    x, y = list(x0), list(y0)
    traj = [(x[:], y[:])]
    for _ in range(steps):
        ay = [sum(A[i][j] * y[j] for j in range(n)) for i in range(m)]
        xb = [sum(B[i][j] * x[i] for i in range(m)) for j in range(n)]
        ubar = sum(x[i] * ay[i] for i in range(m))
        vbar = sum(y[j] * xb[j] for j in range(n))
        x = [max(0.0, x[i] + dt * x[i] * (ay[i] - ubar)) for i in range(m)]
        y = [max(0.0, y[j] + dt * y[j] * (xb[j] - vbar)) for j in range(n)]
        sx, sy = sum(x) or 1.0, sum(y) or 1.0
        x, y = [v / sx for v in x], [v / sy for v in y]
        traj.append((x[:], y[:]))
    return traj

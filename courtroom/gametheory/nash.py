"""Exact Nash-equilibrium analysis of bimatrix games.

Owner: Engineer 5 (Game Theory & Tournament).

Everything is computed in ``fractions.Fraction``, so equilibria are exact and the
verifier's "no profitable deviation" check is a proof for the estimated game,
not a floating-point approximation.

Algorithms:
* Support enumeration over equal-size supports (complete for non-degenerate games).
* Iterated elimination of strictly dominated (pure) strategies.
* Independent best-response verifier.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from itertools import combinations

from pydantic import BaseModel, ConfigDict

Matrix = list[list[Fraction]]
Vector = list[Fraction]


def as_fraction_matrix(rows: Sequence[Sequence[float | int | Fraction]]) -> Matrix:
    out: Matrix = []
    for row in rows:
        out.append(
            [x if isinstance(x, Fraction) else Fraction(repr(float(x))) if isinstance(x, float) else Fraction(x) for x in row]
        )
    return out


# --------------------------------------------------------------------------- linear algebra


def solve(M: Matrix, b: Vector) -> Vector | None:
    """Gaussian elimination over the rationals. ``None`` if singular."""
    n = len(M)
    aug = [[*M[i], b[i]] for i in range(n)]
    for col in range(n):
        pivot = next((r for r in range(col, n) if aug[r][col] != 0), None)
        if pivot is None:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for r in range(n):
            if r != col and aug[r][col] != 0:
                factor = aug[r][col] / aug[col][col]
                aug[r] = [a - factor * c for a, c in zip(aug[r], aug[col], strict=True)]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def _row_payoffs(A: Matrix, y: Vector) -> Vector:
    return [sum((A[i][j] * y[j] for j in range(len(y))), Fraction(0)) for i in range(len(A))]


def _col_payoffs(B: Matrix, x: Vector) -> Vector:
    return [sum((B[i][j] * x[i] for i in range(len(x))), Fraction(0)) for j in range(len(B[0]))]


# --------------------------------------------------------------------------- equilibria


def verify_equilibrium(A: Matrix, B: Matrix, x: Vector, y: Vector) -> bool:
    """True iff (x, y) are distributions and neither player gains by deviating."""
    if any(p < 0 for p in x + y) or sum(x) != 1 or sum(y) != 1:
        return False
    row_vals = _row_payoffs(A, y)
    col_vals = _col_payoffs(B, x)
    u = sum((x[i] * row_vals[i] for i in range(len(x))), Fraction(0))
    v = sum((y[j] * col_vals[j] for j in range(len(y))), Fraction(0))
    return max(row_vals) <= u and max(col_vals) <= v


def support_enumeration(A: Matrix, B: Matrix) -> list[tuple[Vector, Vector]]:
    m, n = len(A), len(A[0])
    found: list[tuple[Vector, Vector]] = []
    for k in range(1, min(m, n) + 1):
        for I in combinations(range(m), k):  # noqa: E741 - supports, standard notation
            for J in combinations(range(n), k):
                # Column mix y on J making every row in I indifferent (value u).
                My = [[A[i][j] for j in J] + [Fraction(-1)] for i in I] + [[Fraction(1)] * k + [Fraction(0)]]
                sy = solve(My, [Fraction(0)] * k + [Fraction(1)])
                # Row mix x on I making every column in J indifferent (value v).
                Mx = [[B[i][j] for i in I] + [Fraction(-1)] for j in J] + [[Fraction(1)] * k + [Fraction(0)]]
                sx = solve(Mx, [Fraction(0)] * k + [Fraction(1)])
                if sy is None or sx is None:
                    continue
                x = [Fraction(0)] * m
                y = [Fraction(0)] * n
                for idx, i in enumerate(I):
                    x[i] = sx[idx]
                for idx, j in enumerate(J):
                    y[j] = sy[idx]
                if verify_equilibrium(A, B, x, y) and (x, y) not in found:
                    found.append((x, y))
    return found


# --------------------------------------------------------------------------- dominance


def dominant_strategy(M: Matrix, player: str) -> tuple[int | None, str | None]:
    """Index of a (strictly, else weakly) dominant pure strategy for 'row' or 'col'."""
    P = M if player == "row" else [list(col) for col in zip(*M, strict=True)]
    k = len(P)
    for strictness in ("strict", "weak"):
        for s in range(k):
            ok = True
            for t in range(k):
                if t == s:
                    continue
                diffs = [a - b for a, b in zip(P[s], P[t], strict=True)]
                if (strictness == "strict" and not all(d > 0 for d in diffs)) or (
                    strictness == "weak" and not (all(d >= 0 for d in diffs) and any(d > 0 for d in diffs))
                ):
                    ok = False
                if not ok:
                    break
            if ok and k > 1:
                return s, strictness
    return None, None


def iesds(A: Matrix, B: Matrix) -> tuple[list[int], list[int]]:
    rows, cols = list(range(len(A))), list(range(len(A[0])))
    changed = True
    while changed:
        changed = False
        for r in list(rows):
            if any(all(A[o][c] > A[r][c] for c in cols) for o in rows if o != r):
                rows.remove(r)
                changed = True
        for c in list(cols):
            if any(all(B[r][o] > B[r][c] for r in rows) for o in cols if o != c):
                cols.remove(c)
                changed = True
    return rows, cols


# --------------------------------------------------------------------------- report


class Equilibrium(BaseModel):
    model_config = ConfigDict(frozen=True)
    row_mix: dict[str, float]
    col_mix: dict[str, float]
    row_mix_exact: dict[str, str]
    col_mix_exact: dict[str, str]
    row_payoff: float
    col_payoff: float
    pure: bool
    verified: bool


class GameAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)
    row_player: str
    col_player: str
    row_labels: list[str]
    col_labels: list[str]
    A: list[list[float]]
    B: list[list[float]]
    equilibria: list[Equilibrium]
    row_dominant: str | None
    row_dominance: str | None
    col_dominant: str | None
    col_dominance: str | None
    iesds_rows: list[str]
    iesds_cols: list[str]
    trivial: bool
    degenerate: bool
    welfare_max: tuple[str, str]
    notes: list[str]


def _fs(x: Fraction) -> str:
    return f"{x.numerator}/{x.denominator}" if x.denominator != 1 else str(x.numerator)


def analyze(
    row_labels: Sequence[str],
    col_labels: Sequence[str],
    A_in: Sequence[Sequence[float | int | Fraction]],
    B_in: Sequence[Sequence[float | int | Fraction]],
    row_player: str = "prosecution",
    col_player: str = "defense",
) -> GameAnalysis:
    A, B = as_fraction_matrix(A_in), as_fraction_matrix(B_in)
    eqs = support_enumeration(A, B)
    equilibria: list[Equilibrium] = []
    for x, y in eqs:
        row_vals = _row_payoffs(A, y)
        col_vals = _col_payoffs(B, x)
        u = sum((x[i] * row_vals[i] for i in range(len(x))), Fraction(0))
        v = sum((y[j] * col_vals[j] for j in range(len(y))), Fraction(0))
        equilibria.append(
            Equilibrium(
                row_mix={row_labels[i]: float(p) for i, p in enumerate(x)},
                col_mix={col_labels[j]: float(p) for j, p in enumerate(y)},
                row_mix_exact={row_labels[i]: _fs(p) for i, p in enumerate(x)},
                col_mix_exact={col_labels[j]: _fs(p) for j, p in enumerate(y)},
                row_payoff=float(u),
                col_payoff=float(v),
                pure=all(p in (0, 1) for p in x + y),
                verified=verify_equilibrium(A, B, x, y),
            )
        )
    rd, rds = dominant_strategy(A, "row")
    cd, cds = dominant_strategy(B, "col")
    rows, cols = iesds(A, B)
    welfare = max(
        ((i, j) for i in range(len(A)) for j in range(len(A[0]))),
        key=lambda ij: (A[ij[0]][ij[1]] + B[ij[0]][ij[1]], -ij[0], -ij[1]),
    )
    trivial = (rds == "strict" and cds == "strict") or (len(rows) == 1 and len(cols) == 1)
    degenerate = len(equilibria) % 2 == 0
    notes: list[str] = []
    if trivial:
        notes.append("Game is dominance-solvable: strategy choice is trivial in this case.")
    if not any(e.pure for e in equilibria):
        notes.append("No pure equilibrium: optimal play requires randomisation (mixed strategy).")
    if degenerate:
        notes.append("Even number of equilibria found: the game is degenerate (ties); a continuum may exist.")
    wi, wj = welfare
    for idx, e in enumerate(equilibria, 1):
        better = [
            (row_labels[i], col_labels[j])
            for i in range(len(A))
            for j in range(len(A[0]))
            if A[i][j] > Fraction(repr(e.row_payoff)) and B[i][j] > Fraction(repr(e.col_payoff))
        ]
        if better:
            notes.append(f"Social dilemma: profile {better[0]} Pareto-dominates equilibrium {idx}.")
    return GameAnalysis(
        row_player=row_player,
        col_player=col_player,
        row_labels=list(row_labels),
        col_labels=list(col_labels),
        A=[[float(v) for v in r] for r in A],
        B=[[float(v) for v in r] for r in B],
        equilibria=equilibria,
        row_dominant=row_labels[rd] if rd is not None else None,
        row_dominance=rds,
        col_dominant=col_labels[cd] if cd is not None else None,
        col_dominance=cds,
        iesds_rows=[row_labels[i] for i in rows],
        iesds_cols=[col_labels[j] for j in cols],
        trivial=trivial,
        degenerate=degenerate,
        welfare_max=(row_labels[wi], col_labels[wj]),
        notes=notes,
    )

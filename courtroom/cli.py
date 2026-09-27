"""Command-line interface: ``python -m courtroom <command>``.

Owner: Engineer 6.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console

from courtroom.cases import CASES, generate_case, get_case
from courtroom.contracts import CaseFile
from courtroom.engine import run_trial, verify_chain

# Windows consoles default to cp1252; never let a glyph crash a live demo.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

console = Console()
EXPORT_DIR = Path(__file__).resolve().parent / "viz" / "web" / "data"


def _case(case_id: str) -> CaseFile:
    return generate_case(int(case_id[4:])) if case_id.startswith("gen-") else get_case(case_id)


def cmd_cases(_: argparse.Namespace) -> int:
    for c in CASES.values():
        console.print(f"[bold]{c.id:24s}[/] {c.case_type.value:8s} {c.standard.value:24s} {c.title}")
        console.print(f"    [grey50]{', '.join(c.tags)}[/]")
    console.print("[grey50]Generated cases: gen-<seed>, e.g. gen-42[/]")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    from courtroom.viz.terminal import print_summary, replay

    result = run_trial(_case(a.case), a.prosecution, a.defense, a.seed)
    if a.json:
        Path(a.json).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"wrote {a.json}")
    if a.live:
        replay(result, delay=a.delay, console=console)
    else:
        for ev in result.events:
            actor = ev.actor.value if ev.actor else "court"
            console.print(
                f"[grey50]{ev.seq:3d}[/] [{'red' if actor == 'prosecution' else 'cyan' if actor == 'defense' else 'yellow'}]{actor:11s}[/] {ev.summary}"
            )
        print_summary(result, console)
    return 0


def cmd_game(a: argparse.Namespace) -> int:
    from courtroom.gametheory import estimate_payoffs
    from courtroom.viz.terminal import print_game

    table = estimate_payoffs(_case(a.case), a.strategies.split(","), seeds=range(a.seeds), workers=a.workers)
    print_game(table, console)
    if a.json:
        Path(a.json).write_text(table.model_dump_json(indent=2), encoding="utf-8")
    return 0


def cmd_tournament(a: argparse.Namespace) -> int:
    from courtroom.gametheory import tournament
    from courtroom.viz.terminal import print_game

    for table in tournament(strategies=a.strategies.split(","), seeds=range(a.seeds), workers=a.workers):
        print_game(table, console)
        console.rule()
    return 0


def cmd_stress(a: argparse.Namespace) -> int:
    from courtroom.gametheory import stress

    report = stress(n_cases=a.cases)
    console.print_json(report.model_dump_json())
    return 0 if report.crashes == 0 and report.invariant_failures == 0 else 1


def cmd_verify(a: argparse.Namespace) -> int:
    case = _case(a.case)
    first = run_trial(case, a.prosecution, a.defense, a.seed)
    second = run_trial(case, a.prosecution, a.defense, a.seed)
    same = first.digest == second.digest and first.model_dump_json() == second.model_dump_json()
    chain_ok = verify_chain(first.events)
    console.print(f"digest run 1: {first.digest}\ndigest run 2: {second.digest}")
    console.print(
        f"bit-identical results: {'[green]YES' if same else '[red]NO'}[/]   hash chain valid: {'[green]YES' if chain_ok else '[red]NO'}[/]"
    )
    return 0 if same and chain_ok else 1


def cmd_export(a: argparse.Namespace) -> int:
    """Pre-compute a static bundle so the web UI works with no server (demo fallback)."""
    from courtroom.agents import describe_strategies
    from courtroom.gametheory import estimate_payoffs, replicator

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bundle: dict[str, object] = {
        "cases": [json.loads(c.model_dump_json()) for c in CASES.values()],
        "strategies": describe_strategies(),
        "trials": {},
        "games": {},
    }
    pairs = [
        ("aggressive", "conservative"),
        ("aggressive", "aggressive"),
        ("conservative", "aggressive"),
        ("conservative", "conservative"),
        ("adaptive", "adaptive"),
        ("chaos", "aggressive"),
    ]
    for cid, case in CASES.items():
        for p, d in pairs:
            r = run_trial(case, p, d, seed=0)
            bundle["trials"][f"{cid}|{p}|{d}|0"] = json.loads(r.model_dump_json())  # type: ignore[index]
        table = estimate_payoffs(case, ("aggressive", "conservative"), seeds=range(a.seeds), workers=a.workers)
        body = json.loads(table.model_dump_json())
        body["dynamics"] = [
            {"x": x, "y": y} for x, y in replicator(table.analysis.A, table.analysis.B, [0.5, 0.5], [0.5, 0.5], steps=300)[::5]
        ]
        bundle["games"][cid] = body  # type: ignore[index]
        console.print(f"exported {cid}")
    payload = json.dumps(bundle, separators=(",", ":"))
    (out / "bundle.js").write_text(f"window.COURTROOM_BUNDLE = {payload};\n", encoding="utf-8")
    console.print(f"[green]wrote {out / 'bundle.js'} ({len(payload) // 1024} KiB)[/]")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    console.print(f"Courtroom UI on http://{a.host}:{a.port}/")
    uvicorn.run("courtroom.api.server:app", host=a.host, port=a.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="courtroom", description="Strategic AI agents in a simulated courtroom.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("cases", help="list the synthetic case library").set_defaults(fn=cmd_cases)

    def trial_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--case", default="helix-espionage")
        p.add_argument("-p", "--prosecution", default="aggressive")
        p.add_argument("-d", "--defense", default="conservative")
        p.add_argument("--seed", type=int, default=0)

    p = sub.add_parser("run", help="run one trial")
    trial_args(p)
    p.add_argument("--live", action="store_true", help="animated dashboard replay")
    p.add_argument("--delay", type=float, default=0.35)
    p.add_argument("--json", help="write the TrialResult JSON here")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("verify", help="prove determinism: run twice, compare digests, check hash chain")
    trial_args(p)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("game", help="payoff matrix + exact Nash equilibria for one case")
    p.add_argument("--case", default="helix-espionage")
    p.add_argument("--strategies", default="aggressive,conservative")
    p.add_argument("--seeds", type=int, default=40)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--json")
    p.set_defaults(fn=cmd_game)

    p = sub.add_parser("tournament", help="game analysis across the whole library")
    p.add_argument("--strategies", default="aggressive,conservative")
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--workers", type=int, default=1)
    p.set_defaults(fn=cmd_tournament)

    p = sub.add_parser("stress", help="fuzz generated cases x all strategies (incl. chaos); exit 1 on any failure")
    p.add_argument("--cases", type=int, default=100)
    p.set_defaults(fn=cmd_stress)

    p = sub.add_parser("export", help="write the static web bundle (offline demo fallback)")
    p.add_argument("--out", default=str(EXPORT_DIR))
    p.add_argument("--seeds", type=int, default=30)
    p.add_argument("--workers", type=int, default=1)
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("serve", help="start the web UI + API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (KeyError, ValueError) as exc:
        console.print(f"[red]error:[/] {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

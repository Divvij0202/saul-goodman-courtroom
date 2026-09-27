"""Rich terminal dashboard: live replay of a trial and game-theory tables.

Owner: Engineer 7 (Visualisation). Pure consumer of ``TrialResult`` /
``PayoffTable``; it never calls the engine itself, so it can't affect outcomes.
"""

from __future__ import annotations

import time

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from courtroom.contracts import EventKind, Side, TrialEvent, TrialResult
from courtroom.gametheory import PayoffTable

SIDE_STYLE = {Side.PROSECUTION: "bold red", Side.DEFENSE: "bold cyan", None: "yellow"}
KIND_ICON = {
    EventKind.PHASE_CHANGE: "§",
    EventKind.ACTION: "»",
    EventKind.RULING: "⚖",
    EventKind.VIOLATION: "✖",
    EventKind.DIRECTED_VERDICT: "⚑",
    EventKind.WATCHDOG: "⏱",
    EventKind.VERDICT: "★",
}


def gauge(p: float, threshold: float, width: int = 32) -> Text:
    filled = round(p * width)
    mark = min(width - 1, round(threshold * width))
    text = Text()
    for i in range(width):
        if i == mark:
            text.append("┃", style="bold white")
        elif i < filled:
            text.append("█", style="green" if p >= threshold else "magenta")
        else:
            text.append("░", style="grey37")
    text.append(f" {p:6.1%}")
    return text


def _burden_panel(result: TrialResult, event: TrialEvent) -> Panel:
    thr = result.verdict.snapshot.elements[0].threshold_probability
    table = Table.grid(padding=(0, 1))
    for element, p in event.element_probabilities.items():
        table.add_row(Text(element, style="bold"), gauge(p, thr))
    table.add_row(Text("BURDEN", style="bold yellow"), gauge(event.burden_index or 0.0, thr))
    return Panel(table, title=f"Burden of proof (threshold ┃ {thr:.0%})", border_style="yellow")


def _stream_panel(events: list[TrialEvent], height: int = 18) -> Panel:
    lines = []
    for ev in events[-height:]:
        style = SIDE_STYLE.get(ev.actor, "yellow")
        if ev.kind is EventKind.VIOLATION:
            style = "bold white on red"
        elif ev.kind is EventKind.VERDICT:
            style = "bold black on yellow"
        line = Text(f"{ev.seq:3d} {KIND_ICON[ev.kind]} ", style="grey50")
        line.append(ev.summary[:120], style=style)
        lines.append(line)
    return Panel(Group(*lines), title="Action stream", border_style="blue")


def _rules_panel(event: TrialEvent) -> Panel:
    body: list[Text] = []
    if event.action and event.action.rationale:
        body.append(Text(f"Agent rationale: {event.action.rationale}", style="italic"))
    for r in event.rules:
        body.append(Text(f"[{r.rule_id}] {r.detail}"))
    if not body:
        body.append(Text("—", style="grey50"))
    return Panel(Group(*body), title=f"Rules fired · hash {event.hash[:16]}…", border_style="magenta")


def _ledger_panel(result: TrialResult) -> Panel:
    t = Table(show_header=True, header_style="bold", expand=True)
    t.add_column("")
    t.add_column("Prosecution", style="red")
    t.add_column("Defense", style="cyan")
    lp, ld = result.ledgers[Side.PROSECUTION], result.ledgers[Side.DEFENSE]
    for label, attr in [
        ("Budget left", "budget"),
        ("Spent", "spent"),
        ("Presented", "presented"),
        ("Admitted", "admitted"),
        ("Excluded", "excluded"),
        ("Objections", "objections"),
        ("Sustained", "sustained"),
        ("Overruled", "overruled"),
        ("Impeachments", "impeachments"),
        ("Violations", "violations"),
        ("Sanctions", "sanctions"),
    ]:
        t.add_row(label, f"{getattr(lp, attr):g}", f"{getattr(ld, attr):g}")
    t.add_row("Utility", f"{result.utilities[Side.PROSECUTION]:+.2f}", f"{result.utilities[Side.DEFENSE]:+.2f}", style="bold")
    return Panel(t, title="Ledgers (final)", border_style="green")


def contradiction_tree(result: TrialResult) -> Tree:
    status = {n.id: n.status for n in result.graph.nodes}
    tree = Tree("Evidence graph", guide_style="grey50")
    style = {"admitted": "green", "excluded": "strike red", "unpresented": "grey50"}
    contra = tree.add("[bold magenta]contradicts")
    for e in (e for e in result.graph.edges if e.relation == "contradicts"):
        contra.add(Text.assemble((e.source, style[status[e.source]]), " ⟷ ", (e.target, style[status[e.target]])))
    corr = tree.add("[bold green]corroborates")
    for e in (e for e in result.graph.edges if e.relation == "corroborates"):
        corr.add(f"{e.source} ⟶ {e.target}")
    return tree


def _layout(result: TrialResult, upto: int) -> Layout:
    events = list(result.events[: upto + 1])
    current = events[-1]
    header = Text.assemble(
        (f" {result.case_title} ", "bold white on dark_blue"),
        f"  P: {result.prosecution_strategy}  vs  D: {result.defense_strategy}  · seed {result.seed} · phase {current.phase.value}",
    )
    root = Layout()
    root.split_column(Layout(header, size=1), Layout(name="body"), Layout(_rules_panel(current), size=7))
    root["body"].split_row(Layout(name="left", ratio=2), Layout(_stream_panel(events), ratio=3))
    root["body"]["left"].split_column(
        Layout(_burden_panel(result, current), size=len(current.element_probabilities) + 3), Layout(_ledger_panel(result))
    )
    return root


def replay(result: TrialResult, delay: float = 0.35, console: Console | None = None) -> None:
    console = console or Console()
    with Live(_layout(result, 0), console=console, refresh_per_second=12, screen=False) as live:
        for i in range(len(result.events)):
            live.update(_layout(result, i))
            time.sleep(delay)
    print_summary(result, console)


def print_summary(result: TrialResult, console: Console | None = None) -> None:
    console = console or Console()
    v = result.verdict
    colour = "red" if v.outcome.favours is Side.PROSECUTION else "cyan"
    console.print(
        Panel(
            Text(f"{v.outcome.value.upper().replace('_', ' ')}\n{v.reason}", justify="center", style=f"bold {colour}"),
            title="VERDICT",
        )
    )
    t = Table(title="Element findings", show_lines=False)
    for col in ("Element", "Log-odds (exact)", "P", "Threshold", "Met", "Counted evidence"):
        t.add_column(col)
    for es in v.snapshot.elements:
        t.add_row(
            es.element_id,
            es.log_odds,
            f"{es.probability:.1%}",
            es.threshold,
            "✔" if es.met else "✘",
            ", ".join(f"{c.evidence_id}({c.log_odds:+.2f})" for c in es.contributions if c.counted) or "—",
        )
    console.print(t)
    console.print(contradiction_tree(result))
    console.print(f"[grey50]Audit digest: {result.digest}[/]")


def print_game(table: PayoffTable, console: Console | None = None) -> None:
    console = console or Console()
    a = table.analysis
    eq_cells = {
        (r, c) for e in a.equilibria if e.pure for r, pr in e.row_mix.items() if pr == 1 for c, pc in e.col_mix.items() if pc == 1
    }
    t = Table(title=f"Payoff matrix · {table.case_id} · {len(table.seeds)} seeds  (U_prosecution, U_defense)")
    t.add_column("P \\ D", style="bold red")
    for c in table.col_strategies:
        t.add_column(c, style="cyan", justify="center")
    grid = {(x.row, x.col): x for x in table.cells}
    for r in table.row_strategies:
        row = []
        for c in table.col_strategies:
            cell = grid[(r, c)]
            txt = f"({cell.mean_row:+.2f}, {cell.mean_col:+.2f})\nP wins {cell.prosecution_win_rate:.0%}"
            row.append(Text(txt, style="bold black on yellow" if (r, c) in eq_cells else ""))
        t.add_row(r, *row)
    console.print(t)
    for i, e in enumerate(a.equilibria, 1):
        kind = "pure" if e.pure else "mixed"
        console.print(
            f"[bold]NE {i} ({kind}, verified={e.verified})[/]: P={e.row_mix_exact}  D={e.col_mix_exact}  "
            f"→ U=({e.row_payoff:+.3f}, {e.col_payoff:+.3f})"
        )
    console.print(
        f"Dominant: P={a.row_dominant} ({a.row_dominance}), D={a.col_dominant} ({a.col_dominance}); IESDS → {a.iesds_rows} × {a.iesds_cols}"
    )
    for n in a.notes:
        console.print(f"[yellow]• {n}[/]")

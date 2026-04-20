"""Rich terminal output: summary panel, pod table, AI analysis panel."""

from __future__ import annotations


from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pod_health.analyzer import HealthReport, PodReport

console = Console()

_SEVERITY_COLOR = {"critical": "red", "warning": "yellow", "info": "dim"}
_PHASE_COLOR = {
    "Running": "green",
    "Pending": "yellow",
    "Succeeded": "dim",
    "Failed": "red",
    "Unknown": "dim",
}


def render_report(report: HealthReport, ai_analysis: str = "", no_ai: bool = False) -> None:
    """Render the full health report to the terminal."""
    _render_summary(report)
    _render_pod_table(report.pod_reports)
    if report.aggregated_issues:
        _render_aggregated_issues(report)
    if ai_analysis:
        _render_ai_panel(ai_analysis)
    elif not no_ai and (report.critical > 0 or report.warning > 0):
        console.print("[dim]  (AI analysis unavailable)[/dim]\n")


def _render_summary(report: HealthReport) -> None:
    parts = [
        f"[bold]Total:[/bold] {report.total}",
        f"[green]Healthy: {report.healthy}[/green]",
        f"[yellow]Warning: {report.warning}[/yellow]",
        f"[red]Critical: {report.critical}[/red]",
    ]
    summary_text = "   ".join(parts)
    if report.critical > 0:
        title_color = "red"
    elif report.warning > 0:
        title_color = "yellow"
    else:
        title_color = "green"
    console.print(
        Panel(
            summary_text,
            title=f"[{title_color}]K8s Pod Health Report[/{title_color}]",
            expand=False,
        )
    )
    console.print()


def _render_pod_table(reports: list[PodReport]) -> None:
    table = Table(show_header=True, header_style="bold cyan", expand=False, box=None)
    table.add_column("POD", style="bold", min_width=30)
    table.add_column("NAMESPACE", style="dim", min_width=10)
    table.add_column("PHASE", min_width=10)
    table.add_column("RESTARTS", justify="right", min_width=8)
    table.add_column("ISSUES", min_width=40)

    for r in reports:
        phase_color = _PHASE_COLOR.get(r.phase, "white")
        phase_text = Text(r.phase or "—", style=phase_color)

        if not r.issues:
            issues_text = Text("OK", style="green")
        else:
            lines: list[str] = []
            for issue in r.issues[:3]:  # cap at 3 lines per pod
                color = _SEVERITY_COLOR.get(issue.severity, "white")
                prefix = f"[{issue.container}] " if issue.container else ""
                lines.append(f"[{color}]{prefix}{issue.message}[/{color}]")
            if len(r.issues) > 3:
                lines.append(f"[dim]+{len(r.issues) - 3} more[/dim]")
            issues_text = Text.from_markup("\n".join(lines))

        table.add_row(
            r.pod_name,
            r.namespace,
            phase_text,
            str(r.restart_count) if r.restart_count else "—",
            issues_text,
        )

    console.print(table)
    console.print()


def _render_aggregated_issues(report: HealthReport) -> None:
    lines: list[str] = []
    for agg in report.aggregated_issues:
        color = _SEVERITY_COLOR.get(agg.severity, "white")
        ctrl = (
            f"{agg.controller_kind}/{agg.controller_name}" if agg.controller_kind else "standalone"
        )
        count_str = f"{agg.count} pod{'s' if agg.count != 1 else ''}"
        lines.append(
            f"[{color}][{agg.severity.upper()}][/{color}] {ctrl} ({agg.namespace}): "
            f"{agg.message} — {count_str}"
        )

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Aggregated Issues[/bold]",
            border_style="yellow",
            expand=False,
        )
    )
    console.print()


def _render_ai_panel(analysis: str) -> None:
    console.print(
        Panel(
            Markdown(analysis),
            title="[bold cyan]AI Analysis (Claude)[/bold cyan]",
            border_style="cyan",
            expand=True,
        )
    )
    console.print()


def render_error(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")


def render_warning(message: str) -> None:
    console.print(f"[yellow]Warning:[/yellow] {message}")

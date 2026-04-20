"""Typer CLI entry point for pod-health."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from pod_health.analyzer import analyze_all
from pod_health.parser import parse_pods
from pod_health.renderer import render_error, render_report, render_warning

app = typer.Typer(help="K8s Pod Health Analyzer — AI-powered kubectl pod diagnostics.")
console = Console()


@app.command()
def main(
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Path to kubectl JSON output file."),
    no_ai: bool = typer.Option(False, "--no-ai", help="Skip AI analysis (works offline)."),
    model: str = typer.Option("haiku", "--model", help="AI model: 'haiku' (default) or 'sonnet'."),
    namespace: Optional[str] = typer.Option(None, "--namespace", "-n", help="Filter by namespace."),
    output_json: bool = typer.Option(False, "--json", help="Output raw JSON report instead of rich UI."),
) -> None:
    """Analyze kubectl pod health — pipe JSON or specify --file."""
    # Read input
    raw_json = _read_input(file)
    if raw_json is None:
        return

    # Parse
    try:
        pods = parse_pods(raw_json)
    except ValueError as e:
        render_error(str(e))
        raise typer.Exit(1)

    if not pods:
        console.print("[yellow]No pods found in input.[/yellow]")
        raise typer.Exit(0)

    # Namespace filter
    if namespace:
        pods = [p for p in pods if p.metadata.namespace == namespace]
        if not pods:
            console.print(f"[yellow]No pods found in namespace '{namespace}'.[/yellow]")
            raise typer.Exit(0)

    # Analyze
    report = analyze_all(pods)

    # JSON output mode
    if output_json:
        _print_json(report)
        return

    # AI analysis
    ai_text = ""
    if not no_ai and (report.critical > 0 or report.warning > 0):
        ai_text = _run_ai(report, model)

    render_report(report, ai_analysis=ai_text, no_ai=no_ai)


def _read_input(file: Optional[Path]) -> Optional[str]:
    """Read JSON from --file or stdin. Returns None and prints error if neither available."""
    if file:
        try:
            return file.read_text()
        except OSError as e:
            render_error(f"Cannot read file '{file}': {e}")
            raise typer.Exit(1)

    if not sys.stdin.isatty():
        return sys.stdin.read()

    render_error(
        "No input provided. Use --file pods.json or pipe: kubectl get pods -o json | pod-health"
    )
    raise typer.Exit(1)


def _run_ai(report: "analyze_all.__class__", model: str) -> str:  # type: ignore[valid-type]
    """Run AI analysis with spinner. Returns analysis text or empty string on error."""
    from pod_health.ai_advisor import get_ai_analysis

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(description="Asking Claude for analysis...", total=None)
        try:
            return get_ai_analysis(report, model=model)  # type: ignore[arg-type]
        except RuntimeError as e:
            render_warning(f"AI analysis skipped: {e}")
            return ""


def _print_json(report: "analyze_all.__class__") -> None:  # type: ignore[valid-type]

    r = report  # type: ignore[assignment]
    data = {
        "summary": {
            "total": r.total,
            "healthy": r.healthy,
            "warning": r.warning,
            "critical": r.critical,
        },
        "pods": [
            {
                "name": p.pod_name,
                "namespace": p.namespace,
                "phase": p.phase,
                "restarts": p.restart_count,
                "issues": [
                    {"severity": i.severity, "message": i.message, "container": i.container}
                    for i in p.issues
                ],
            }
            for p in r.pod_reports
        ],
    }
    console.print_json(json.dumps(data))

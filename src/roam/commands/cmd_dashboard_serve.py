"""``roam dashboard-serve`` — start an interactive web dashboard for the codebase.

Serves a single-file HTML dashboard that visualizes the project's
symbol graph, file dependencies, and architecture layers.  Reads
everything from the local Roam SQLite index — no network egress,
no external services.

Output formats: always starts an HTTP server on localhost.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

import click

from roam.capability import roam_capability
from roam.commands.resolve import ensure_index
from roam.dashboard import DashboardServer
from roam.db.connection import find_project_root


@roam_capability(
    name="dashboard-serve",
    category="architecture",
    summary="Start an interactive web dashboard to explore the codebase graph",
    maturity="alpha",
    mcp_expose=True,
    mcp_preset=("core", "architecture"),
    side_effect=True,
    task_required=False,
    destructive=False,
    stale_sensitive=True,
    ai_safe=True,
    requires_index=True,
)
@click.command(name="dashboard-serve")
@click.option(
    "--port",
    type=int,
    default=8765,
    show_default=True,
    help="Port to listen on.",
)
@click.option(
    "--no-open",
    is_flag=True,
    default=False,
    help="Don't open the browser automatically.",
)
@click.pass_context
def dashboard_serve(ctx, port: int, no_open: bool) -> None:
    """Start an interactive web dashboard for exploring the codebase.

    The dashboard shows:
    - Symbol graph with drag/zoom/click interaction
    - File-level dependency view
    - Architecture layers
    - Kind distribution and complexity stats

    Press Ctrl+C to stop the server.
    """
    ensure_index()

    project_root = find_project_root()
    if project_root is None:
        project_root = Path.cwd()

    db_path = project_root / ".roam" / "index.db"
    if not db_path.exists():
        click.echo(f"Error: No index found at {db_path}. Run `roam index` first.", err=True)
        return

    server = DashboardServer(str(db_path), port=port)
    url = server.start()

    click.echo(f"\n  Dashboard: {url}")
    click.echo(f"  Project:   {project_root}")
    click.echo(f"  Press Ctrl+C to stop\n")

    if not no_open:
        webbrowser.open(url)

    try:
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nShutting down...")
        server.stop()

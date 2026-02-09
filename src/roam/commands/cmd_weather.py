"""Show code hotspots: churn x complexity ranking."""

import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import TOP_CHURN_FILES
from roam.output.formatter import format_table


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.option('-n', 'count', default=20, help='Number of hotspots')
def weather(count):
    """Show code hotspots: churn x complexity ranking."""
    _ensure_index()
    with open_db(readonly=True) as conn:
        rows = conn.execute(TOP_CHURN_FILES, (count * 2,)).fetchall()
        if not rows:
            click.echo("No churn data available. Is this a git repository?")
            return

        scored = []
        for r in rows:
            churn = r["total_churn"] or 0
            complexity = r["complexity"] or 1
            score = churn * complexity
            scored.append((score, churn, complexity, r["path"], r["language"] or ""))
        scored.sort(reverse=True)

        table_rows = []
        for score, churn, complexity, path, lang in scored[:count]:
            table_rows.append([f"{score:.0f}", str(churn), f"{complexity:.1f}", path, lang])

        click.echo("=== Hotspots (churn x complexity) ===")
        click.echo(format_table(
            ["Score", "Churn", "Complexity", "Path", "Lang"],
            table_rows,
        ))

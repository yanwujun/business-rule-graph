"""Show unreferenced exported symbols (dead code)."""

import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import UNREFERENCED_EXPORTS
from roam.output.formatter import abbrev_kind, loc, format_table


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
def dead():
    """Show unreferenced exported symbols (dead code)."""
    _ensure_index()
    with open_db(readonly=True) as conn:
        rows = conn.execute(UNREFERENCED_EXPORTS).fetchall()

        click.echo(f"=== Unreferenced Exports ({len(rows)}) ===")
        if not rows:
            click.echo("  (none -- all exports are referenced)")
            return

        table_rows = []
        for r in rows:
            table_rows.append([
                r["name"],
                abbrev_kind(r["kind"]),
                loc(r["file_path"], r["line_start"]),
            ])
        click.echo(format_table(
            ["Name", "Kind", "Location"],
            table_rows,
            budget=50,
        ))

        # Check for files with no extracted symbols (may cause false positives)
        unparsed = conn.execute(
            "SELECT COUNT(*) FROM files f "
            "WHERE NOT EXISTS (SELECT 1 FROM symbols s WHERE s.file_id = f.id)"
        ).fetchone()[0]
        if unparsed:
            click.echo(f"\nNote: {unparsed} files had no symbols extracted (may cause false positives)")

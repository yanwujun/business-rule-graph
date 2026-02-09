"""Show detected clusters and directory mismatches."""

import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import ALL_CLUSTERS
from roam.graph.clusters import compare_with_directories
from roam.output.formatter import format_table


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.option('--min-size', default=3, show_default=True, help='Hide clusters smaller than this')
def clusters(min_size):
    """Show code clusters and directory mismatches."""
    _ensure_index()
    with open_db(readonly=True) as conn:
        rows = conn.execute(ALL_CLUSTERS).fetchall()

        click.echo("=== Clusters ===")
        if rows:
            # Filter clusters by min-size
            visible = [r for r in rows if r["size"] >= min_size]
            hidden_count = len(rows) - len(visible)
            visible_ids = {r["cluster_id"] for r in visible}

            if visible:
                table_rows = []
                for r in visible:
                    members = r["members"] or ""
                    preview = members[:80] + "..." if len(members) > 80 else members
                    table_rows.append([
                        str(r["cluster_id"]),
                        r["cluster_label"],
                        str(r["size"]),
                        preview,
                    ])
                click.echo(format_table(
                    ["ID", "Label", "Size", "Members"],
                    table_rows,
                    budget=30,
                ))
            else:
                click.echo("  (no clusters with size >= {})".format(min_size))

            if hidden_count:
                click.echo(f"  ({hidden_count} clusters with fewer than {min_size} members hidden)")
        else:
            click.echo("  (no clusters detected)")
            return

        # --- Mismatches ---
        click.echo("\n=== Directory Mismatches (hidden coupling) ===")
        mismatches = compare_with_directories(conn)
        if mismatches:
            # Only show mismatches for displayed clusters
            mismatches = [m for m in mismatches if m["cluster_id"] in visible_ids]
        if mismatches:
            m_rows = []
            for m in mismatches:
                dirs = ", ".join(m["directories"][:5])
                if len(m["directories"]) > 5:
                    dirs += f" (+{len(m['directories']) - 5})"
                m_rows.append([
                    str(m["cluster_id"]),
                    m["cluster_label"],
                    str(m["mismatch_count"]),
                    dirs,
                ])
            click.echo(format_table(
                ["Cluster", "Label", "Mismatches", "Directories"],
                m_rows,
                budget=20,
            ))
        else:
            click.echo("  (none -- clusters align with directories)")

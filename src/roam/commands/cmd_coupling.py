"""Show temporal coupling: files that change together."""

import click

from roam.db.connection import open_db, db_exists
from roam.output.formatter import format_table


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.option('-n', 'count', default=20, help='Number of pairs to show')
def coupling(count):
    """Show temporal coupling: file pairs that change together."""
    _ensure_index()

    with open_db(readonly=True) as conn:
        rows = conn.execute("""
            SELECT fa.path as path_a, fb.path as path_b,
                   gc.cochange_count
            FROM git_cochange gc
            JOIN files fa ON gc.file_id_a = fa.id
            JOIN files fb ON gc.file_id_b = fb.id
            ORDER BY gc.cochange_count DESC
            LIMIT ?
        """, (count,)).fetchall()

        if not rows:
            click.echo("No co-change data available. Run `roam index` on a git repository.")
            return

        # Check which pairs have structural connections (file_edges)
        file_edge_set = set()
        fe_rows = conn.execute(
            "SELECT source_file_id, target_file_id FROM file_edges"
        ).fetchall()
        for fe in fe_rows:
            file_edge_set.add((fe["source_file_id"], fe["target_file_id"]))
            file_edge_set.add((fe["target_file_id"], fe["source_file_id"]))

        # Build file path -> id lookup
        path_to_id = {}
        for f in conn.execute("SELECT id, path FROM files").fetchall():
            path_to_id[f["path"]] = f["id"]

        table_rows = []
        for r in rows:
            path_a = r["path_a"]
            path_b = r["path_b"]
            cochange = r["cochange_count"]
            fid_a = path_to_id.get(path_a)
            fid_b = path_to_id.get(path_b)

            has_edge = ""
            if fid_a and fid_b:
                if (fid_a, fid_b) in file_edge_set:
                    has_edge = "yes"
                else:
                    has_edge = "HIDDEN"

            table_rows.append([str(cochange), has_edge, path_a, path_b])

        click.echo("=== Temporal coupling (co-change frequency) ===")
        click.echo(format_table(
            ["co-changes", "structural?", "file A", "file B"],
            table_rows,
        ))

        hidden_count = sum(1 for r in table_rows if r[1] == "HIDDEN")
        if hidden_count:
            click.echo(f"\n{hidden_count} pairs have NO import edge but co-change frequently (hidden coupling).")

"""Find symbols matching a name substring (case-insensitive)."""

import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import SEARCH_SYMBOLS
from roam.output.formatter import abbrev_kind, loc, format_table, KIND_ABBREV, to_json


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.argument('pattern')
@click.option('--full', is_flag=True, help='Show all results without truncation')
@click.option('-k', '--kind', 'kind_filter', default=None,
              help='Filter by symbol kind (fn, cls, meth, var, iface, etc.)')
@click.pass_context
def search(ctx, pattern, full, kind_filter):
    """Find symbols matching a name substring (case-insensitive)."""
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()
    like_pattern = f"%{pattern}%"
    with open_db(readonly=True) as conn:
        rows = conn.execute(SEARCH_SYMBOLS, (like_pattern, 9999 if full else 50)).fetchall()

        if kind_filter:
            abbrev_to_kind = {v: k for k, v in KIND_ABBREV.items()}
            full_kind = abbrev_to_kind.get(kind_filter, kind_filter)
            rows = [r for r in rows if r["kind"] == full_kind]

        if not rows:
            suffix = f" of kind '{kind_filter}'" if kind_filter else ""
            if json_mode:
                click.echo(to_json({"pattern": pattern, "results": []}))
            else:
                click.echo(f"No symbols matching '{pattern}'{suffix}")
            return

        # Batch-fetch incoming edge counts
        sym_ids = [r["id"] for r in rows]
        ref_counts = {}
        for i in range(0, len(sym_ids), 500):
            batch = sym_ids[i:i + 500]
            ph = ",".join("?" for _ in batch)
            for rc in conn.execute(
                f"SELECT target_id, COUNT(*) as cnt FROM edges "
                f"WHERE target_id IN ({ph}) GROUP BY target_id",
                batch,
            ).fetchall():
                ref_counts[rc["target_id"]] = rc["cnt"]

        if json_mode:
            click.echo(to_json({
                "pattern": pattern,
                "total": len(rows),
                "results": [
                    {
                        "name": r["name"],
                        "kind": r["kind"],
                        "refs": ref_counts.get(r["id"], 0),
                        "location": loc(r["file_path"], r["line_start"]),
                    }
                    for r in rows
                ],
            }))
            return

        # --- Text output ---
        total = len(rows)
        if not full and total == 50:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM symbols WHERE name LIKE ? COLLATE NOCASE",
                (like_pattern,),
            ).fetchone()[0]
            click.echo(f"=== Symbols matching '{pattern}' ({total} of {cnt}, use --full for all) ===")
        else:
            click.echo(f"=== Symbols matching '{pattern}' ({total}) ===")

        table_rows = []
        for r in rows:
            refs = ref_counts.get(r["id"], 0)
            table_rows.append([
                r["name"],
                abbrev_kind(r["kind"]),
                str(refs),
                loc(r["file_path"], r["line_start"]),
            ])
        click.echo(format_table(
            ["Name", "Kind", "Refs", "Location"],
            table_rows,
            budget=0 if full else 50,
        ))

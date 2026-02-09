import time
from collections import Counter

import click


@click.command()
@click.option('--force', is_flag=True, help='Force full reindex')
@click.option('--verbose', is_flag=True, help='Show detailed warnings during indexing')
def index(force, verbose):
    """Build or rebuild the codebase index."""
    from roam.index.indexer import Indexer
    from roam.db.connection import open_db, db_exists
    t0 = time.monotonic()
    indexer = Indexer()
    indexer.run(force=force, verbose=verbose)
    elapsed = time.monotonic() - t0
    click.echo(f"Index complete. ({elapsed:.1f}s)")

    # Show summary stats
    if db_exists():
        with open_db(readonly=True) as conn:
            file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            sym_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

            lang_rows = conn.execute(
                "SELECT language, COUNT(*) as cnt FROM files WHERE language IS NOT NULL GROUP BY language ORDER BY cnt DESC"
            ).fetchall()
            lang_str = ", ".join(f"{r['language']}={r['cnt']}" for r in lang_rows[:8])

            avg_sym = f"{sym_count / file_count:.1f}" if file_count else "0"

            # Parse error rate
            parsed_ok = conn.execute(
                "SELECT COUNT(*) FROM files WHERE id IN (SELECT DISTINCT file_id FROM symbols)"
            ).fetchone()[0]
            error_pct = (file_count - parsed_ok) * 100 / file_count if file_count else 0

            click.echo(f"  Files: {file_count}  Symbols: {sym_count}  Edges: {edge_count}")
            click.echo(f"  Languages: {lang_str}")
            click.echo(f"  Avg symbols/file: {avg_sym}  Parse coverage: {100 - error_pct:.0f}%")

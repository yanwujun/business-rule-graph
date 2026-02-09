import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import (
    SYMBOL_BY_NAME, SYMBOL_BY_QUALIFIED, SEARCH_SYMBOLS,
    CALLERS_OF, CALLEES_OF, METRICS_FOR_SYMBOL,
)
from roam.output.formatter import (
    abbrev_kind, loc, format_signature, format_edge_kind,
    truncate_lines, section,
)


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


def _find_symbol(conn, name):
    """Find a symbol by exact name, qualified name, or fuzzy match."""
    row = conn.execute(SYMBOL_BY_QUALIFIED, (name,)).fetchone()
    if row:
        return row
    rows = conn.execute(SYMBOL_BY_NAME, (name,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        return rows  # Ambiguous
    rows = conn.execute(SEARCH_SYMBOLS, (f"%{name}%", 10)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if rows:
        return rows  # Ambiguous
    return None


@click.command()
@click.argument('name')
@click.option('--full', is_flag=True, help='Show all results without truncation')
def symbol(name, full):
    """Show symbol definition, callers, and callees."""
    _ensure_index()

    with open_db(readonly=True) as conn:
        result = _find_symbol(conn, name)

        if result is None:
            click.echo(f"Symbol not found: {name}")
            raise SystemExit(1)

        if isinstance(result, list):
            click.echo(f"Multiple matches for '{name}':")
            for s in result:
                click.echo(f"  {abbrev_kind(s['kind'])}  {s['qualified_name'] or s['name']}  {loc(s['file_path'], s['line_start'])}")
            click.echo("Use a qualified name to disambiguate.")
            return

        s = result
        # --- Definition ---
        sig = format_signature(s["signature"])
        click.echo(f"{abbrev_kind(s['kind'])}  {s['qualified_name'] or s['name']}")
        if sig:
            click.echo(f"  {sig}")
        click.echo(f"  {loc(s['file_path'], s['line_start'])}")

        if s["docstring"]:
            doc_lines = s["docstring"].strip().splitlines()
            if not full:
                doc_lines = truncate_lines(doc_lines, 5)
            for dl in doc_lines:
                click.echo(f"  | {dl}")

        # --- PageRank ---
        metrics = conn.execute(METRICS_FOR_SYMBOL, (s["id"],)).fetchone()
        if metrics:
            click.echo(f"  PR={metrics['pagerank']:.4f}  in={metrics['in_degree']}  out={metrics['out_degree']}")

        # --- Callers ---
        callers = conn.execute(CALLERS_OF, (s["id"],)).fetchall()
        if callers:
            # Dedup by source symbol: prefer call > inherits > implements > import
            _EDGE_PRIORITY = {"call": 0, "inherits": 1, "implements": 2, "import": 3}
            best = {}
            for c in callers:
                sid = c["id"]
                prio = _EDGE_PRIORITY.get(c["edge_kind"], 1)
                if sid not in best or prio < best[sid][1]:
                    best[sid] = (c, prio)
            deduped = [v[0] for v in best.values()]
            lines = []
            for c in deduped:
                edge = format_edge_kind(c["edge_kind"])
                lines.append(f"  {abbrev_kind(c['kind'])}  {c['name']}  ({edge})  {loc(c['file_path'], c['edge_line'])}")
            click.echo(section(f"Callers ({len(deduped)}):", lines, budget=0 if full else 15))

        # --- Callees ---
        callees = conn.execute(CALLEES_OF, (s["id"],)).fetchall()
        if callees:
            # Dedup by target symbol: prefer call > inherits > implements > import
            best = {}
            for c in callees:
                sid = c["id"]
                prio = _EDGE_PRIORITY.get(c["edge_kind"], 1)
                if sid not in best or prio < best[sid][1]:
                    best[sid] = (c, prio)
            deduped = [v[0] for v in best.values()]
            lines = []
            for c in deduped:
                edge = format_edge_kind(c["edge_kind"])
                lines.append(f"  {abbrev_kind(c['kind'])}  {c['name']}  ({edge})  {loc(c['file_path'], c['edge_line'])}")
            click.echo(section(f"Callees ({len(deduped)}):", lines, budget=0 if full else 15))

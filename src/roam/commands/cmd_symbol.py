import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import (
    SYMBOL_BY_NAME, SYMBOL_BY_QUALIFIED, SEARCH_SYMBOLS,
    CALLERS_OF, CALLEES_OF, METRICS_FOR_SYMBOL,
)
from roam.output.formatter import (
    abbrev_kind, loc, format_signature, format_edge_kind,
    truncate_lines, section, to_json,
)

_EDGE_PRIORITY = {"call": 0, "template": 0, "inherits": 1, "implements": 2, "import": 3}


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


def _pick_best(conn, rows):
    """Pick the most-referenced symbol from ambiguous matches."""
    ids = [r["id"] for r in rows]
    ph = ",".join("?" for _ in ids)
    counts = conn.execute(
        f"SELECT target_id, COUNT(*) as cnt FROM edges "
        f"WHERE target_id IN ({ph}) GROUP BY target_id",
        ids,
    ).fetchall()
    ref_map = {c["target_id"]: c["cnt"] for c in counts}
    best = max(rows, key=lambda r: ref_map.get(r["id"], 0))
    if ref_map.get(best["id"], 0) > 0:
        return best
    return None


def _find_symbol(conn, name):
    """Find a symbol by exact name, qualified name, or fuzzy match."""
    rows = conn.execute(SYMBOL_BY_QUALIFIED, (name,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        best = _pick_best(conn, rows)
        if best:
            return best
        return rows
    rows = conn.execute(SYMBOL_BY_NAME, (name,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        best = _pick_best(conn, rows)
        if best:
            return best
        return rows
    rows = conn.execute(SEARCH_SYMBOLS, (f"%{name}%", 10)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if rows:
        best = _pick_best(conn, rows)
        if best:
            return best
        return rows
    return None


def _dedup_edges(edges):
    """Dedup edges by symbol, preferring call > inherits > implements > import."""
    best = {}
    for c in edges:
        sid = c["id"]
        prio = _EDGE_PRIORITY.get(c["edge_kind"], 1)
        if sid not in best or prio < best[sid][1]:
            best[sid] = (c, prio)
    return [v[0] for v in best.values()]


@click.command()
@click.argument('name')
@click.option('--full', is_flag=True, help='Show all results without truncation')
@click.pass_context
def symbol(ctx, name, full):
    """Show symbol definition, callers, and callees."""
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()

    with open_db(readonly=True) as conn:
        result = _find_symbol(conn, name)

        if result is None:
            click.echo(f"Symbol not found: {name}")
            raise SystemExit(1)

        if isinstance(result, list):
            if json_mode:
                click.echo(to_json({
                    "error": "ambiguous",
                    "matches": [
                        {"name": s["qualified_name"] or s["name"], "kind": s["kind"],
                         "location": loc(s["file_path"], s["line_start"])}
                        for s in result
                    ],
                }))
                return
            click.echo(f"Multiple matches for '{name}':")
            for s in result:
                click.echo(f"  {abbrev_kind(s['kind'])}  {s['qualified_name'] or s['name']}  {loc(s['file_path'], s['line_start'])}")
            click.echo("Use a qualified name to disambiguate.")
            return

        s = result
        metrics = conn.execute(METRICS_FOR_SYMBOL, (s["id"],)).fetchone()
        callers = conn.execute(CALLERS_OF, (s["id"],)).fetchall()
        callees = conn.execute(CALLEES_OF, (s["id"],)).fetchall()
        deduped_callers = _dedup_edges(callers) if callers else []
        deduped_callees = _dedup_edges(callees) if callees else []

        if json_mode:
            data = {
                "name": s["qualified_name"] or s["name"],
                "kind": s["kind"],
                "signature": s["signature"] or "",
                "location": loc(s["file_path"], s["line_start"]),
                "docstring": s["docstring"] or "",
            }
            if metrics:
                data["pagerank"] = round(metrics["pagerank"], 4)
                data["in_degree"] = metrics["in_degree"]
                data["out_degree"] = metrics["out_degree"]
            data["callers"] = [
                {"name": c["name"], "kind": c["kind"], "edge_kind": c["edge_kind"],
                 "location": loc(c["file_path"], c["edge_line"])}
                for c in deduped_callers
            ]
            data["callees"] = [
                {"name": c["name"], "kind": c["kind"], "edge_kind": c["edge_kind"],
                 "location": loc(c["file_path"], c["edge_line"])}
                for c in deduped_callees
            ]
            click.echo(to_json(data))
            return

        # --- Text output ---
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

        if metrics:
            click.echo(f"  PR={metrics['pagerank']:.4f}  in={metrics['in_degree']}  out={metrics['out_degree']}")

        if deduped_callers:
            lines = []
            for c in deduped_callers:
                edge = format_edge_kind(c["edge_kind"])
                lines.append(f"  {abbrev_kind(c['kind'])}  {c['name']}  ({edge})  {loc(c['file_path'], c['edge_line'])}")
            click.echo(section(f"Callers ({len(deduped_callers)}):", lines, budget=0 if full else 15))

        if deduped_callees:
            lines = []
            for c in deduped_callees:
                edge = format_edge_kind(c["edge_kind"])
                lines.append(f"  {abbrev_kind(c['kind'])}  {c['name']}  ({edge})  {loc(c['file_path'], c['edge_line'])}")
            click.echo(section(f"Callees ({len(deduped_callees)}):", lines, budget=0 if full else 15))

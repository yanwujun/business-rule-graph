import click

from roam.db.connection import open_db, db_exists
from roam.output.formatter import abbrev_kind, loc, to_json


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.argument('source')
@click.argument('target')
@click.pass_context
def trace(ctx, source, target):
    """Show shortest path between two symbols."""
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()

    from roam.graph.builder import build_symbol_graph
    from roam.graph.pathfinding import find_path, find_symbol_id, format_path

    with open_db(readonly=True) as conn:
        src_ids = find_symbol_id(conn, source)
        if not src_ids:
            click.echo(f"Source symbol not found: {source}")
            raise SystemExit(1)

        tgt_ids = find_symbol_id(conn, target)
        if not tgt_ids:
            click.echo(f"Target symbol not found: {target}")
            raise SystemExit(1)

        G = build_symbol_graph(conn)

        best = None
        for sid in src_ids:
            for tid in tgt_ids:
                p = find_path(G, sid, tid)
                if p and (best is None or len(p) < len(best)):
                    best = p

        if best is None:
            if json_mode:
                click.echo(to_json({"source": source, "target": target, "path": None}))
            else:
                click.echo(f"No path from '{source}' to '{target}'.")
            return

        annotated = format_path(best, conn)

        # Build edge kinds for each hop
        hops = []
        for i, node in enumerate(annotated):
            hop = {"name": node["name"], "kind": node["kind"],
                   "location": loc(node["file_path"], node["line"])}
            if i > 0:
                prev_id = best[i - 1]
                curr_id = best[i]
                edge_kind = G.edges.get((prev_id, curr_id), {}).get("kind", "")
                if not edge_kind:
                    edge_kind = G.edges.get((curr_id, prev_id), {}).get("kind", "")
                hop["edge_kind"] = edge_kind
            hops.append(hop)

        if json_mode:
            click.echo(to_json({"source": source, "target": target, "hops": len(hops), "path": hops}))
            return

        # --- Text output ---
        click.echo(f"Path ({len(annotated)} hops):")
        for i, node in enumerate(annotated):
            if i == 0:
                click.echo(f"    {abbrev_kind(node['kind'])}  {node['name']}  {loc(node['file_path'], node['line'])}")
            else:
                edge_label = f"[{hops[i].get('edge_kind', '')}] " if hops[i].get("edge_kind") else ""
                click.echo(f"  -> {edge_label}{abbrev_kind(node['kind'])}  {node['name']}  {loc(node['file_path'], node['line'])}")

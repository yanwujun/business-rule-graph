"""Detect and report code health issues."""

import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import TOP_BY_DEGREE, TOP_BY_BETWEENNESS
from roam.graph.builder import build_symbol_graph
from roam.graph.cycles import find_cycles, format_cycles
from roam.graph.layers import detect_layers, find_violations
from roam.output.formatter import (
    abbrev_kind, loc, section, format_table, truncate_lines, to_json,
)


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.pass_context
def health(ctx):
    """Show code health: cycles, god components, bottlenecks."""
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()
    with open_db(readonly=True) as conn:
        G = build_symbol_graph(conn)

        # --- Cycles ---
        cycles = find_cycles(G)
        formatted_cycles = format_cycles(cycles, conn) if cycles else []

        # --- God components ---
        degree_rows = conn.execute(TOP_BY_DEGREE, (50,)).fetchall()
        god_items = []
        for r in degree_rows:
            total = (r["in_degree"] or 0) + (r["out_degree"] or 0)
            if total > 20:
                god_items.append({
                    "name": r["name"], "kind": r["kind"],
                    "degree": total, "file": r["file_path"],
                })

        # --- Bottlenecks ---
        bw_rows = conn.execute(TOP_BY_BETWEENNESS, (15,)).fetchall()
        bn_items = []
        for r in bw_rows:
            bw = r["betweenness"] or 0
            if bw > 0.5:
                bn_items.append({
                    "name": r["name"], "kind": r["kind"],
                    "betweenness": round(bw, 1), "file": r["file_path"],
                })

        # --- Layer violations ---
        layer_map = detect_layers(G)
        violations = find_violations(G, layer_map) if layer_map else []
        v_lookup = {}
        if violations:
            all_ids = {v["source"] for v in violations} | {v["target"] for v in violations}
            ph = ",".join("?" for _ in all_ids)
            for r in conn.execute(
                f"SELECT s.id, s.name, f.path as file_path "
                f"FROM symbols s JOIN files f ON s.file_id = f.id WHERE s.id IN ({ph})",
                list(all_ids),
            ).fetchall():
                v_lookup[r["id"]] = r

        if json_mode:
            click.echo(to_json({
                "cycles": [
                    {"size": c["size"], "symbols": [s["name"] for s in c["symbols"]],
                     "files": c["files"]}
                    for c in formatted_cycles
                ],
                "god_components": god_items,
                "bottlenecks": bn_items,
                "layer_violations": [
                    {
                        "source": v_lookup.get(v["source"], {}).get("name", "?"),
                        "source_layer": v["source_layer"],
                        "target": v_lookup.get(v["target"], {}).get("name", "?"),
                        "target_layer": v["target_layer"],
                    }
                    for v in violations
                ],
            }))
            return

        # --- Text output ---
        click.echo("=== Cycles ===")
        if formatted_cycles:
            for i, cyc in enumerate(formatted_cycles, 1):
                names = [s["name"] for s in cyc["symbols"]]
                click.echo(f"  cycle {i} ({cyc['size']} symbols): {', '.join(names[:10])}")
                if len(names) > 10:
                    click.echo(f"    (+{len(names) - 10} more)")
                click.echo(f"    files: {', '.join(cyc['files'][:5])}")
            click.echo(f"  total: {len(cycles)} cycle(s)")
        else:
            click.echo("  (none)")

        click.echo("\n=== God Components (degree > 20) ===")
        if god_items:
            god_rows = [[g["name"], abbrev_kind(g["kind"]), str(g["degree"]), loc(g["file"])]
                        for g in god_items]
            click.echo(format_table(["Name", "Kind", "Degree", "File"], god_rows, budget=20))
        else:
            click.echo("  (none)")

        click.echo("\n=== Bottlenecks (high betweenness) ===")
        if bn_items:
            bn_rows = []
            for b in bn_items:
                bw_str = f"{b['betweenness']:.0f}" if b["betweenness"] >= 10 else f"{b['betweenness']:.1f}"
                bn_rows.append([b["name"], abbrev_kind(b["kind"]), bw_str, loc(b["file"])])
            click.echo(format_table(["Name", "Kind", "Betweenness", "File"], bn_rows, budget=15))
        else:
            click.echo("  (none)")

        click.echo(f"\n=== Layer Violations ({len(violations)}) ===")
        if violations:
            v_rows = []
            for v in violations[:20]:
                src = v_lookup.get(v["source"], {})
                tgt = v_lookup.get(v["target"], {})
                v_rows.append([
                    src.get("name", "?"), f"L{v['source_layer']}",
                    tgt.get("name", "?"), f"L{v['target_layer']}",
                ])
            click.echo(format_table(["Source", "Layer", "Target", "Layer"], v_rows, budget=20))
            if len(violations) > 20:
                click.echo(f"  (+{len(violations) - 20} more)")
        elif layer_map:
            click.echo("  (none)")
        else:
            click.echo("  (no layers detected)")

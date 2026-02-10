"""Show topological layer detection and violations."""

import click

from roam.db.connection import open_db, db_exists
from roam.graph.builder import build_symbol_graph
from roam.graph.layers import detect_layers, find_violations, format_layers
from roam.output.formatter import abbrev_kind, loc, format_table, truncate_lines, to_json

import networkx as nx


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.pass_context
def layers(ctx):
    """Show dependency layers and violations."""
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()
    with open_db(readonly=True) as conn:
        G = build_symbol_graph(conn)
        layer_map = detect_layers(G)

        if not layer_map:
            if json_mode:
                click.echo(to_json({"layers": [], "violations": []}))
            else:
                click.echo("No layers detected (graph is empty).")
            return

        formatted = format_layers(layer_map, conn)
        max_layer = max(l["layer"] for l in formatted) if formatted else 0

        violations = find_violations(G, layer_map)

        if json_mode:
            # Lookup violation names
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

            click.echo(to_json({
                "total_layers": max_layer + 1,
                "layers": [
                    {
                        "layer": l["layer"],
                        "symbol_count": len(l["symbols"]),
                        "symbols": [
                            {"name": s["name"], "kind": s["kind"]}
                            for s in l["symbols"][:50]
                        ],
                    }
                    for l in formatted
                ],
                "violations": [
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

        total_symbols = sum(len(l["symbols"]) for l in formatted)
        layer0_count = next((len(l["symbols"]) for l in formatted if l["layer"] == 0), 0)
        layer0_pct = layer0_count * 100 / total_symbols if total_symbols else 0

        click.echo(f"=== Layers ({max_layer + 1} levels) ===")

        # Architectural summary
        if max_layer <= 1:
            shape = "Flat (no layering)"
        elif layer0_pct > 80:
            shape = f"Flat ({layer0_pct:.0f}% in Layer 0)"
        elif layer0_pct > 50:
            shape = f"Moderate ({layer0_pct:.0f}% in Layer 0, {max_layer + 1} levels)"
        else:
            shape = f"Well-layered ({max_layer + 1} levels, even distribution)"
        click.echo(f"  Architecture: {shape}")

        for layer_info in formatted:
            n = layer_info["layer"]
            symbols = layer_info["symbols"]
            if len(symbols) > 50:
                label = " base layer (no dependencies)" if n == 0 else ""
                click.echo(f"\n  Layer {n} ({len(symbols)} symbols):{label}")
            else:
                names = [f"{abbrev_kind(s['kind'])} {s['name']}" for s in symbols]
                preview = truncate_lines(names, 10)
                click.echo(f"\n  Layer {n} ({len(symbols)} symbols):")
                for line in preview:
                    click.echo(f"    {line}")

        # --- Deepest dependency chains (useful even for flat codebases) ---
        if max_layer >= 1:
            # Find the longest path in the DAG (condensation handles cycles)
            try:
                condensation = nx.condensation(G)
                longest = nx.dag_longest_path(condensation)
                if len(longest) > 1:
                    # Map SCC nodes back to original symbols (pick highest-degree from each SCC)
                    scc_members = condensation.graph.get("mapping", {})
                    # Reverse mapping: SCC id -> original node ids
                    scc_to_nodes: dict[int, list] = {}
                    for orig_node, scc_id in scc_members.items():
                        scc_to_nodes.setdefault(scc_id, []).append(orig_node)

                    chain_ids = []
                    for scc_id in longest:
                        members = scc_to_nodes.get(scc_id, [])
                        if members:
                            # Pick the highest-degree member as representative
                            best = max(members, key=lambda n: G.degree(n) if n in G else 0)
                            chain_ids.append(best)

                    # Look up names
                    if chain_ids:
                        ph = ",".join("?" for _ in chain_ids)
                        chain_rows = conn.execute(
                            f"SELECT s.id, s.name, s.kind, f.path as file_path "
                            f"FROM symbols s JOIN files f ON s.file_id = f.id "
                            f"WHERE s.id IN ({ph})",
                            chain_ids,
                        ).fetchall()
                        chain_lookup = {r["id"]: r for r in chain_rows}
                        click.echo(f"\n  Deepest dependency chain ({len(chain_ids)} levels):")
                        for i, cid in enumerate(chain_ids):
                            info = chain_lookup.get(cid)
                            if info:
                                arrow = "    " if i == 0 else "  -> "
                                click.echo(f"  {arrow}{abbrev_kind(info['kind'])} {info['name']}  {loc(info['file_path'])}")
            except Exception:
                pass

        # --- Violations ---
        click.echo(f"\n=== Violations ({len(violations)}) ===")
        if violations:
            all_ids = {v["source"] for v in violations} | {v["target"] for v in violations}
            ph = ",".join("?" for _ in all_ids)
            rows = conn.execute(
                f"SELECT s.id, s.name, s.kind, f.path as file_path "
                f"FROM symbols s JOIN files f ON s.file_id = f.id "
                f"WHERE s.id IN ({ph})",
                list(all_ids),
            ).fetchall()
            lookup = {r["id"]: r for r in rows}

            v_rows = []
            for v in violations[:30]:
                src = lookup.get(v["source"], {})
                tgt = lookup.get(v["target"], {})
                v_rows.append([
                    src.get("name", "?"),
                    f"L{v['source_layer']}",
                    "->",
                    tgt.get("name", "?"),
                    f"L{v['target_layer']}",
                    loc(src.get("file_path", "?")),
                ])
            click.echo(format_table(
                ["Source", "Layer", "", "Target", "Layer", "File"],
                v_rows,
                budget=30,
            ))
            if len(violations) > 30:
                click.echo(f"  (+{len(violations) - 30} more)")
        else:
            click.echo("  (none -- clean layering)")

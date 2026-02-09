"""Show topological layer detection and violations."""

import click

from roam.db.connection import open_db, db_exists
from roam.graph.builder import build_symbol_graph
from roam.graph.layers import detect_layers, find_violations, format_layers
from roam.output.formatter import abbrev_kind, loc, format_table, truncate_lines


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
def layers():
    """Show dependency layers and violations."""
    _ensure_index()
    with open_db(readonly=True) as conn:
        G = build_symbol_graph(conn)
        layer_map = detect_layers(G)

        if not layer_map:
            click.echo("No layers detected (graph is empty).")
            return

        formatted = format_layers(layer_map, conn)
        max_layer = max(l["layer"] for l in formatted) if formatted else 0

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

        # --- Violations ---
        violations = find_violations(G, layer_map)
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

"""Show detected clusters and directory mismatches."""

import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import ALL_CLUSTERS
from roam.graph.clusters import compare_with_directories
from roam.output.formatter import format_table, to_json


def _ensure_index():
    from roam.db.connection import db_exists
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.option('--min-size', default=3, show_default=True, help='Hide clusters smaller than this')
@click.pass_context
def clusters(ctx, min_size):
    """Show code clusters and directory mismatches."""
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()
    with open_db(readonly=True) as conn:
        rows = conn.execute(ALL_CLUSTERS).fetchall()

        if json_mode:
            visible = [r for r in rows if r["size"] >= min_size]
            mismatches = compare_with_directories(conn)
            visible_ids = {r["cluster_id"] for r in visible}
            click.echo(to_json({
                "clusters": [
                    {
                        "id": r["cluster_id"],
                        "label": r["cluster_label"],
                        "size": r["size"],
                        "members": r["members"] or "",
                    }
                    for r in visible
                ],
                "mismatches": [
                    {
                        "cluster_id": m["cluster_id"],
                        "label": m["cluster_label"],
                        "mismatch_count": m["mismatch_count"],
                        "directories": m["directories"],
                    }
                    for m in mismatches if m["cluster_id"] in visible_ids
                ],
            }))
            return

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

        # --- Cluster cohesion and coupling ---
        if visible:
            # Build symbol -> cluster mapping for visible clusters
            cluster_rows = conn.execute(
                "SELECT symbol_id, cluster_id FROM clusters"
            ).fetchall()
            sym_to_cluster = {r["symbol_id"]: r["cluster_id"] for r in cluster_rows}

            # Count intra-cluster and inter-cluster edges
            edges = conn.execute("SELECT source_id, target_id FROM edges").fetchall()
            intra_count: dict[int, int] = {}
            inter_pairs: dict[tuple, int] = {}
            for e in edges:
                c_src = sym_to_cluster.get(e["source_id"])
                c_tgt = sym_to_cluster.get(e["target_id"])
                if c_src is None or c_tgt is None:
                    continue
                if c_src == c_tgt:
                    intra_count[c_src] = intra_count.get(c_src, 0) + 1
                else:
                    pair = (min(c_src, c_tgt), max(c_src, c_tgt))
                    inter_pairs[pair] = inter_pairs.get(pair, 0) + 1

            total_intra = sum(intra_count.values())
            total_inter = sum(inter_pairs.values())
            total_all = total_intra + total_inter
            cohesion_pct = total_intra * 100 / total_all if total_all else 0
            click.echo(f"\n  Cluster cohesion: {cohesion_pct:.0f}% edges are intra-cluster ({total_intra} internal, {total_inter} cross-cluster)")

            # Top inter-cluster coupling pairs
            if inter_pairs:
                visible_pairs = {k: v for k, v in inter_pairs.items()
                                 if k[0] in visible_ids and k[1] in visible_ids}
                top_inter = sorted(visible_pairs.items(), key=lambda x: -x[1])[:10]
                if top_inter:
                    # Get cluster labels
                    cl_labels = {r["cluster_id"]: r["cluster_label"] for r in rows}
                    click.echo(f"\n=== Inter-Cluster Coupling (top pairs) ===")
                    ic_rows = []
                    for (ca, cb), cnt in top_inter:
                        ic_rows.append([
                            cl_labels.get(ca, f"c{ca}"),
                            cl_labels.get(cb, f"c{cb}"),
                            str(cnt),
                        ])
                    click.echo(format_table(["Cluster A", "Cluster B", "Edges"], ic_rows))

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

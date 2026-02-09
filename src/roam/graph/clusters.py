"""Louvain community detection for the symbol graph."""

from __future__ import annotations

import os
import sqlite3
from collections import Counter, defaultdict

import networkx as nx


def detect_clusters(G: nx.DiGraph) -> dict[int, int]:
    """Detect communities using Louvain on the undirected projection of *G*.

    Falls back to greedy modularity if Louvain is unavailable.
    Returns ``{node_id: cluster_id}``.
    """
    if len(G) == 0:
        return {}

    undirected = G.to_undirected()

    # Remove isolates -- community detection on disconnected singletons just
    # assigns each its own community, which is not useful.
    communities: list[set[int]] = []
    try:
        communities = list(nx.community.louvain_communities(undirected, seed=42))
    except (AttributeError, TypeError):
        # NetworkX < 3.1 or missing optional dependency
        communities = list(nx.community.greedy_modularity_communities(undirected))

    mapping: dict[int, int] = {}
    for cluster_id, members in enumerate(communities):
        for node in members:
            mapping[node] = cluster_id
    return mapping


def label_clusters(
    clusters: dict[int, int], conn: sqlite3.Connection
) -> dict[int, str]:
    """Generate human-readable labels for clusters.

    Uses the highest-PageRank symbol in each cluster as the label,
    falling back to the most common directory prefix.
    Returns ``{cluster_id: label}``.
    """
    if not clusters:
        return {}

    # Group symbols by cluster
    groups: dict[int, list[int]] = defaultdict(list)
    for node_id, cid in clusters.items():
        groups[cid].append(node_id)

    # Fetch file paths and pagerank for all symbols in one query
    all_ids = list(clusters.keys())
    placeholders = ",".join("?" for _ in all_ids)
    rows = conn.execute(
        f"SELECT s.id, s.name, f.path, COALESCE(gm.pagerank, 0) as pagerank "
        f"FROM symbols s "
        f"JOIN files f ON s.file_id = f.id "
        f"LEFT JOIN graph_metrics gm ON s.id = gm.symbol_id "
        f"WHERE s.id IN ({placeholders})",
        all_ids,
    ).fetchall()
    id_to_path: dict[int, str] = {}
    id_to_info: dict[int, dict] = {}
    for r in rows:
        id_to_path[r["id"]] = r["path"]
        id_to_info[r["id"]] = {"name": r["name"], "pagerank": r["pagerank"]}

    labels: dict[int, str] = {}
    for cid, members in groups.items():
        # Try to use the highest-PageRank symbol as the label
        best_name = None
        best_pr = -1
        for m in members:
            info = id_to_info.get(m)
            if info and info["pagerank"] > best_pr:
                best_pr = info["pagerank"]
                best_name = info["name"]

        if best_name and best_pr > 0:
            # Add directory context for disambiguation
            dirs = [
                os.path.dirname(id_to_path[m]).replace("\\", "/")
                for m in members if m in id_to_path
            ]
            if dirs:
                most_common_dir = Counter(dirs).most_common(1)[0][0]
                short_dir = most_common_dir.rstrip("/").rsplit("/", 1)[-1] if most_common_dir else ""
                labels[cid] = f"{best_name} ({short_dir})" if short_dir else best_name
            else:
                labels[cid] = best_name
        else:
            # Fallback: directory-based label
            dirs = [
                os.path.dirname(id_to_path[m]).replace("\\", "/")
                for m in members if m in id_to_path
            ]
            if not dirs:
                labels[cid] = f"cluster-{cid}"
                continue
            most_common_dir = Counter(dirs).most_common(1)[0][0]
            short = most_common_dir.rstrip("/").rsplit("/", 1)[-1] if most_common_dir else "root"
            labels[cid] = short or f"cluster-{cid}"
    return labels


def store_clusters(
    conn: sqlite3.Connection,
    clusters: dict[int, int],
    labels: dict[int, str],
) -> int:
    """Persist cluster assignments into the ``clusters`` table.

    Returns the number of rows written.
    """
    if not clusters:
        return 0

    rows = [
        (node_id, cid, labels.get(cid, f"cluster-{cid}"))
        for node_id, cid in clusters.items()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO clusters (symbol_id, cluster_id, cluster_label) "
        "VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def compare_with_directories(conn: sqlite3.Connection) -> list[dict]:
    """Compare detected clusters with the directory tree.

    A *mismatch* means symbols in the same cluster live in different
    directories.  Returns a list of dicts::

        [
            {
                "cluster_id": 0,
                "cluster_label": "utils",
                "directories": ["src/utils", "src/core"],
                "mismatch_count": 5,
            },
            ...
        ]
    """
    rows = conn.execute(
        "SELECT c.cluster_id, c.cluster_label, f.path "
        "FROM clusters c "
        "JOIN symbols s ON c.symbol_id = s.id "
        "JOIN files f ON s.file_id = f.id"
    ).fetchall()

    if not rows:
        return []

    cluster_dirs: dict[int, dict] = defaultdict(lambda: {"label": "", "dirs": []})
    for cid, label, path in rows:
        d = os.path.dirname(path).replace("\\", "/")
        entry = cluster_dirs[cid]
        entry["label"] = label
        entry["dirs"].append(d)

    result = []
    for cid, info in sorted(cluster_dirs.items()):
        unique_dirs = sorted(set(info["dirs"]))
        if len(unique_dirs) > 1:
            # Count symbols that are NOT in the majority directory
            dir_counts = Counter(info["dirs"])
            majority_count = dir_counts.most_common(1)[0][1]
            mismatch_count = len(info["dirs"]) - majority_count
            result.append({
                "cluster_id": cid,
                "cluster_label": info["label"],
                "directories": unique_dirs,
                "mismatch_count": mismatch_count,
            })

    result.sort(key=lambda r: r["mismatch_count"], reverse=True)
    return result

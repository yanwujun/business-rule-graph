"""Shortest-path utilities for the ``roam trace`` command."""

from __future__ import annotations

import sqlite3

import networkx as nx


def find_path(
    G: nx.DiGraph, source_id: int, target_id: int
) -> list[int] | None:
    """Find the shortest path from *source_id* to *target_id*.

    Tries the directed graph first; if no directed path exists, falls back to
    the undirected projection.  Returns ``None`` when no path exists at all.
    """
    if source_id not in G or target_id not in G:
        return None

    # Directed attempt
    try:
        return list(nx.shortest_path(G, source_id, target_id))
    except nx.NetworkXNoPath:
        pass

    # Undirected fallback
    try:
        undirected = G.to_undirected()
        return list(nx.shortest_path(undirected, source_id, target_id))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def find_symbol_id(conn: sqlite3.Connection, name: str) -> list[int]:
    """Find symbol IDs matching *name*.

    Searches by exact ``name`` first, then by ``qualified_name``.  If neither
    matches, performs a ``LIKE`` search.  Returns a (possibly empty) list of
    matching symbol IDs.
    """
    # Exact name match
    rows = conn.execute(
        "SELECT id FROM symbols WHERE name = ?", (name,)
    ).fetchall()
    if rows:
        return [r[0] for r in rows]

    # Exact qualified name match
    rows = conn.execute(
        "SELECT id FROM symbols WHERE qualified_name = ?", (name,)
    ).fetchall()
    if rows:
        return [r[0] for r in rows]

    # Fuzzy / LIKE search
    rows = conn.execute(
        "SELECT id FROM symbols WHERE name LIKE ? OR qualified_name LIKE ? LIMIT 50",
        (f"%{name}%", f"%{name}%"),
    ).fetchall()
    return [r[0] for r in rows]


def format_path(
    path: list[int], conn: sqlite3.Connection
) -> list[dict]:
    """Annotate a node-ID path with symbol metadata.

    Returns::

        [
            {"id": 1, "name": "foo", "kind": "function",
             "file_path": "src/a.py", "line": 42},
            ...
        ]
    """
    if not path:
        return []

    placeholders = ",".join("?" for _ in path)
    rows = conn.execute(
        f"SELECT s.id, s.name, s.kind, f.path AS file_path, s.line_start "
        f"FROM symbols s JOIN files f ON s.file_id = f.id "
        f"WHERE s.id IN ({placeholders})",
        path,
    ).fetchall()

    lookup: dict[int, dict] = {}
    for sid, name, kind, fpath, line in rows:
        lookup[sid] = {
            "id": sid,
            "name": name,
            "kind": kind,
            "file_path": fpath,
            "line": line,
        }

    # Preserve path order
    return [lookup[nid] for nid in path if nid in lookup]

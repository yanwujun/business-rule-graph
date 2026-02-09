"""Build NetworkX graphs from the Roam SQLite index."""

from __future__ import annotations

import sqlite3

import networkx as nx


def build_symbol_graph(conn: sqlite3.Connection) -> nx.DiGraph:
    """Build a directed graph from symbol edges.

    Nodes are symbol IDs with attributes: name, kind, file_path, qualified_name.
    Edges carry a ``kind`` attribute (calls, imports, inherits, etc.).
    """
    G = nx.DiGraph()

    # Load nodes
    rows = conn.execute(
        "SELECT s.id, s.name, s.kind, s.qualified_name, f.path AS file_path "
        "FROM symbols s JOIN files f ON s.file_id = f.id"
    ).fetchall()
    for row in rows:
        sid, name, kind, qname, fpath = row
        G.add_node(sid, name=name, kind=kind, qualified_name=qname, file_path=fpath)

    # Load edges
    rows = conn.execute("SELECT source_id, target_id, kind FROM edges").fetchall()
    for source_id, target_id, kind in rows:
        # Only add edges whose endpoints exist in the graph
        if source_id in G and target_id in G:
            G.add_edge(source_id, target_id, kind=kind)

    return G


def build_file_graph(conn: sqlite3.Connection) -> nx.DiGraph:
    """Build a directed graph from file-level edges.

    Nodes are file IDs with attributes: path, language.
    Edges carry ``kind`` and ``symbol_count`` attributes.
    """
    G = nx.DiGraph()

    rows = conn.execute("SELECT id, path, language FROM files").fetchall()
    for fid, path, language in rows:
        G.add_node(fid, path=path, language=language)

    rows = conn.execute(
        "SELECT source_file_id, target_file_id, kind, symbol_count FROM file_edges"
    ).fetchall()
    for src, tgt, kind, sym_count in rows:
        if src in G and tgt in G:
            G.add_edge(src, tgt, kind=kind, symbol_count=sym_count)

    return G

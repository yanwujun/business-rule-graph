"""Dashboard HTTP server + JSON graph export for Roam.

Serves a single-file interactive dashboard that reads the codebase
graph from the Roam SQLite index.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

import networkx as nx

from roam.db.connection import open_db
from roam.graph.builder import build_file_graph, build_symbol_graph
from roam.graph.layers import detect_layers

logger = logging.getLogger(__name__)

# Path to the single-file HTML frontend template
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_INDEX_HTML = _TEMPLATE_DIR / "index.html"


def export_graph_json(db_path: str) -> dict[str, Any]:
    """Export the Roam index as a rich JSON graph suitable for the dashboard.

    Returns a dict with:
        project: {name, root, total_symbols, total_files, languages}
        nodes: [{id, name, kind, file, line, complexity, pagerank, ...}]
        edges: [{source, target, kind, weight}]
        layers: [{name, nodes: [...]}]
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        project_name = Path(db_path).parent.parent.name
        root = str(Path(db_path).parent.parent)

        # --- Project stats ---
        total_symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        languages = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT language FROM files WHERE language IS NOT NULL ORDER BY language"
            ).fetchall()
        ]

        project = {
            "name": project_name,
            "root": root,
            "total_symbols": total_symbols,
            "total_files": total_files,
            "languages": languages,
        }

        # --- Nodes: symbols (top 2000 by pagerank) ---
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.kind, s.qualified_name,
                   f.path AS file_path,
                   s.line_start, s.line_end,
                   COALESCE(gm.pagerank, 0) AS pagerank,
                   COALESCE(sm.cognitive_complexity, 0) AS complexity,
                   COALESCE(fs.health_score, 100) AS health_score,
                   s.visibility
            FROM symbols s
            JOIN files f ON s.file_id = f.id
            LEFT JOIN graph_metrics gm ON s.id = gm.symbol_id
            LEFT JOIN symbol_metrics sm ON s.id = sm.symbol_id
            LEFT JOIN file_stats fs ON f.id = fs.file_id
            ORDER BY COALESCE(gm.pagerank, 0) DESC
            LIMIT 2000
        """
        ).fetchall()

        nodes = []
        for r in rows:
            nodes.append(
                {
                    "id": f"symbol:{r['id']}",
                    "name": r["name"],
                    "kind": r["kind"],
                    "qualified_name": r["qualified_name"] or r["name"],
                    "file": r["file_path"],
                    "line": r["line_start"],
                    "line_end": r["line_end"],
                    "pagerank": round(r["pagerank"], 5),
                    "complexity": round(r["complexity"], 1),
                    "health_score": round(r["health_score"], 1) if r["health_score"] else None,
                    "visibility": r["visibility"],
                    "node_type": "symbol",
                }
            )

        # --- Nodes: files (only those with top symbols) ---
        symbol_file_ids = {(r[0], r[1]) for r in rows}
        file_paths = {fp for (_, fp) in symbol_file_ids}
        file_placeholders = ",".join("?" for _ in file_paths) if file_paths else "''"
        if file_paths:
            file_rows = conn.execute(
                f"""
                SELECT f.id, f.path, f.language, f.line_count,
                       COALESCE(fs.complexity, 0) AS complexity,
                       COALESCE(fs.health_score, 100) AS health_score
                FROM files f
                LEFT JOIN file_stats fs ON f.id = fs.file_id
                WHERE f.path IN ({file_placeholders})
                ORDER BY f.id
                """,
                list(file_paths),
            ).fetchall()
        else:
            file_rows = []

        for r in file_rows:
            nodes.append(
                {
                    "id": f"file:{r['path']}",
                    "name": Path(r["path"]).name,
                    "kind": "file",
                    "file": r["path"],
                    "language": r["language"] or "",
                    "line_count": r["line_count"],
                    "complexity": round(r["complexity"], 1),
                    "health_score": round(r["health_score"], 1) if r["health_score"] else None,
                    "pagerank": 0,
                    "node_type": "file",
                }
            )

        # --- Edges: symbol edges ---
        edge_rows = conn.execute(
            """
            SELECT
                'symbol:' || e.source_id AS source,
                'symbol:' || e.target_id AS target,
                e.kind, e.confidence
            FROM edges e
            ORDER BY e.source_id, e.target_id
        """
        ).fetchall()

        edges = []
        for r in edge_rows:
            edges.append(
                {
                    "source": r["source"],
                    "target": r["target"],
                    "kind": r["kind"],
                    "weight": round(r["confidence"] if r["confidence"] else 0.5, 2),
                }
            )

        # --- Edges: file edges ---
        fe_rows = conn.execute(
            """
            SELECT
                'file:' || f1.path AS source,
                'file:' || f2.path AS target,
                fe.kind, fe.symbol_count
            FROM file_edges fe
            JOIN files f1 ON fe.source_file_id = f1.id
            JOIN files f2 ON fe.target_file_id = f2.id
            ORDER BY fe.source_file_id, fe.target_file_id
        """
        ).fetchall()

        for r in fe_rows:
            edges.append(
                {
                    "source": r["source"],
                    "target": r["target"],
                    "kind": r["kind"],
                    "weight": round(min(r["symbol_count"] * 0.1, 1.0), 2),
                }
            )

        # --- Layers ---
        G = build_symbol_graph(conn)
        layers_raw = detect_layers(G)
        layers = [{"name": f"Layer {lid}", "nodes": []} for lid in set(layers_raw.values())]
        # Map symbols to layers
        layer_map: dict[int, list[str]] = {}
        for sym_id_str, layer_id in layers_raw.items():
            lid = int(layer_id)
            layer_map.setdefault(lid, []).append(f"symbol:{sym_id_str}")
        for i, layer in enumerate(layers):
            lid = list(layer_map.keys())[i] if i < len(layer_map) else i
            layer["nodes"] = layer_map.get(lid, [])

        # --- Stats ---
        kind_counts = {}
        for r in conn.execute(
            "SELECT kind, COUNT(*) AS cnt FROM symbols GROUP BY kind ORDER BY cnt DESC"
        ).fetchall():
            kind_counts[r["kind"]] = r["cnt"]

        stats = {"kind_distribution": kind_counts}

        conn.close()

        return {
            "project": project,
            "nodes": nodes,
            "edges": edges,
            "layers": layers,
            "stats": stats,
        }

    except Exception:
        conn.close()
        raise


class _DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves the dashboard HTML and JSON API."""

    graph_json: bytes = b"{}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_TEMPLATE_DIR.parent), **kwargs)

    def do_GET(self):
        if self.path == "/api/graph":
            self._send_json(self.graph_json)
        elif self.path == "/" or self.path == "/index.html":
            self._serve_html()
        else:
            super().do_GET()

    def _send_json(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_html(self):
        if _INDEX_HTML.exists():
            content = _INDEX_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(500, "Dashboard HTML not found")

    def log_message(self, format, *args):
        logger.debug("Dashboard HTTP: %s", format % args)


class DashboardServer:
    """Lightweight HTTP server for the interactive dashboard."""

    def __init__(self, db_path: str, port: int = 8765):
        self.db_path = db_path
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        """Start the server in a background thread. Returns the dashboard URL."""
        graph_data = export_graph_json(self.db_path)
        graph_bytes = json.dumps(graph_data, ensure_ascii=False, default=str).encode("utf-8")

        # Inject the graph data into the handler class
        handler = type(
            "_DashboardHandler",
            (_DashboardHandler,),
            {"graph_json": graph_bytes},
        )

        self._server = HTTPServer(("127.0.0.1", self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        url = f"http://127.0.0.1:{self.port}"
        return url

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

"""Map symbols/files to their test coverage."""

import os

import click

from roam.db.connection import open_db, db_exists
from roam.output.formatter import abbrev_kind, loc, format_edge_kind, to_json


TEST_PATTERNS_NAME = ["test_", "_test.", ".test.", ".spec."]
TEST_PATTERNS_DIR = ["tests/", "test/", "__tests__/", "spec/"]


def _is_test_file(path):
    """Check if a file path matches test naming conventions."""
    p = path.replace("\\", "/")
    basename = os.path.basename(p)
    if any(pat in basename for pat in TEST_PATTERNS_NAME):
        return True
    if any(d in p for d in TEST_PATTERNS_DIR):
        return True
    return False


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


def _find_symbol(conn, name):
    """Find a symbol by exact name, qualified name, or fuzzy match."""
    rows = conn.execute(
        "SELECT s.*, f.path as file_path FROM symbols s "
        "JOIN files f ON s.file_id = f.id WHERE s.qualified_name = ?",
        (name,),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]

    rows = conn.execute(
        "SELECT s.*, f.path as file_path FROM symbols s "
        "JOIN files f ON s.file_id = f.id WHERE s.name = ?",
        (name,),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]

    # Disambiguate: pick most-referenced
    if len(rows) > 1:
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
        return rows[0]

    # Fuzzy match
    rows = conn.execute(
        "SELECT s.*, f.path as file_path FROM symbols s "
        "JOIN files f ON s.file_id = f.id WHERE s.name LIKE ? COLLATE NOCASE LIMIT 10",
        (f"%{name}%",),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    if rows:
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


def _test_map_symbol(conn, sym):
    """Show test files that exercise a given symbol."""
    click.echo(f"Test coverage for: {sym['name']} ({abbrev_kind(sym['kind'])}, {loc(sym['file_path'], sym['line_start'])})")
    click.echo()

    # Direct tests: edges where source is in a test file and target is this symbol
    callers = conn.execute(
        "SELECT s.name, s.kind, f.path as file_path, e.kind as edge_kind, e.line as edge_line "
        "FROM edges e "
        "JOIN symbols s ON e.source_id = s.id "
        "JOIN files f ON s.file_id = f.id "
        "WHERE e.target_id = ?",
        (sym["id"],),
    ).fetchall()

    direct_tests = [c for c in callers if _is_test_file(c["file_path"])]
    if direct_tests:
        click.echo(f"Direct tests ({len(direct_tests)}):")
        for t in direct_tests:
            edge = format_edge_kind(t["edge_kind"])
            click.echo(f"  {t['name']:<25s} {abbrev_kind(t['kind'])}  {loc(t['file_path'], t['edge_line'])}   ({edge})")
    else:
        click.echo("Direct tests: (none)")

    click.echo()

    # Test files importing the symbol's file
    sym_file_id = conn.execute(
        "SELECT id FROM files WHERE path = ?", (sym["file_path"],)
    ).fetchone()
    if sym_file_id:
        importers = conn.execute(
            "SELECT f.path, fe.symbol_count "
            "FROM file_edges fe "
            "JOIN files f ON fe.source_file_id = f.id "
            "WHERE fe.target_file_id = ?",
            (sym_file_id["id"],),
        ).fetchall()
        test_importers = [r for r in importers if _is_test_file(r["path"])]
        if test_importers:
            click.echo(f"Test files importing {sym['file_path']} ({len(test_importers)}):")
            for r in test_importers:
                click.echo(f"  {r['path']:<45s} {r['symbol_count']} symbols used")
        else:
            click.echo(f"Test files importing {sym['file_path']}: (none)")


def _test_map_file(conn, path):
    """Show test files that exercise a given source file."""
    frow = conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
    if frow is None:
        frow = conn.execute(
            "SELECT * FROM files WHERE path LIKE ? LIMIT 1", (f"%{path}",)
        ).fetchone()
    if frow is None:
        click.echo(f"File not found in index: {path}")
        raise SystemExit(1)

    click.echo(f"Test coverage for: {frow['path']}")
    click.echo()

    # Test files that import this file
    importers = conn.execute(
        "SELECT f.path, fe.symbol_count "
        "FROM file_edges fe "
        "JOIN files f ON fe.source_file_id = f.id "
        "WHERE fe.target_file_id = ?",
        (frow["id"],),
    ).fetchall()
    test_importers = [r for r in importers if _is_test_file(r["path"])]

    if test_importers:
        click.echo(f"Test files importing {frow['path']} ({len(test_importers)}):")
        for r in test_importers:
            # List test functions in that test file
            test_syms = conn.execute(
                "SELECT s.name, s.kind, s.line_start FROM symbols s "
                "WHERE s.file_id = (SELECT id FROM files WHERE path = ?) "
                "AND s.kind IN ('function', 'method') "
                "AND s.name LIKE 'test%' "
                "ORDER BY s.line_start",
                (r["path"],),
            ).fetchall()
            click.echo(f"  {r['path']:<45s} {r['symbol_count']} symbols used")
            for ts in test_syms:
                click.echo(f"    {abbrev_kind(ts['kind'])}  {ts['name']}  L{ts['line_start']}")
    else:
        click.echo(f"Test files importing {frow['path']}: (none)")

    click.echo()

    # Also show direct test references to symbols in this file
    sym_ids = conn.execute(
        "SELECT id FROM symbols WHERE file_id = ?", (frow["id"],)
    ).fetchall()
    if sym_ids:
        ph = ",".join("?" for _ in sym_ids)
        ids = [s["id"] for s in sym_ids]
        test_callers = conn.execute(
            f"SELECT DISTINCT f.path "
            f"FROM edges e "
            f"JOIN symbols s ON e.source_id = s.id "
            f"JOIN files f ON s.file_id = f.id "
            f"WHERE e.target_id IN ({ph})",
            ids,
        ).fetchall()
        test_caller_files = [r["path"] for r in test_callers if _is_test_file(r["path"])]
        if test_caller_files:
            click.echo(f"Test files referencing symbols in {frow['path']} ({len(test_caller_files)}):")
            for tf in test_caller_files:
                click.echo(f"  {tf}")


@click.command("test-map")
@click.argument('name')
@click.pass_context
def test_map(ctx, name):
    """Map a symbol or file to its test coverage."""
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()

    name_norm = name.replace("\\", "/")

    with open_db(readonly=True) as conn:
        if "/" in name_norm or "." in name_norm:
            frow = conn.execute("SELECT id FROM files WHERE path = ?", (name_norm,)).fetchone()
            if frow is None:
                frow = conn.execute(
                    "SELECT id FROM files WHERE path LIKE ? LIMIT 1", (f"%{name_norm}",)
                ).fetchone()
            if frow:
                if json_mode:
                    _test_map_file_json(conn, name_norm)
                else:
                    _test_map_file(conn, name_norm)
                return

        sym = _find_symbol(conn, name)
        if sym:
            if json_mode:
                _test_map_symbol_json(conn, sym)
            else:
                _test_map_symbol(conn, sym)
            return

        click.echo(f"Not found: {name}")
        raise SystemExit(1)


def _test_map_symbol_json(conn, sym):
    """JSON output for test-map on a symbol."""
    callers = conn.execute(
        "SELECT s.name, s.kind, f.path as file_path, e.kind as edge_kind "
        "FROM edges e JOIN symbols s ON e.source_id = s.id "
        "JOIN files f ON s.file_id = f.id WHERE e.target_id = ?",
        (sym["id"],),
    ).fetchall()
    direct_tests = [c for c in callers if _is_test_file(c["file_path"])]

    sym_file_id = conn.execute(
        "SELECT id FROM files WHERE path = ?", (sym["file_path"],)
    ).fetchone()
    test_importers = []
    if sym_file_id:
        importers = conn.execute(
            "SELECT f.path, fe.symbol_count FROM file_edges fe "
            "JOIN files f ON fe.source_file_id = f.id WHERE fe.target_file_id = ?",
            (sym_file_id["id"],),
        ).fetchall()
        test_importers = [r for r in importers if _is_test_file(r["path"])]

    click.echo(to_json({
        "name": sym["name"], "kind": sym["kind"],
        "location": loc(sym["file_path"], sym["line_start"]),
        "direct_tests": [
            {"name": t["name"], "kind": t["kind"], "file": t["file_path"],
             "edge_kind": t["edge_kind"]}
            for t in direct_tests
        ],
        "test_importers": [
            {"path": r["path"], "symbols_used": r["symbol_count"]}
            for r in test_importers
        ],
    }))


def _test_map_file_json(conn, path):
    """JSON output for test-map on a file."""
    frow = conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
    if frow is None:
        frow = conn.execute(
            "SELECT * FROM files WHERE path LIKE ? LIMIT 1", (f"%{path}",)
        ).fetchone()
    if frow is None:
        click.echo(to_json({"error": f"File not found: {path}"}))
        return

    importers = conn.execute(
        "SELECT f.path, fe.symbol_count FROM file_edges fe "
        "JOIN files f ON fe.source_file_id = f.id WHERE fe.target_file_id = ?",
        (frow["id"],),
    ).fetchall()
    test_importers = [r for r in importers if _is_test_file(r["path"])]

    sym_ids = conn.execute(
        "SELECT id FROM symbols WHERE file_id = ?", (frow["id"],)
    ).fetchall()
    test_caller_files = []
    if sym_ids:
        ph = ",".join("?" for _ in sym_ids)
        ids = [s["id"] for s in sym_ids]
        test_callers = conn.execute(
            f"SELECT DISTINCT f.path FROM edges e "
            f"JOIN symbols s ON e.source_id = s.id "
            f"JOIN files f ON s.file_id = f.id WHERE e.target_id IN ({ph})",
            ids,
        ).fetchall()
        test_caller_files = [r["path"] for r in test_callers if _is_test_file(r["path"])]

    click.echo(to_json({
        "path": frow["path"],
        "test_importers": [
            {"path": r["path"], "symbols_used": r["symbol_count"]}
            for r in test_importers
        ],
        "test_callers": test_caller_files,
    }))

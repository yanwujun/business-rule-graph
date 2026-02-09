import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import (
    FILES_IN_DIR, SYMBOLS_IN_DIR, FILE_IMPORTS, FILE_IMPORTED_BY,
)
from roam.output.formatter import (
    abbrev_kind, loc, format_signature, format_table, section,
)


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.argument('path')
def module(path):
    """Show directory contents: exports, signatures, deps."""
    _ensure_index()

    path = path.replace("\\", "/").rstrip("/")

    with open_db(readonly=True) as conn:
        if path == ".":
            # Root-level files: match paths without any directory separator
            files = conn.execute(
                "SELECT * FROM files WHERE path NOT LIKE '%/%' ORDER BY path",
            ).fetchall()
            if not files:
                # Fall back: all files
                files = conn.execute("SELECT * FROM files ORDER BY path").fetchall()
        else:
            pattern = f"{path}/%"
            files = conn.execute(FILES_IN_DIR, (pattern,)).fetchall()
            if not files:
                files = conn.execute(FILES_IN_DIR, (f"%{path}/%",)).fetchall()
        if not files:
            click.echo(f"No files found under: {path}/")
            raise SystemExit(1)

        click.echo(f"Module: {path}/  ({len(files)} files)")
        click.echo()

        # --- Files ---
        file_rows = [[f["path"], f["language"] or "?", str(f["line_count"])]
                     for f in files]
        click.echo("Files:")
        click.echo(format_table(["path", "lang", "lines"], file_rows, budget=30))
        click.echo()

        # --- Exported symbols ---
        if path == ".":
            symbols = conn.execute(
                """SELECT s.*, f.path as file_path FROM symbols s
                   JOIN files f ON s.file_id = f.id
                   WHERE f.path NOT LIKE '%/%'
                   ORDER BY f.path, s.line_start""",
            ).fetchall()
        else:
            pattern = f"{path}/%"
            symbols = conn.execute(SYMBOLS_IN_DIR, (pattern,)).fetchall()
            if not symbols:
                symbols = conn.execute(SYMBOLS_IN_DIR, (f"%{path}/%",)).fetchall()

        if symbols:
            sym_lines = []
            for s in symbols:
                sig = format_signature(s["signature"], max_len=60)
                parts = [abbrev_kind(s["kind"]), s["name"]]
                if sig:
                    parts.append(sig)
                parts.append(loc(s["file_path"], s["line_start"]))
                sym_lines.append("  " + "  ".join(parts))
            click.echo(section(f"Exports ({len(symbols)}):", sym_lines, budget=40))
        else:
            click.echo("Exports: (none)")
        click.echo()

        # --- Module-level dependencies ---
        file_ids = [f["id"] for f in files]
        file_id_set = set(file_ids)

        imports_external = {}
        imported_by_external = {}

        for fid in file_ids:
            for row in conn.execute(FILE_IMPORTS, (fid,)).fetchall():
                if row["id"] not in file_id_set:
                    imports_external[row["path"]] = (
                        imports_external.get(row["path"], 0) + row["symbol_count"]
                    )
            for row in conn.execute(FILE_IMPORTED_BY, (fid,)).fetchall():
                if row["id"] not in file_id_set:
                    imported_by_external[row["path"]] = (
                        imported_by_external.get(row["path"], 0) + row["symbol_count"]
                    )

        if imports_external:
            sorted_imp = sorted(imports_external.items(), key=lambda x: -x[1])
            rows = [[p, str(c)] for p, c in sorted_imp]
            click.echo("External imports:")
            click.echo(format_table(["file", "symbols"], rows, budget=20))
        else:
            click.echo("External imports: (none)")
        click.echo()

        if imported_by_external:
            sorted_by = sorted(imported_by_external.items(), key=lambda x: -x[1])
            rows = [[p, str(c)] for p, c in sorted_by]
            click.echo("Imported by (external):")
            click.echo(format_table(["file", "symbols"], rows, budget=20))
        else:
            click.echo("Imported by (external): (none)")

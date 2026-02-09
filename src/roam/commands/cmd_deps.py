import click

from roam.db.connection import open_db, db_exists
from roam.db.queries import FILE_BY_PATH, FILE_IMPORTS, FILE_IMPORTED_BY
from roam.output.formatter import format_table


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.argument('path')
@click.option('--full', is_flag=True, help='Show all results without truncation')
def deps(path, full):
    """Show file import/imported-by relationships."""
    _ensure_index()

    path = path.replace("\\", "/")

    with open_db(readonly=True) as conn:
        frow = conn.execute(FILE_BY_PATH, (path,)).fetchone()
        if frow is None:
            frow = conn.execute(
                "SELECT * FROM files WHERE path LIKE ? LIMIT 1",
                (f"%{path}",),
            ).fetchone()
        if frow is None:
            click.echo(f"File not found in index: {path}")
            raise SystemExit(1)

        click.echo(f"{frow['path']}")
        click.echo()

        # --- Imports (what this file depends on) ---
        imports = conn.execute(FILE_IMPORTS, (frow["id"],)).fetchall()
        if imports:
            rows = [[i["path"], str(i["symbol_count"])] for i in imports]
            click.echo("Imports:")
            click.echo(format_table(["file", "symbols"], rows))
        else:
            click.echo("Imports: (none)")
        click.echo()

        # --- Imported by (who depends on this file) ---
        imported_by = conn.execute(FILE_IMPORTED_BY, (frow["id"],)).fetchall()
        if imported_by:
            rows = [[i["path"], str(i["symbol_count"])] for i in imported_by]
            click.echo("Imported by:")
            click.echo(format_table(["file", "symbols"], rows))
        else:
            click.echo("Imported by: (none)")

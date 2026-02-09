"""Show code ownership: who owns a file or directory."""

import os

import click

from roam.db.connection import open_db, db_exists, find_project_root
from roam.index.git_stats import get_blame_for_file
from roam.output.formatter import format_table


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


def _ownership_for_file(project_root, file_path):
    """Compute ownership breakdown for a single file."""
    blame = get_blame_for_file(project_root, file_path)
    if not blame:
        return None

    author_lines = {}
    for entry in blame:
        author = entry["author"]
        author_lines[author] = author_lines.get(author, 0) + 1

    total = sum(author_lines.values())
    if total == 0:
        return None

    # Sort by lines desc
    sorted_authors = sorted(author_lines.items(), key=lambda x: x[1], reverse=True)

    # Compute fragmentation: 1 - sum(p_i^2) (Herfindahl index complement)
    fragmentation = 1.0 - sum((n / total) ** 2 for _, n in sorted_authors)

    return {
        "authors": sorted_authors,
        "total": total,
        "fragmentation": round(fragmentation, 3),
        "main_dev": sorted_authors[0][0] if sorted_authors else "?",
    }


@click.command()
@click.argument('path')
def owner(path):
    """Show code ownership: who owns a file or directory."""
    _ensure_index()
    project_root = find_project_root()
    path = path.replace("\\", "/")

    with open_db(readonly=True) as conn:
        # Check if path is a directory (matches multiple files)
        dir_files = conn.execute(
            "SELECT path FROM files WHERE path LIKE ? ORDER BY path",
            (f"{path}%",),
        ).fetchall()

        if not dir_files:
            # Try exact match
            frow = conn.execute(
                "SELECT path FROM files WHERE path = ?", (path,)
            ).fetchone()
            if frow is None:
                frow = conn.execute(
                    "SELECT path FROM files WHERE path LIKE ? LIMIT 1",
                    (f"%{path}",),
                ).fetchone()
            if frow is None:
                click.echo(f"Path not found in index: {path}")
                raise SystemExit(1)
            dir_files = [frow]

        if len(dir_files) == 1:
            # Single file
            file_path = dir_files[0]["path"]
            click.echo(f"{file_path}")
            click.echo()

            info = _ownership_for_file(project_root, file_path)
            if info is None:
                click.echo("  (no blame data available)")
                return

            click.echo(f"Main developer: {info['main_dev']}")
            click.echo(f"Fragmentation: {info['fragmentation']} (0=one owner, 1=many)")
            click.echo()

            rows = []
            for author, lines in info["authors"]:
                pct = f"{lines * 100 / info['total']:.0f}%"
                rows.append([author, str(lines), pct])
            click.echo(format_table(["author", "lines", "pct"], rows))
        else:
            # Directory: aggregate
            click.echo(f"{path}/ ({len(dir_files)} files)")
            click.echo()

            all_author_lines = {}
            total_lines = 0
            for f in dir_files:
                info = _ownership_for_file(project_root, f["path"])
                if info is None:
                    continue
                for author, lines in info["authors"]:
                    all_author_lines[author] = all_author_lines.get(author, 0) + lines
                total_lines += info["total"]

            if total_lines == 0:
                click.echo("  (no blame data available)")
                return

            sorted_authors = sorted(all_author_lines.items(), key=lambda x: x[1], reverse=True)
            fragmentation = 1.0 - sum((n / total_lines) ** 2 for _, n in sorted_authors)

            click.echo(f"Main developer: {sorted_authors[0][0]}")
            click.echo(f"Fragmentation: {fragmentation:.3f}")
            click.echo()

            rows = []
            for author, lines in sorted_authors:
                pct = f"{lines * 100 / total_lines:.0f}%"
                rows.append([author, str(lines), pct])
            click.echo(format_table(["author", "lines", "pct"], rows))

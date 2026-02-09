"""Find all classes that extend/use/implement a given symbol."""

import click

from roam.db.connection import db_exists, open_db
from roam.output.formatter import abbrev_kind, loc, section


def _ensure_index():
    if not db_exists():
        from roam.index.indexer import Indexer
        Indexer().run()


@click.command()
@click.argument("name")
def uses(name):
    """Find all classes that extend, use, or implement a symbol."""
    _ensure_index()

    with open_db(readonly=True) as conn:
        # Find the target symbol(s) by name
        targets = conn.execute(
            "SELECT id, name, kind, qualified_name FROM symbols WHERE name = ?",
            (name,),
        ).fetchall()

        if not targets:
            # Try LIKE search
            targets = conn.execute(
                "SELECT id, name, kind, qualified_name FROM symbols WHERE name LIKE ?",
                (f"%{name}%",),
            ).fetchall()

        if not targets:
            click.echo(f"Symbol '{name}' not found.")
            raise SystemExit(1)

        target_ids = [t["id"] for t in targets]

        # Find all edges pointing TO these targets with inheritance kinds
        inheritance_kinds = ("inherits", "uses_trait", "implements")
        placeholders = ",".join("?" for _ in target_ids)
        kind_placeholders = ",".join("?" for _ in inheritance_kinds)

        rows = conn.execute(
            f"""SELECT DISTINCT s.name, s.qualified_name, s.kind, s.line_start,
                       f.path, e.kind as edge_kind, t.name as target_name
                FROM edges e
                JOIN symbols s ON e.source_id = s.id
                JOIN symbols t ON e.target_id = t.id
                JOIN files f ON s.file_id = f.id
                WHERE e.target_id IN ({placeholders})
                  AND e.kind IN ({kind_placeholders})
                ORDER BY e.kind, f.path, s.line_start""",
            [*target_ids, *inheritance_kinds],
        ).fetchall()

        if not rows:
            # Also try: maybe the user searched for a trait/class name
            # but the edges store it differently. Search by target_name in edges.
            # Fallback: search edge targets by name match
            rows = conn.execute(
                f"""SELECT DISTINCT s.name, s.qualified_name, s.kind, s.line_start,
                           f.path, e.kind as edge_kind, t.name as target_name
                    FROM edges e
                    JOIN symbols s ON e.source_id = s.id
                    JOIN symbols t ON e.target_id = t.id
                    JOIN files f ON s.file_id = f.id
                    WHERE t.name = ?
                      AND e.kind IN ({kind_placeholders})
                    ORDER BY e.kind, f.path, s.line_start""",
                [name, *inheritance_kinds],
            ).fetchall()

        if not rows:
            click.echo(f"No classes extend, use, or implement '{name}'.")
            click.echo(f"\nTip: If the index is stale, run: roam index --force")
            return

        click.echo(f"=== Who uses '{name}' ({len(rows)} results) ===\n")

        # Group by edge kind
        by_kind = {}
        for r in rows:
            edge_kind = r["edge_kind"]
            by_kind.setdefault(edge_kind, []).append(r)

        kind_labels = {
            "inherits": "Extends",
            "uses_trait": "Uses trait",
            "implements": "Implements",
        }

        for kind, items in by_kind.items():
            label = kind_labels.get(kind, kind)
            click.echo(f"-- {label} ({len(items)}) --")
            for r in items:
                click.echo(
                    f"  {abbrev_kind(r['kind'])}  {r['qualified_name']}  "
                    f"{loc(r['path'], r['line_start'])}"
                )
            click.echo()

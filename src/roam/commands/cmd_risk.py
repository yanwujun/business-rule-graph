"""Show domain-weighted risk ranking of symbols."""

import json
import os
import re

import click

from roam.db.connection import open_db, db_exists
from roam.output.formatter import abbrev_kind, loc, format_table, to_json


def _ensure_index():
    if not db_exists():
        click.echo("No index found. Building...")
        from roam.index.indexer import Indexer
        Indexer().run()


# Default domain keyword → weight multiplier mapping.
# Symbols matching high-weight domains rank higher in risk output.
_DEFAULT_DOMAINS = {
    # Financial / accounting (critical — bugs lose money)
    "money": 10, "payment": 10, "invoice": 10, "ledger": 10,
    "balance": 10, "transaction": 10, "credit": 10, "debit": 10,
    "tax": 10, "vat": 10, "price": 8, "cost": 8, "amount": 8,
    "currency": 8, "billing": 8, "refund": 8, "receipt": 8,
    "accounting": 10, "fiscal": 10, "journal": 8,
    # Auth / security (critical — bugs leak data)
    "auth": 8, "password": 10, "token": 8, "session": 6,
    "permission": 8, "encrypt": 10, "decrypt": 10, "secret": 10,
    "credential": 10, "login": 6, "logout": 4,
    # Data integrity
    "delete": 6, "destroy": 6, "migrate": 6, "truncate": 8,
    "backup": 6, "restore": 6, "sync": 4, "import": 4, "export": 4,
    # Business logic (medium)
    "order": 5, "customer": 5, "user": 4, "account": 5,
    "calculate": 5, "validate": 4, "process": 3, "approve": 5,
    "schedule": 4, "notify": 3, "report": 4,
    # UI / presentation (dampened — less risky than business logic)
    "render": 0.3, "display": 0.3, "show": 0.3, "hide": 0.3, "style": 0.3,
    "theme": 0.3, "color": 0.3, "icon": 0.3, "modal": 0.3, "tooltip": 0.3,
    "animation": 0.3, "layout": 0.3, "grid": 0.3, "menu": 0.3,
    "button": 0.3, "dialog": 0.3, "drawer": 0.3, "spinner": 0.3,
    "badge": 0.3, "card": 0.3, "panel": 0.3, "tab": 0.3,
}


def _load_custom_domains():
    """Load custom domain weights from .roam/domain-weights.json if present."""
    path = os.path.join(".roam", "domain-weights.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k).lower(): float(v) for k, v in data.items()
                    if isinstance(v, (int, float))}
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return {}


_UI_PATH_PATTERNS = ("components/", "views/", "pages/", "templates/",
                      "layouts/", "/ui/", "widgets/", "screens/")
_UI_EXTENSIONS = (".vue", ".svelte", ".jsx", ".tsx")


def _is_ui_file(file_path):
    """Check if a file is in a UI-related directory or has a UI extension."""
    p = file_path.replace("\\", "/").lower()
    return (any(pat in p for pat in _UI_PATH_PATTERNS)
            or any(p.endswith(ext) for ext in _UI_EXTENSIONS))


def _match_domain(name, domains):
    """Return the highest domain weight for a symbol name."""
    split_re = re.compile(r'[A-Z][a-z]+|[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)')
    words = [w.lower() for w in split_re.findall(name)]
    best_weight = None
    matched = ""
    for w in words:
        if w in domains:
            wt = domains[w]
            if best_weight is None or wt > best_weight:
                best_weight = wt
                matched = w
    if best_weight is None:
        return 1, ""  # No domain match — neutral
    return best_weight, matched


@click.command()
@click.option('-n', 'count', default=30, help='Number of symbols to show')
@click.option('--domain', 'domain_keywords', default=None,
              help='Comma-separated high-weight domain keywords (e.g. "payment,tax,ledger")')
@click.pass_context
def risk(ctx, count, domain_keywords):
    """Show domain-weighted risk ranking of symbols.

    Combines static risk (fan-in + fan-out + betweenness) with domain
    criticality weights. Financial, auth, and data-integrity symbols
    rank higher than UI symbols.
    """
    json_mode = ctx.obj.get('json') if ctx.obj else False
    _ensure_index()

    # Build domain map: defaults → .roam/domain-weights.json → CLI overrides
    domains = dict(_DEFAULT_DOMAINS)
    custom = _load_custom_domains()
    if custom:
        domains.update(custom)
    if domain_keywords:
        for kw in domain_keywords.split(","):
            kw = kw.strip().lower()
            if kw:
                domains[kw] = 10  # User-specified keywords get max weight

    with open_db(readonly=True) as conn:
        rows = conn.execute("""
            SELECT s.name, s.kind, f.path as file_path, s.line_start,
                   gm.in_degree, gm.out_degree, gm.betweenness, gm.pagerank
            FROM graph_metrics gm
            JOIN symbols s ON gm.symbol_id = s.id
            JOIN files f ON s.file_id = f.id
            WHERE s.kind IN ('function', 'class', 'method', 'interface', 'struct')
            AND (gm.in_degree + gm.out_degree) > 0
        """).fetchall()

        if not rows:
            if json_mode:
                click.echo(to_json({"items": []}))
            else:
                click.echo("No graph metrics available. Run `roam index` first.")
            return

        # Compute static risk (0-10 scale)
        max_total = max((r["in_degree"] + r["out_degree"]) for r in rows) or 1
        max_bw = max((r["betweenness"] or 0) for r in rows) or 1

        scored = []
        for r in rows:
            total_deg = r["in_degree"] + r["out_degree"]
            bw = r["betweenness"] or 0

            # Static risk: weighted combination of degree and betweenness
            static_risk = (
                (total_deg / max_total) * 5 +
                (bw / max_bw) * 5
            )

            domain_weight, domain_match = _match_domain(r["name"], domains)

            # File-path UI dampening: if symbol is in a UI file and matched
            # a non-UI domain keyword (e.g. "restore" in a component),
            # halve the domain weight to avoid false positives
            if domain_weight > 1 and _is_ui_file(r["file_path"]):
                domain_weight = max(1, domain_weight * 0.5)

            adjusted_risk = static_risk * domain_weight

            scored.append({
                "name": r["name"],
                "kind": r["kind"],
                "file_path": r["file_path"],
                "line_start": r["line_start"],
                "static_risk": round(static_risk, 1),
                "domain_weight": domain_weight,
                "domain_match": domain_match,
                "adjusted_risk": round(adjusted_risk, 1),
                "in_degree": r["in_degree"],
                "out_degree": r["out_degree"],
            })

        scored.sort(key=lambda x: -x["adjusted_risk"])
        scored = scored[:count]

        if json_mode:
            click.echo(to_json({
                "items": [
                    {
                        "name": s["name"],
                        "kind": s["kind"],
                        "static_risk": s["static_risk"],
                        "domain_weight": s["domain_weight"],
                        "domain_match": s["domain_match"],
                        "adjusted_risk": s["adjusted_risk"],
                        "location": loc(s["file_path"], s["line_start"]),
                    }
                    for s in scored
                ],
            }))
            return

        # --- Text output ---
        click.echo("=== Domain-Weighted Risk ===")
        if domain_keywords:
            click.echo(f"  Custom domain keywords: {domain_keywords}")
        click.echo()

        table_rows = []
        for s in scored:
            domain_str = f"x{s['domain_weight']}" if s['domain_weight'] > 1 else ""
            match_str = f"({s['domain_match']})" if s['domain_match'] else ""
            flag = ""
            if s["adjusted_risk"] >= 30:
                flag = "CRITICAL"
            elif s["adjusted_risk"] >= 15:
                flag = "HIGH"
            elif s["adjusted_risk"] >= 5:
                flag = "MEDIUM"

            table_rows.append([
                abbrev_kind(s["kind"]),
                s["name"],
                f"{s['static_risk']:.1f}",
                f"{domain_str} {match_str}".strip() if domain_str else "",
                f"{s['adjusted_risk']:.1f}",
                flag,
                loc(s["file_path"], s["line_start"]),
            ])

        click.echo(format_table(
            ["Kind", "Name", "Static", "Domain", "Adjusted", "Level", "Location"],
            table_rows,
        ))

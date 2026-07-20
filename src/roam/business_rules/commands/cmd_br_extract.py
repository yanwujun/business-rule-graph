"""CLI commands for business rule graph — M1: extract + summarize"""
from __future__ import annotations

import json
import sqlite3

import click

from roam.business_rules.extractor import BusinessRuleExtractor
from roam.business_rules.summarizer import RuleSummarizer
from roam.db.connection import find_project_root


@click.command("business-rules-extract")
@click.option("--update", is_flag=True, help="Incremental: only changed files")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--project-root", default=None, help="Project root (default: auto-detect)")
def cmd_br_extract(update=False, as_json=False, project_root=None):
    """Extract business rules from Java/Spring Boot code (AST engine)"""
    if project_root:
        root = project_root
    else:
        try:
            root = find_project_root()
        except Exception:
            root = "."

    db_path = f"{root}/.roam/index.db"
    if not __import__("os").path.exists(db_path):
        click.echo("Error: No index found. Run 'roam init' first.", err=True)
        return

    extractor = BusinessRuleExtractor(project_root=root)
    rules = extractor.extract_from_db(db_path, incremental=update)

    if not rules:
        click.echo("No business rules detected.")
        return

    # Write to SQLite
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM business_rules WHERE 1=1")
        conn.executemany("""
            INSERT OR REPLACE INTO business_rules
            (rule_id, rule_type, domain, flow, description, severity,
             source_file, source_line, source_symbol, params, annotations,
             hash, extraction)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            (
                r.rule_id, r.rule_type.value, r.domain, r.flow,
                r.description, r.severity.value,
                r.source_file, r.source_line, r.source_symbol,
                json.dumps(r.params, ensure_ascii=False),
                json.dumps(r.annotations, ensure_ascii=False),
                r.compute_hash(), r.extraction,
            )
            for r in rules
        ])
        conn.commit()

    # Summary
    by_type = {}
    for r in rules:
        key = r.rule_type.value
        by_type[key] = by_type.get(key, 0) + 1

    if as_json:
        click.echo(json.dumps({
            "total": len(rules),
            "by_type": by_type,
        }, indent=2, ensure_ascii=False))
    else:
        click.echo(f"Extracted {len(rules)} business rules (AST)")
        for rt, count in sorted(by_type.items()):
            click.echo(f"  {rt}: {count}")


@click.command("business-rules-summarize")
@click.option("--api-key", default=None, help="LLM API key (or set env var)")
@click.option("--base-url", default=None, help="LLM API base URL")
@click.option("--model", default=None, help="LLM model name")
@click.option("--batch-size", default=50, help="Rules per LLM call")
@click.option("--json", "as_json", is_flag=True)
def cmd_br_summarize(api_key=None, base_url=None, model=None, batch_size=50, as_json=False):
    """LLM semantic enrichment — add business context to extracted rules"""
    try:
        root = find_project_root()
    except Exception:
        root = "."

    db_path = f"{root}/.roam/index.db"

    # Load rules from DB
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM business_rules ORDER BY source_file, source_line"
        ).fetchall()

    if not rows:
        click.echo("No rules to summarize. Run 'roam business-rules extract' first.")
        return

    rules = []
    for r in rows:
        rules.append({
            "rule_id": r["rule_id"],
            "rule_type": r["rule_type"],
            "domain": r["domain"],
            "flow": r["flow"] or "",
            "description": r["description"],
            "severity": r["severity"],
            "source_file": r["source_file"],
            "source_line": r["source_line"],
            "exception_message": json.loads(r["params"]).get("exception_message", ""),
            "status_value": json.loads(r["params"]).get("status_value", ""),
            "enum_values": json.loads(r["params"]).get("enum_values", []),
            "extraction": r["extraction"],
        })

    summarizer = RuleSummarizer(
        api_key=api_key, base_url=base_url, model=model,
    )
    enriched = summarizer.summarize(rules, batch_size=batch_size)

    # Write back
    with sqlite3.connect(db_path) as conn:
        for r in enriched:
            conn.execute("""
                UPDATE business_rules
                SET domain = ?, flow = ?, description = ?, severity = ?,
                    merge_with = ?, updated_at = datetime('now')
                WHERE rule_id = ?
            """, (
                r.get("domain", ""),
                r.get("flow", ""),
                r.get("description", ""),
                r.get("severity", "medium"),
                r.get("merge_with"),
                r["rule_id"],
            ))
        conn.commit()

    # Handle merge_with
    merges = [r for r in enriched if r.get("merge_with")]
    for r in merges:
        click.echo(f"Merged: {r['rule_id']} → {r['merge_with']}")

    if as_json:
        click.echo(json.dumps({
            "total": len(enriched),
            "merges": len(merges),
        }, indent=2, ensure_ascii=False))
    else:
        click.echo(
            f"Summarized {len(enriched)} rules"
            + (f" ({len(merges)} merged)" if merges else "")
        )

"""CLI commands — extract, summarize, graph, check, diff, snapshot, list, explain"""
from __future__ import annotations

import json
import os as _os
import sqlite3
from pathlib import Path

import click


def _get_db_path():
    try:
        from roam.db.connection import find_project_root
        root = find_project_root()
    except Exception:
        root = "."
    return f"{root}/.roam/index.db"


def _resolve_projects(workspace):
    """解析工作区项目列表。无 --workspace 时返回空列表（单项目模式）。"""
    if workspace:
        from roam.business_rules.workspace import resolve_workspace
        return resolve_workspace(workspace)
    return []


def _extract_one(project_root, update=False):
    """对单个项目执行 AST 规则提取，返回规则列表"""
    from roam.business_rules.extractor import BusinessRuleExtractor

    db_path = str(project_root / ".roam" / "index.db")
    if not _os.path.exists(db_path):
        return None, "No index found"

    extractor = BusinessRuleExtractor(project_root=str(project_root))
    rules = extractor.extract_from_db(db_path, incremental=update)
    if not rules:
        return [], "No rules"

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM business_rules WHERE 1=1")
        conn.executemany("""INSERT OR REPLACE INTO business_rules
            (rule_id, rule_type, domain, flow, description, severity,
             source_file, source_line, source_symbol, params, annotations, hash, extraction)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
            (r.rule_id, r.rule_type.value, r.domain, r.flow, r.description, r.severity.value,
             r.source_file, r.source_line, r.source_symbol,
             json.dumps(r.params, ensure_ascii=False), json.dumps(r.annotations, ensure_ascii=False),
             r.compute_hash(), r.extraction) for r in rules
        ])
        conn.commit()
    return rules, None


@click.command("business-rules-extract")
@click.option("--update", is_flag=True, help="Incremental: only changed files")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--project-root", default=None, help="Project root (default: auto-detect)")
@click.option("--workspace", default=None, help=".code-workspace file for multi-root analysis")
def cmd_br_extract(update=False, as_json=False, project_root=None, workspace=None):
    """Extract business rules from Java/Spring Boot code (AST engine)"""
    projects = _resolve_projects(workspace)

    if projects:
        # 多项目模式
        all_results = []
        for proj in projects:
            if not proj.has_index:
                click.echo(f"  {proj.name:<20} [SKIP] No index (run 'roam init' first)", err=True)
                all_results.append({"project": proj.name, "total": 0, "status": "skipped"})
                continue
            rules, err = _extract_one(proj.root, update=update)
            if err:
                click.echo(f"  {proj.name:<20} {err}")
                all_results.append({"project": proj.name, "total": 0, "status": err})
            else:
                by_type = {}
                for r in rules:
                    by_type[r.rule_type.value] = by_type.get(r.rule_type.value, 0) + 1
                all_results.append({"project": proj.name, "total": len(rules), "by_type": by_type, "status": "ok"})
                click.echo(f"  {proj.name:<20} {len(rules)} rules")

        total_rules = sum(r["total"] for r in all_results)
        active = [r for r in all_results if r["status"] == "ok"]
        if as_json:
            click.echo(json.dumps({"workspace_projects": len(projects), "total_rules": total_rules,
                                   "projects": all_results}, indent=2, ensure_ascii=False))
        else:
            click.echo(f"\nWorkspace: {len(active)} projects active, {total_rules} total rules")

    else:
        # 单项目模式（原有逻辑）
        from roam.business_rules.extractor import BusinessRuleExtractor

        root = project_root or _root()
        db_path = f"{root}/.roam/index.db"
        if not _os.path.exists(db_path):
            click.echo("Error: No index found. Run 'roam init' first.", err=True)
            return

        extractor = BusinessRuleExtractor(project_root=root)
        rules = extractor.extract_from_db(db_path, incremental=update)
        if not rules:
            click.echo("No business rules detected.")
            return

        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM business_rules WHERE 1=1")
            conn.executemany("""INSERT OR REPLACE INTO business_rules
                (rule_id, rule_type, domain, flow, description, severity,
                 source_file, source_line, source_symbol, params, annotations, hash, extraction)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
                (r.rule_id, r.rule_type.value, r.domain, r.flow, r.description, r.severity.value,
                 r.source_file, r.source_line, r.source_symbol,
                 json.dumps(r.params, ensure_ascii=False), json.dumps(r.annotations, ensure_ascii=False),
                 r.compute_hash(), r.extraction) for r in rules
            ])
            conn.commit()

        by_type = {}
        for r in rules:
            by_type[r.rule_type.value] = by_type.get(r.rule_type.value, 0) + 1
        if as_json:
            click.echo(json.dumps({"total": len(rules), "by_type": by_type}, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Extracted {len(rules)} business rules (AST)")
            for rt, count in sorted(by_type.items()):
                click.echo(f"  {rt}: {count}")


@click.command("business-rules-summarize")
@click.option("--api-key", default=None, help="LLM API key")
@click.option("--base-url", default=None, help="LLM API base URL")
@click.option("--model", default=None, help="LLM model name")
@click.option("--batch-size", default=50, help="Rules per LLM call")
@click.option("--json", "as_json", is_flag=True)
def cmd_br_summarize(api_key=None, base_url=None, model=None, batch_size=50, as_json=False):
    """LLM semantic enrichment — add business context to extracted rules"""
    from roam.business_rules.summarizer import RuleSummarizer

    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM business_rules ORDER BY source_file, source_line").fetchall()
    if not rows:
        click.echo("No rules. Run 'roam business-rules extract' first.")
        return

    rules = [{k: r[k] for k in r.keys()} for r in rows]
    for r in rules:
        try:
            r["params"] = json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]
        except (json.JSONDecodeError, TypeError):
            r["params"] = {}
        r.setdefault("exception_message", r["params"].get("exception_message", ""))
        r.setdefault("status_value", r["params"].get("status_value", ""))
        r.setdefault("enum_values", r["params"].get("enum_values", []))

    summarizer = RuleSummarizer(api_key=api_key, base_url=base_url, model=model)
    enriched = summarizer.summarize(rules, batch_size=batch_size)

    with sqlite3.connect(db_path) as conn:
        for r in enriched:
            conn.execute("""UPDATE business_rules
                SET domain=?, flow=?, description=?, severity=?, merge_with=?, updated_at=datetime('now')
                WHERE rule_id=?""",
                (r.get("domain", ""), r.get("flow", ""), r.get("description", ""),
                 r.get("severity", "medium"), r.get("merge_with"), r["rule_id"]))
        conn.commit()

    merges = [r for r in enriched if r.get("merge_with")]
    if as_json:
        click.echo(json.dumps({"total": len(enriched), "merges": len(merges)}, indent=2, ensure_ascii=False))
    else:
        click.echo(f"Summarized {len(enriched)} rules" + (f" ({len(merges)} merged)" if merges else ""))


@click.command("business-rules-graph")
@click.option("--stats", is_flag=True, help="Show statistics only")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--workspace", default=None, help=".code-workspace file for multi-root analysis")
def cmd_br_graph(stats=False, as_json=False, workspace=None):
    """Build/rebuild business rule knowledge graph"""
    from roam.business_rules.graph import RuleGraph

    projects = _resolve_projects(workspace)
    target_dbs = [str(p.db_path) for p in projects] if projects else [_get_db_path()]

    for db_path in target_dbs:
        if not _os.path.exists(db_path):
            continue
        graph = RuleGraph(db_path)
        if stats:
            s = graph.stats()
            click.echo(json.dumps(s, indent=2) if as_json else f"Rules: {s['rules']}  Edges: {s['edges']}")
        else:
            result = graph.build()
            if as_json:
                click.echo(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                click.echo(f"Graph built: {result['total_edges']} edges")
                for et, n in sorted(result["by_type"].items()):
                    click.echo(f"  {et}: {n}")


@click.command("business-rules-check")
@click.option("--snapshot-id", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
@click.option("--workspace", default=None, help=".code-workspace file for multi-root analysis")
def cmd_br_check(snapshot_id=None, as_json=False, workspace=None):
    """Detect business rule conflicts"""
    from roam.business_rules.conflict import ConflictDetector

    projects = _resolve_projects(workspace)
    all_conflicts = []

    target_dbs = [p.db_path for p in projects] if projects else [_get_db_path()]

    for db_path in target_dbs:
        db_path = str(db_path)
        if not _os.path.exists(db_path):
            continue
        detector = ConflictDetector(db_path)
        conflicts = detector.detect(previous_snapshot_id=snapshot_id)
        proj_tag = ""
        if projects and len(projects) > 1:
            proj_name = Path(db_path).parent.parent.name if str(db_path) != _get_db_path() else ""
            proj_tag = f"[{proj_name}] " if proj_name else ""
        for c in conflicts:
            all_conflicts.append((proj_tag, c))

    if as_json:
        click.echo(json.dumps([{"source": ptag, "type": c.conflict_type, "severity": c.severity,
                                "description": c.description, "rule_a": c.rule_a, "rule_b": c.rule_b}
                               for ptag, c in all_conflicts], indent=2, ensure_ascii=False))
    elif not all_conflicts:
        click.echo("No conflicts detected.")
    else:
        for ptag, c in all_conflicts:
            click.echo(f"{ptag}[{c.severity.upper()}] {c.conflict_type}: {c.description}")


@click.command("business-rules-diff")
@click.option("--from", "from_id", type=int)
@click.option("--to", "to_id", type=int)
def cmd_br_diff(from_id=None, to_id=None):
    """Diff two business rule snapshots"""
    from roam.business_rules.snapshot import RuleSnapshot

    db_path = _get_db_path()
    snap = RuleSnapshot(db_path)
    if from_id is None or to_id is None:
        snapshots = snap.list_snapshots(limit=2)
        if len(snapshots) < 2:
            click.echo("Need at least 2 snapshots.")
            return
        from_id = from_id or snapshots[1]["id"]
        to_id = to_id or snapshots[0]["id"]
    result = snap.diff(from_id, to_id)
    if "error" in result:
        click.echo(result["error"])
        return
    click.echo(f"{result['from']['label'] or result['from']['id']} → {result['to']['label'] or result['to']['id']}")
    click.echo(f"  Rules: {result['from']['count']} → {result['to']['count']} ({result['net_change']:+d})")
    if result["added"]:
        click.echo(f"  Added: {len(result['added'])}")
    if result["removed"]:
        click.echo(f"  Removed: {len(result['removed'])}")


@click.command("business-rules-snapshot")
@click.option("--label", default="")
def cmd_br_snapshot(label=""):
    """Create a business rule snapshot"""
    from roam.business_rules.snapshot import RuleSnapshot

    db_path = _get_db_path()
    snap = RuleSnapshot(db_path)
    sid = snap.create(label=label)
    click.echo(f"Snapshot {sid} created" + (f": {label}" if label else ""))


@click.command("business-rules-list")
@click.option("--type", "rule_type", default=None)
@click.option("--domain", default=None)
@click.option("--json", "as_json", is_flag=True)
def cmd_br_list(rule_type=None, domain=None, as_json=False):
    """List all extracted business rules"""
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        q = "SELECT rule_id, rule_type, domain, description, source_file, source_line FROM business_rules WHERE 1=1"
        params = []
        if rule_type:
            q += " AND rule_type=?"
            params.append(rule_type)
        if domain:
            q += " AND domain=?"
            params.append(domain)
        q += " ORDER BY source_file, source_line"
        rows = conn.execute(q, params).fetchall()

    if as_json:
        click.echo(json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False))
    else:
        if not rows:
            click.echo("No rules found.")
            return
        click.echo(f"{'RULE_ID':<50} {'TYPE':<16} {'DOMAIN':<12} DESCRIPTION")
        click.echo("-" * 110)
        for r in rows:
            click.echo(f"{r['rule_id']:<50} {r['rule_type']:<16} {r['domain']:<12} {r['description'][:40]}")


@click.command("business-rules-explain")
@click.argument("rule_id")
@click.option("--json", "as_json", is_flag=True)
def cmd_br_explain(rule_id, as_json=False):
    """Show details of a single business rule"""
    from roam.business_rules.graph import RuleGraph

    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rule = conn.execute("SELECT * FROM business_rules WHERE rule_id=?", (rule_id,)).fetchone()
        if not rule:
            click.echo(f"Rule not found: {rule_id}")
            return
        graph = RuleGraph(db_path)
        related = graph.related(rule_id)

    if as_json:
        click.echo(json.dumps({"rule": dict(rule), "related": related}, indent=2, ensure_ascii=False))
    else:
        r = dict(rule)
        click.echo(f"Rule:    {r['rule_id']}")
        click.echo(f"Type:    {r['rule_type']}")
        click.echo(f"Domain:  {r['domain']}")
        click.echo(f"Flow:    {r['flow']}")
        click.echo(f"Desc:    {r['description']}")
        click.echo(f"Source:  {r['source_file']}:{r['source_line']}")
        click.echo(f"Severity:{r['severity']}")
        if r.get("merge_with"):
            click.echo(f"Merged:  → {r['merge_with']}")
        if related:
            click.echo(f"\nRelated ({len(related)}):")
            for rel in related:
                click.echo(f"  → {rel['rule_id']} [{rel['edge_type']}]")


def _root():
    try:
        from roam.db.connection import find_project_root
        return find_project_root()
    except Exception:
        return "."

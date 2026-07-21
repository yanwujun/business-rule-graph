"""规则图谱构建 — 纯计算，零 LLM

Layer 1: 规则 → 代码溯源 (business_rule_code_edges)
Layer 2: 规则 → 规则关系 (business_rule_edges)
"""
from __future__ import annotations

import json
import sqlite3
import logging

logger = logging.getLogger(__name__)


class RuleGraph:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def build(self) -> dict:
        from .loader import load_rules
        rules = load_rules(self.db_path)
        edges: list[tuple[str, str, str]] = []

        # same_field
        by_field: dict[str, list[str]] = {}
        for r in rules:
            p = r.get("params", {})
            field = p.get("field") or p.get("value") or p.get("status_value") or p.get("exception_message")
            if field:
                by_field.setdefault(str(field)[:60], []).append(r["rule_id"])
        for field, ids in by_field.items():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    edges.append((ids[i], ids[j], "same_field"))

        # same_flow
        by_flow: dict[str, list[str]] = {}
        for r in rules:
            flow = r.get("flow") or ""
            if flow:
                by_flow.setdefault(flow, []).append(r["rule_id"])
        for flow, ids in by_flow.items():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    edges.append((ids[i], ids[j], "same_flow"))

        # conflicts_with / related
        edges.extend(self._detect_conflicts(rules))

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM business_rule_edges")
            conn.executemany("""
                INSERT INTO business_rule_edges(source_rule_id, target_rule_id, edge_type)
                SELECT br1.id, br2.id, ? FROM business_rules br1, business_rules br2
                WHERE br1.rule_id=? AND br2.rule_id=?
            """, [(et, s, t) for s, t, et in edges])
            conn.commit()

        by_type = {}
        for _, _, et in edges:
            by_type[et] = by_type.get(et, 0) + 1
        return {"total_edges": len(edges), "by_type": by_type}

    def _detect_conflicts(self, rules: list[dict]) -> list[tuple[str, str, str]]:
        conflicts = []
        by_field: dict[str, list[dict]] = {}
        for r in rules:
            p = r.get("params", {})
            field = (p.get("field") or p.get("value") or p.get("status_value")
                     or p.get("exception_message"))
            if field:
                by_field.setdefault(str(field)[:60], []).append(r)
        for items in by_field.values():
            if len(items) < 2:
                continue
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    ri, rj = items[i], items[j]
                    if ri["rule_type"] != rj["rule_type"]:
                        conflicts.append((ri["rule_id"], rj["rule_id"], "conflicts_with"))
                    elif ri["source_file"] != rj["source_file"]:
                        conflicts.append((ri["rule_id"], rj["rule_id"], "related"))
        return conflicts

    def stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            rules = conn.execute("SELECT COUNT(*) FROM business_rules").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM business_rule_edges").fetchone()[0]
        return {"rules": rules, "edges": edges}

    def related(self, rule_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT br.rule_id, br.rule_type, br.domain, br.description,
                       bre.edge_type
                FROM business_rule_edges bre
                JOIN business_rules br ON (
                    (bre.target_rule_id = br.id AND bre.source_rule_id = (SELECT id FROM business_rules WHERE rule_id=?))
                    OR (bre.source_rule_id = br.id AND bre.target_rule_id = (SELECT id FROM business_rules WHERE rule_id=?))
                )
            """, (rule_id, rule_id)).fetchall()
        return [dict(r) for r in rows]

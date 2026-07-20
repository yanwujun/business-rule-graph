"""规则图谱构建 — 纯计算，零 LLM

Layer 1: 规则 → 代码溯源 (business_rule_code_edges)
  implemented_by: 规则 → symbol (方法/类)
  constrains: 规则 → symbol (字段/实体)

Layer 2: 规则 → 规则关系 (business_rule_edges)
  same_field: 约束同一字段的规则
  same_flow: 同一业务流程的规则
  conflicts_with: 同字段同操作符但阈值不同的规则
"""
from __future__ import annotations

import json
import sqlite3
import logging

logger = logging.getLogger(__name__)


class RuleGraph:
    """业务规则图谱 — 从 SQLite 规则表自动推断边关系"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def build(self) -> dict:
        """构建完整图谱，返回统计"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # 加载所有规则
            rows = conn.execute("SELECT * FROM business_rules").fetchall()

        rules = [dict(r) for r in rows]
        edges: list[tuple[str, str, str]] = []

        # ---- same_field ----
        by_field: dict[str, list[str]] = {}
        for r in rules:
            try:
                params = json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]
            except (json.JSONDecodeError, TypeError):
                params = {}
            field = params.get("field") or params.get("value") or params.get("status_value")
            if field:
                by_field.setdefault(str(field), []).append(r["rule_id"])

        for field, rule_ids in by_field.items():
            for i in range(len(rule_ids)):
                for j in range(i + 1, len(rule_ids)):
                    edges.append((rule_ids[i], rule_ids[j], "same_field"))

        # ---- same_flow ----
        by_flow: dict[str, list[str]] = {}
        for r in rules:
            flow = r.get("flow") or ""
            if flow:
                by_flow.setdefault(flow, []).append(r["rule_id"])

        for flow, rule_ids in by_flow.items():
            for i in range(len(rule_ids)):
                for j in range(i + 1, len(rule_ids)):
                    edges.append((rule_ids[i], rule_ids[j], "same_flow"))

        # ---- conflicts_with: same_field + same_type + diff threshold ----
        conflicts = self._detect_conflicts(rules)
        edges.extend(conflicts)

        # Write
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM business_rule_edges")
            conn.executemany("""
                INSERT INTO business_rule_edges
                    (source_rule_id, target_rule_id, edge_type)
                SELECT br1.id, br2.id, ?
                FROM business_rules br1, business_rules br2
                WHERE br1.rule_id = ? AND br2.rule_id = ?
            """, [(et, s, t) for s, t, et in edges])
            conn.commit()

        by_type = {}
        for _, _, et in edges:
            by_type[et] = by_type.get(et, 0) + 1

        return {"total_edges": len(edges), "by_type": by_type}

    def _detect_conflicts(self, rules: list[dict]) -> list[tuple[str, str, str]]:
        """跨类型规则冲突检测"""
        conflicts = []

        # Group rules by params field/value for cross-type comparison
        by_field: dict[str, list[dict]] = {}
        for r in rules:
            try:
                p = json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]
            except (json.JSONDecodeError, TypeError):
                continue
            field = (p.get("field") or p.get("value") or p.get("status_value")
                     or p.get("exception_message"))
            if field:
                by_field.setdefault(str(field)[:60], []).append(r)

        # Same field, different rules → potential conflict
        for field, items in by_field.items():
            if len(items) < 2:
                continue
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    ri, rj = items[i], items[j]
                    # Same field + different type → potential semantic conflict
                    if ri["rule_type"] != rj["rule_type"]:
                        conflicts.append((ri["rule_id"], rj["rule_id"], "conflicts_with"))
                    # Same type but different source → duplicate or split logic
                    elif ri["source_file"] != rj["source_file"]:
                        conflicts.append((ri["rule_id"], rj["rule_id"], "related"))

        return conflicts

    def stats(self) -> dict:
        """图谱统计"""
        with sqlite3.connect(self.db_path) as conn:
            rules = conn.execute("SELECT COUNT(*) FROM business_rules").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM business_rule_edges").fetchone()[0]
        return {"rules": rules, "edges": edges}

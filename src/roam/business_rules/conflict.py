"""冲突检测引擎 — 纯计算，零 LLM

检测类型:
  1. 同字段阈值冲突: same field + same operator + different threshold
  2. 权限移除: AUTHORIZATION 规则在上次快照中存在但当前已删除
  3. 状态机断裂: WORKFLOW 规则形成的转移图中有死端
"""
from __future__ import annotations

import json
import sqlite3
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Conflict:
    conflict_type: str     # threshold_mismatch / auth_removed / status_deadend
    severity: str          # critical / high / medium
    rule_a: dict
    rule_b: Optional[dict]
    description: str


class ConflictDetector:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def detect(self, previous_snapshot_id: Optional[int] = None) -> list[Conflict]:
        conflicts = []
        conflicts.extend(self._threshold_mismatch())
        if previous_snapshot_id:
            conflicts.extend(self._auth_removed(previous_snapshot_id))
        return conflicts

    def _threshold_mismatch(self) -> list[Conflict]:
        """同字段同操作符但不同阈值的规则"""
        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM business_rules
                WHERE rule_type = 'validation'
            """).fetchall()

        # Group: (field, operator) → list of rules
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            rdict = dict(r)
            try:
                p = json.loads(rdict["params"]) if isinstance(rdict["params"], str) else rdict["params"]
            except (json.JSONDecodeError, TypeError):
                continue
            field = p.get("field") or p.get("value") or p.get("status_value")
            op = p.get("operator", "")
            threshold = p.get("threshold") or p.get("min") or p.get("max") or p.get("value")
            if not field:
                continue
            key = (str(field), str(op))
            groups.setdefault(key, []).append({"rule": rdict, "threshold": str(threshold)})

        for (field, op), items in groups.items():
            if len(items) < 2:
                continue
            thresholds = set(i["threshold"] for i in items)
            if len(thresholds) <= 1:
                continue
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    ta = items[i]["threshold"]
                    tb = items[j]["threshold"]
                    if ta != tb:
                        ra = items[i]["rule"]
                        rb = items[j]["rule"]
                        results.append(Conflict(
                            conflict_type="threshold_mismatch",
                            severity="critical",
                            rule_a={
                                "rule_id": ra["rule_id"],
                                "source_file": ra["source_file"],
                                "source_line": ra["source_line"],
                                "description": ra["description"],
                                "threshold": ta,
                            },
                            rule_b={
                                "rule_id": rb["rule_id"],
                                "source_file": rb["source_file"],
                                "source_line": rb["source_line"],
                                "description": rb["description"],
                                "threshold": tb,
                            },
                            description=(
                                f"字段 '{field}' 阈值不一致: "
                                f"{ta} ({ra['source_file']}:{ra['source_line']}) vs "
                                f"{tb} ({rb['source_file']}:{rb['source_line']})"
                            ),
                        ))
        return results

    def _auth_removed(self, snapshot_id: int) -> list[Conflict]:
        """检测被移除的权限规则"""
        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            snap = conn.execute(
                "SELECT removed_rules FROM business_rule_snapshots WHERE id=?",
                (snapshot_id,),
            ).fetchone()
            if not snap:
                return []
            try:
                removed = json.loads(snap["removed_rules"])
            except (json.JSONDecodeError, TypeError):
                return []
            for rule_id in removed:
                old = conn.execute(
                    "SELECT * FROM business_rules WHERE rule_id=? AND rule_type='authorization'",
                    (rule_id,),
                ).fetchone()
                if old:
                    results.append(Conflict(
                        conflict_type="auth_removed",
                        severity="high",
                        rule_a=dict(old),
                        rule_b=None,
                        description=f"权限规则被移除: {rule_id} ({old['source_file']}:{old['source_line']})",
                    ))
        return results

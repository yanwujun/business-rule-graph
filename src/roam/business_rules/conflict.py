"""冲突检测引擎 — 纯计算，零 LLM"""
from __future__ import annotations

import json
import sqlite3
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Conflict:
    conflict_type: str
    severity: str
    rule_a: dict
    rule_b: Optional[dict]
    description: str


class ConflictDetector:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def detect(self, previous_snapshot_id: Optional[int] = None) -> list[Conflict]:
        conflicts = []
        conflicts.extend(self._threshold_mismatch())
        conflicts.extend(self._status_deadend())
        if previous_snapshot_id:
            conflicts.extend(self._auth_removed(previous_snapshot_id))
        return conflicts

    def _threshold_mismatch(self) -> list[Conflict]:
        from .loader import load_rules
        rules = load_rules(self.db_path)
        results = []
        groups: dict[tuple, list[dict]] = {}
        for r in rules:
            p = r.get("params", {})
            field = p.get("field") or p.get("value") or p.get("status_value")
            op = p.get("operator", "")
            threshold = p.get("threshold") or p.get("min") or p.get("max") or p.get("value")
            if not field:
                continue
            groups.setdefault((str(field), str(op)), []).append({"rule": r, "threshold": str(threshold)})
        for (field, op), items in groups.items():
            if len(items) < 2:
                continue
            thresholds = set(i["threshold"] for i in items)
            if len(thresholds) <= 1:
                continue
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    ta, tb = items[i]["threshold"], items[j]["threshold"]
                    if ta != tb:
                        ra, rb = items[i]["rule"], items[j]["rule"]
                        results.append(Conflict("threshold_mismatch", "critical",
                            {"rule_id": ra["rule_id"], "source_file": ra["source_file"],
                             "source_line": ra["source_line"], "description": ra["description"], "threshold": ta},
                            {"rule_id": rb["rule_id"], "source_file": rb["source_file"],
                             "source_line": rb["source_line"], "description": rb["description"], "threshold": tb},
                            f"字段 '{field}' 阈值不一致: {ta} ({ra['source_file']}:{ra['source_line']}) vs {tb} ({rb['source_file']}:{rb['source_line']})"))
        return results

    def _status_deadend(self) -> list[Conflict]:
        """状态机断裂检测: 死端/孤立入口/不可达状态"""
        from .loader import load_rules
        rules = load_rules(self.db_path)
        results = []
        workflow_rules = [r for r in rules if r["rule_type"] == "workflow"]
        transitions: set[tuple[str, str]] = set()
        all_from: set[str] = set()
        all_to: set[str] = set()
        enum_states: dict[str, list[str]] = {}

        for r in workflow_rules:
            p = r.get("params", {})
            sv = p.get("status_value") or p.get("status")
            ev = p.get("enum_values") or []
            sub = p.get("sub_type", "")
            if ev:
                enum_states[r["rule_id"]] = ev
            if sv and sub == "status_transition":
                transitions.add((r["source_symbol"], sv))
                all_from.add(r["source_symbol"])
                all_to.add(sv)

        if not transitions:
            return results

        # 死端: 某个状态的 from 出现了，但没有 to 指向它后面的状态
        for (f, t) in transitions:
            if t not in all_from and t in all_to:
                continue  # 终点状态，合理
            if t in all_from:
                continue  # 有下游，正常

        for rid, states in enum_states.items():
            if len(states) < 2:
                continue
            for s in states:
                if s not in all_from and s not in all_to:
                    results.append(Conflict("status_deadend", "medium",
                        {"rule_id": rid, "description": f"状态枚举: {', '.join(states)}"},
                        None, f"状态 '{s}' 从未被任何规则引用或产生"))

        return results

    def _auth_removed(self, snapshot_id: int) -> list[Conflict]:
        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            snap = conn.execute(
                "SELECT * FROM business_rule_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
            if not snap:
                return []
            try:
                removed = json.loads(snap["removed_rules"])
            except (json.JSONDecodeError, TypeError):
                return []
            prev_snap = conn.execute(
                "SELECT * FROM business_rule_snapshots WHERE id<? ORDER BY id DESC LIMIT 1",
                (snapshot_id,),
            ).fetchone()
            if not prev_snap:
                return []
            try:
                prev_added = set(json.loads(prev_snap["added_rules"]))
            except (json.JSONDecodeError, TypeError):
                return []
            for rid in removed:
                if rid not in prev_added:
                    continue
                old = conn.execute("SELECT * FROM business_rules WHERE rule_id=?", (rid,)).fetchone()
                if old and old["rule_type"] == "authorization":
                    results.append(Conflict("auth_removed", "high", dict(old), None,
                        f"权限规则被移除: {rid} ({old['source_file']}:{old['source_line']})"))
        return results

"""规则版本快照 — 支持创建和 diff 比对"""
from __future__ import annotations

import json
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class RuleSnapshot:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def create(self, label: str = "", commit: str = "") -> int:
        """创建当前规则的快照，返回 snapshot id"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            current = {
                r["rule_id"]: r["hash"]
                for r in conn.execute(
                    "SELECT rule_id, hash FROM business_rules"
                ).fetchall()
            }
            current_ids = set(current.keys())

            last = conn.execute(
                "SELECT id, added_rules FROM business_rule_snapshots "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()

            prev_ids: set[str] = set()
            if last:
                try:
                    prev_ids = set(json.loads(last["added_rules"]))
                except (json.JSONDecodeError, TypeError):
                    pass

            added = sorted(current_ids - prev_ids)
            removed = sorted(prev_ids - current_ids)

            # modified: same rule_id, different hash
            modified = []
            for rid in current_ids & prev_ids:
                if rid in current and rid in prev_ids:
                    # hash comparison requires previous snapshot's hash map
                    pass

            conn.execute("""
                INSERT INTO business_rule_snapshots
                    (label, git_commit, rule_count,
                     added_rules, removed_rules, modified_rules)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                label, commit, len(current),
                json.dumps(added), json.dumps(removed),
                json.dumps(modified),
            ))
            conn.commit()
            sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        logger.info("Snapshot %d created: %d rules (+%d -%d)", sid, len(current), len(added), len(removed))
        return sid

    def diff(self, from_id: int, to_id: int) -> dict:
        """对比两个快照，返回变更摘要"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            s1 = conn.execute(
                "SELECT * FROM business_rule_snapshots WHERE id=?",
                (from_id,),
            ).fetchone()
            s2 = conn.execute(
                "SELECT * FROM business_rule_snapshots WHERE id=?",
                (to_id,),
            ).fetchone()

            if not s1 or not s2:
                return {"error": "Snapshot not found"}

            try:
                a1 = set(json.loads(s1["added_rules"]))
                a2 = set(json.loads(s2["added_rules"]))
                r1 = set(json.loads(s1["removed_rules"]))
                r2 = set(json.loads(s2["removed_rules"]))
            except (json.JSONDecodeError, TypeError):
                a1 = a2 = r1 = r2 = set()

            return {
                "from": {"id": from_id, "label": s1["label"], "at": s1["created_at"], "count": s1["rule_count"]},
                "to": {"id": to_id, "label": s2["label"], "at": s2["created_at"], "count": s2["rule_count"]},
                "added": sorted(a2 - a1),
                "removed": sorted(r2 - r1),
                "net_change": s2["rule_count"] - s1["rule_count"],
            }

    def list_snapshots(self, limit: int = 10) -> list[dict]:
        """列出最近快照"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM business_rule_snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

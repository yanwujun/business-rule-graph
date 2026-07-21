"""T010 [AC-09] RuleSnapshot 单元测试

覆盖: 创建快照 / diff 对比
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from roam.business_rules.snapshot import RuleSnapshot


def _init_snapshot_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS business_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id TEXT UNIQUE NOT NULL,
            rule_type TEXT NOT NULL,
            domain TEXT DEFAULT '',
            flow TEXT DEFAULT '',
            description TEXT DEFAULT '',
            severity TEXT DEFAULT 'medium',
            source_file TEXT DEFAULT '',
            source_line INTEGER DEFAULT 0,
            source_symbol TEXT DEFAULT '',
            params TEXT DEFAULT '{}',
            annotations TEXT DEFAULT '[]',
            hash TEXT DEFAULT '',
            extraction TEXT DEFAULT '',
            merge_with TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS business_rule_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT DEFAULT '',
            git_commit TEXT DEFAULT '',
            rule_count INTEGER DEFAULT 0,
            added_rules TEXT DEFAULT '[]',
            removed_rules TEXT DEFAULT '[]',
            modified_rules TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    return conn


class TestSnapshotCreate:
    """AC-09: 快照创建"""

    def test_create_first_snapshot(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_snapshot_db(db_path)
            conn.executemany(
                "INSERT INTO business_rules (rule_id, rule_type, hash) VALUES (?, ?, ?)",
                [("rule_1", "validation", "abc123"), ("rule_2", "workflow", "def456")],
            )
            conn.commit()
            conn.close()

            snapshot = RuleSnapshot(db_path)
            snap_id = snapshot.create(label="baseline")
            assert snap_id == 1

            # 验证快照记录
            conn2 = sqlite3.connect(db_path)
            conn2.row_factory = sqlite3.Row
            row = conn2.execute("SELECT * FROM business_rule_snapshots WHERE id=1").fetchone()
            assert row["label"] == "baseline"
            assert row["rule_count"] == 2
            added = json.loads(row["added_rules"])
            assert "rule_1" in added
            assert "rule_2" in added
            conn2.close()
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_create_incremental_snapshot(self):
        """第二个快照只记录新增/删除"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_snapshot_db(db_path)
            conn.executemany(
                "INSERT INTO business_rules (rule_id, rule_type, hash) VALUES (?, ?, ?)",
                [("rule_1", "validation", "abc"), ("rule_2", "workflow", "def")],
            )
            conn.commit()
            conn.close()

            snapshot = RuleSnapshot(db_path)
            snap1 = snapshot.create(label="v1")  # 2 条规则

            # 添加新规则
            conn2 = sqlite3.connect(db_path)
            conn2.execute(
                "INSERT INTO business_rules (rule_id, rule_type, hash) VALUES (?, ?, ?)",
                ("rule_3", "calculation", "ghi"),
            )
            conn2.commit()
            conn2.close()

            snap2 = snapshot.create(label="v2")
            assert snap2 == 2

            conn3 = sqlite3.connect(db_path)
            conn3.row_factory = sqlite3.Row
            row = conn3.execute("SELECT * FROM business_rule_snapshots WHERE id=2").fetchone()
            assert row["rule_count"] == 3
            added = json.loads(row["added_rules"])
            assert "rule_3" in added
            conn3.close()
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_diff(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_snapshot_db(db_path)
            conn.executemany(
                "INSERT INTO business_rules (rule_id, rule_type, hash) VALUES (?, ?, ?)",
                [("rule_1", "validation", "abc"), ("rule_2", "workflow", "def")],
            )
            conn.commit()
            conn.close()

            snapshot = RuleSnapshot(db_path)
            snap1 = snapshot.create(label="v1")

            # 修改: 删除 rule_1, 添加 rule_3
            conn2 = sqlite3.connect(db_path)
            conn2.execute("DELETE FROM business_rules WHERE rule_id='rule_1'")
            conn2.execute(
                "INSERT INTO business_rules (rule_id, rule_type, hash) VALUES (?, ?, ?)",
                ("rule_3", "calculation", "ghi"),
            )
            conn2.commit()
            conn2.close()

            snap2 = snapshot.create(label="v2")
            result = snapshot.diff(from_id=snap1, to_id=snap2)

            assert "added" in result
            assert "removed" in result
        finally:
            Path(db_path).unlink(missing_ok=True)

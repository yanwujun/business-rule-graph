"""T009 [AC-06/07/08] ConflictDetector 单元测试

覆盖: 阈值冲突 / 权限移除 / 状态机断裂（死端 + 孤立入口 + 不可达）
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from roam.business_rules.conflict import ConflictDetector


def _init_db(db_path: str):
    """创建 business_rules 测试表"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
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
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS business_rule_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT DEFAULT '',
            git_commit TEXT DEFAULT '',
            rule_count INTEGER DEFAULT 0,
            added_rules TEXT DEFAULT '[]',
            removed_rules TEXT DEFAULT '[]',
            modified_rules TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _insert_rule(conn, rule_id, rule_type, source_file="test.java", source_line=1,
                 source_symbol="testMethod", params=None, description=""):
    conn.execute("""
        INSERT OR REPLACE INTO business_rules
        (rule_id, rule_type, source_file, source_line, source_symbol, params, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (rule_id, rule_type, source_file, source_line, source_symbol,
          json.dumps(params or {}), description))
    conn.commit()


class TestThresholdMismatch:
    """AC-06: 阈值冲突检测"""

    def test_same_field_different_threshold(self):
        """同字段 total 阈值 100 vs 50 → critical 冲突"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_db(db_path)
            _insert_rule(conn, "OrderService:145:if-throw", "validation",
                         params={"field": "total", "operator": ">=", "threshold": "100"},
                         description="金额>=100")
            _insert_rule(conn, "PaymentService:89:if-throw", "validation",
                         params={"field": "total", "operator": ">=", "threshold": "50"},
                         description="金额>=50")
            conn.close()

            detector = ConflictDetector(db_path)
            conflicts = detector._threshold_mismatch()
            assert len(conflicts) == 1
            assert conflicts[0].conflict_type == "threshold_mismatch"
            assert conflicts[0].severity == "critical"
            assert "total" in conflicts[0].description
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_same_field_same_threshold_no_conflict(self):
        """同字段相同阈值 → 无冲突"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_db(db_path)
            _insert_rule(conn, "A:1:if-throw", "validation",
                         params={"field": "total", "threshold": "100"})
            _insert_rule(conn, "B:1:if-throw", "validation",
                         params={"field": "total", "threshold": "100"})
            conn.close()

            detector = ConflictDetector(db_path)
            conflicts = detector._threshold_mismatch()
            assert len(conflicts) == 0
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_different_fields_no_conflict(self):
        """不同字段 → 无冲突"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_db(db_path)
            _insert_rule(conn, "A:1:if-throw", "validation",
                         params={"field": "total", "threshold": "100"})
            _insert_rule(conn, "B:1:if-throw", "validation",
                         params={"field": "amount", "threshold": "50"})
            conn.close()

            detector = ConflictDetector(db_path)
            conflicts = detector._threshold_mismatch()
            assert len(conflicts) == 0
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestStatusDeadend:
    """AC-08: 状态机断裂检测"""

    def test_deadend_state_detected(self):
        """DRAFT→SUBMITTED→APPROVED, APPROVED 无出边 → 死端"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_db(db_path)
            _insert_rule(conn, "Flow:10:status-check", "workflow",
                         source_symbol="DRAFT",
                         params={"status_value": "SUBMITTED", "sub_type": "status_transition"})
            _insert_rule(conn, "Flow:20:status-check", "workflow",
                         source_symbol="SUBMITTED",
                         params={"status_value": "APPROVED", "sub_type": "status_transition"})
            _insert_rule(conn, "StatusEnum:1:status-enum", "workflow",
                         params={"enum_values": ["DRAFT", "SUBMITTED", "APPROVED", "ARCHIVED"]})
            conn.close()

            detector = ConflictDetector(db_path)
            conflicts = detector._status_deadend()
            # APPROVED 只有入边无出边 → 死端
            deadends = [c for c in conflicts if c.conflict_type == "status_deadend"]
            assert len(deadends) >= 1
            assert any("APPROVED" in c.description for c in deadends)
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_unreachable_enum_state(self):
        """枚举定义 CANCELED 但无规则引用 → 不可达"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_db(db_path)
            _insert_rule(conn, "Flow:10:status-check", "workflow",
                         source_symbol="DRAFT",
                         params={"status_value": "SUBMITTED", "sub_type": "status_transition"})
            _insert_rule(conn, "StatusEnum:1:status-enum", "workflow",
                         params={"enum_values": ["DRAFT", "SUBMITTED", "APPROVED", "CANCELED"]})
            conn.close()

            detector = ConflictDetector(db_path)
            conflicts = detector._status_deadend()
            # CANCELED 从未被任何规则引用
            unreachable = [c for c in conflicts if c.conflict_type == "status_deadend"]
            assert any("CANCELED" in c.description for c in unreachable)
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_no_transitions_no_error(self):
        """无 workflow 转移规则 → 不崩溃"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_db(db_path)
            _insert_rule(conn, "Other:1:if-throw", "validation",
                         params={"field": "total", "threshold": "100"})
            conn.close()

            detector = ConflictDetector(db_path)
            conflicts = detector._status_deadend()
            assert len(conflicts) == 0
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestAuthRemoved:
    """AC-07: 权限移除检测"""

    def test_auth_rule_removed_after_snapshot(self):
        """基线有 auth 规则，当前已删除 → 检出"""
        # 注意: _auth_removed 依赖快照表，此处验证方法存在且可调用
        # 完整集成测试需先创建快照再删除规则
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = _init_db(db_path)
            # 插入一条 auth 规则和两个快照
            _insert_rule(conn, "AuthCheck:10:auth-annotation", "authorization",
                         source_symbol="checkAuth",
                         description="权限检查")
            # 快照1: 包含 auth 规则
            conn.execute("""
                INSERT INTO business_rule_snapshots (id, label, added_rules, removed_rules)
                VALUES (1, 'baseline', '["AuthCheck:10:auth-annotation"]', '[]')
            """)
            # 快照2: auth 规则被移除
            conn.execute("""
                INSERT INTO business_rule_snapshots (id, label, added_rules, removed_rules)
                VALUES (2, 'after_change', '[]', '["AuthCheck:10:auth-annotation"]')
            """)
            conn.commit()
            conn.close()

            detector = ConflictDetector(db_path)
            conflicts = detector._auth_removed(snapshot_id=2)
            assert len(conflicts) == 1
            assert conflicts[0].conflict_type == "auth_removed"
            assert conflicts[0].severity == "high"
        finally:
            Path(db_path).unlink(missing_ok=True)

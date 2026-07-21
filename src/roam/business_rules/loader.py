"""共享数据加载器 — graph.py + conflict.py 去重"""
from __future__ import annotations

import json
import sqlite3


def load_rules(db_path: str) -> list[dict]:
    """加载所有业务规则，自动解析 params JSON"""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM business_rules ORDER BY source_file, source_line"
        ).fetchall()
    rules = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d["params"]) if isinstance(d["params"], str) else d["params"]
        except (json.JSONDecodeError, TypeError):
            d["params"] = {}
        try:
            d["annotations"] = json.loads(d["annotations"]) if isinstance(d["annotations"], str) else d["annotations"]
        except (json.JSONDecodeError, TypeError):
            d["annotations"] = []
        rules.append(d)
    return rules

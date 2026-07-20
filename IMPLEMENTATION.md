# Business Rule Graph — 实施计划

> 项目: https://github.com/yanwujun/business-rule-graph
> 基座: roam-code v13
> 原则: 纯 AST，零 LLM；LLM 为可选增强层

---

## 前置检查

```bash
cd /home/administrator/business-rule-graph
pip install -e ".[mcp]"
# 验证 roam 命令可用
python -m roam version
```

---

## M1: 规则提取 MVP（2-3天）

### 目标
在 P2040 项目上跑通 `roam business-rules extract`，能从 Java 代码提取业务规则到 SQLite。

### 1.1 模块骨架

创建目录和空文件：
```
src/roam/business_rules/
├── __init__.py          # 空
├── models.py            # RuleType 枚举 + BusinessRule dataclass
├── patterns.py          # ANNOTATION_RULE_MAP + AST 查询模式
├── extractor.py         # 核心提取器
└── commands/
    ├── __init__.py
    └── cmd_br_extract.py
```

### 1.2 `models.py` — 数据模型

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class RuleType(str, Enum):
    """8 种业务规则类型 — 吸收自 diff-to-business-rules"""
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    WORKFLOW = "workflow"
    CALCULATION = "calculation"
    DATA_INTEGRITY = "data_integrity"
    PROCESS = "process"
    CONFIGURATION = "configuration"
    INTEGRATION = "integration"

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class BusinessRule:
    rule_id: str                    # "OrderService.validateOrder.@Min.total"
    rule_type: RuleType
    domain: str = ""                # 从包名推断
    flow: str = ""                  # 从类名推断
    description: str = ""           # 模板生成
    severity: Severity = Severity.MEDIUM
    source_file: str = ""
    source_line: int = 0
    source_symbol: str = ""         # 方法名/类名
    params: dict = field(default_factory=dict)
    annotations: list = field(default_factory=list)
    symbols: list = field(default_factory=list)  # 关联的 roam-code symbol IDs

    def compute_hash(self) -> str:
        """SHA256 of (source_file + source_symbol + str(sorted(params)))"""
        import hashlib, json
        payload = f"{self.source_file}|{self.source_symbol}|{json.dumps(self.params, sort_keys=True)}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
```

### 1.3 `patterns.py` — 注解→规则映射 + tree-sitter 查询

```python
from .models import RuleType, Severity

# ============================================================
# 注解 → (规则类型, 操作符, 参数提取方式)
# ============================================================
ANNOTATION_RULE_MAP = {
    # ---- validation ----
    "NotNull":   (RuleType.VALIDATION, "required", None, Severity.MEDIUM),
    "NotBlank":  (RuleType.VALIDATION, "required", None, Severity.MEDIUM),
    "NotEmpty":  (RuleType.VALIDATION, "required", None, Severity.MEDIUM),
    "Min":       (RuleType.VALIDATION, ">=", "value", Severity.MEDIUM),
    "Max":       (RuleType.VALIDATION, "<=", "value", Severity.MEDIUM),
    "DecimalMin":(RuleType.VALIDATION, ">=", "value", Severity.MEDIUM),
    "DecimalMax":(RuleType.VALIDATION, "<=", "value", Severity.MEDIUM),
    "Size":      (RuleType.VALIDATION, "size", ["min","max"], Severity.MEDIUM),
    "Length":    (RuleType.VALIDATION, "size", ["min","max"], Severity.MEDIUM),
    "Pattern":   (RuleType.VALIDATION, "regexp", "regexp", Severity.MEDIUM),
    "Email":     (RuleType.VALIDATION, "email", None, Severity.MEDIUM),
    "Positive":  (RuleType.VALIDATION, ">", "0", Severity.LOW),
    "Negative":  (RuleType.VALIDATION, "<", "0", Severity.LOW),
    "Valid":     (RuleType.VALIDATION, "cascade", None, Severity.MEDIUM),
    "Validated": (RuleType.VALIDATION, "cascade", None, Severity.MEDIUM),

    # ---- authorization ----
    "PreAuthorize":    (RuleType.AUTHORIZATION, "spel", "value", Severity.HIGH),
    "PostAuthorize":   (RuleType.AUTHORIZATION, "spel", "value", Severity.HIGH),
    "RolesAllowed":    (RuleType.AUTHORIZATION, "roles", "value", Severity.HIGH),
    "Secured":         (RuleType.AUTHORIZATION, "secured", "value", Severity.HIGH),
    "PreFilter":       (RuleType.AUTHORIZATION, "filter", "value", Severity.HIGH),
    "PostFilter":      (RuleType.AUTHORIZATION, "filter", "value", Severity.HIGH),
    "PermitAll":       (RuleType.AUTHORIZATION, "permit_all", None, Severity.LOW),
    "DenyAll":         (RuleType.AUTHORIZATION, "deny_all", None, Severity.CRITICAL),

    # ---- data_integrity ----
    "Column":          (RuleType.DATA_INTEGRITY, "column", None, Severity.MEDIUM),
    "UniqueConstraint":(RuleType.DATA_INTEGRITY, "unique", None, Severity.MEDIUM),

    # ---- integration ----
    "Retryable":       (RuleType.INTEGRATION, "retry", None, Severity.MEDIUM),
    "CircuitBreaker":  (RuleType.INTEGRATION, "circuit_breaker", None, Severity.HIGH),
    "Bulkhead":        (RuleType.INTEGRATION, "bulkhead", None, Severity.MEDIUM),
    "RateLimiter":     (RuleType.INTEGRATION, "rate_limit", None, Severity.MEDIUM),

    # ---- configuration ----
    "Value":           (RuleType.CONFIGURATION, "property", "value", Severity.LOW),
    "ConfigurationProperties": (RuleType.CONFIGURATION, "prefix", "prefix", Severity.LOW),

    # ---- workflow ----
    "Transactional":   (RuleType.WORKFLOW, "transactional", None, Severity.MEDIUM),
    "EventListener":   (RuleType.PROCESS, "event", "value", Severity.MEDIUM),
    "Scheduled":       (RuleType.PROCESS, "scheduled", "cron", Severity.LOW),
    "Async":           (RuleType.PROCESS, "async", None, Severity.LOW),
}

# ============================================================
# 方法命名模式 → 规则类型
# ============================================================
METHOD_NAME_PATTERNS = {
    #
    # data_integrity
    "existsBy":         (RuleType.DATA_INTEGRITY, "unique_check"),
    "countBy":          (RuleType.DATA_INTEGRITY, "count_check"),
    "findBy.*And":      (RuleType.DATA_INTEGRITY, "compound_query"),
    #
    # workflow
    "setStatus":        (RuleType.WORKFLOW, "status_transition"),
    "changeStatus":     (RuleType.WORKFLOW, "status_transition"),
    "updateStatus":     (RuleType.WORKFLOW, "status_transition"),
    "transitionTo":     (RuleType.WORKFLOW, "status_transition"),
    #
    # validation
    "validate":         (RuleType.VALIDATION, "custom_validate"),
    "check":            (RuleType.VALIDATION, "custom_check"),
    "assert":           (RuleType.VALIDATION, "custom_assert"),
    "verify":           (RuleType.VALIDATION, "custom_verify"),
    #
    # calculation
    "calculate":        (RuleType.CALCULATION, "compute"),
    "compute":          (RuleType.CALCULATION, "compute"),
    "getDiscount":      (RuleType.CALCULATION, "discount"),
    "getTax":           (RuleType.CALCULATION, "tax"),
    "getCommission":    (RuleType.CALCULATION, "commission"),
    "getFee":           (RuleType.CALCULATION, "fee"),
}

# ============================================================
# tree-sitter AST 查询模式 — 补充注解之外的规则
# ============================================================
TREE_SITTER_QUERIES = {
    # if (condition) throw new XxxException — validation 规则
    "if_throw_validation": """
        (if_statement
          condition: (_)
          consequence: (block
            (expression_statement
              (object_creation_expression
                type: (type_identifier) @exception_type
                (#match? @exception_type ".*Exception")
              )
            )
          )
        )
    """,

    # switch (status) { case X: case Y: } — workflow 规则
    "switch_on_status": """
        (switch_expression
          condition: (identifier) @switch_var
          (#match? @switch_var ".*[Ss]tatus$")
          body: (switch_block
            (switch_block_statement_group)+
          )
        )
    """,

    # enum XxxStatus — workflow 规则
    "status_enum": """
        (enum_declaration
          name: (identifier) @enum_name
          (#match? @enum_name ".*[Ss]tatus$")
        )
    """,

    # BigDecimal operations — calculation 规则
    "bigdecimal_ops": """
        (method_invocation
          object: (identifier) @var
          name: (identifier) @method
          (#match? @method "^(add|subtract|multiply|divide)$")
        )
    """,
}


def domain_from_package(package: str) -> str:
    """从 Java 包名推断业务域"""
    parts = package.replace("com.xcj.", "").split(".")
    domain_map = {
        "order": "订单管理", "trade": "交易管理",
        "supplier": "供应商管理", "provider": "供应商管理",
        "product": "商品管理", "goods": "商品管理",
        "user": "用户管理", "member": "会员管理",
        "payment": "支付管理", "pay": "支付管理",
        "contract": "合同管理", "agreement": "协议管理",
        "framework": "框架协议", "direct": "直采商城",
        "mall": "商城管理", "cart": "购物车",
        "audit": "审核管理", "approval": "审批管理",
        "logistics": "物流管理", "delivery": "配送管理",
        "invoice": "发票管理", "bill": "账单管理",
        "report": "报表管理", "statistics": "统计分析",
        "message": "消息管理", "notification": "通知管理",
        "system": "系统管理", "admin": "管理后台",
        "config": "配置管理", "setting": "系统设置",
    }
    for key, name in domain_map.items():
        if key in parts:
            return name
    return parts[0] if parts else "未分类"


def flow_from_class(class_name: str) -> str:
    """从类名推断业务流程"""
    flow_map = {
        "Order": "下单", "Trade": "交易",
        "Payment": "支付", "Refund": "退款",
        "Submit": "提交", "Audit": "审核",
        "Approve": "审批", "Review": "审核",
        "Deliver": "发货", "Logistics": "物流",
        "Cart": "购物车", "Inventory": "库存",
        "Price": "定价", "Discount": "折扣",
        "Contract": "签约", "Register": "注册",
        "Login": "登录", "Search": "搜索",
        "Recommend": "推荐", "Report": "报表",
        "Export": "导出", "Import": "导入",
        "Push": "推送", "Sync": "同步",
        "Supplier": "供应商", "Provider": "供应商",
    }
    for key, name in flow_map.items():
        if class_name.startswith(key) or class_name.endswith(key):
            return name
    return class_name
```

### 1.4 `extractor.py` — 核心提取器

```python
"""纯 AST 业务规则提取器 — 零 LLM 依赖"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from .models import BusinessRule, RuleType
from .patterns import (
    ANNOTATION_RULE_MAP,
    METHOD_NAME_PATTERNS,
    domain_from_package,
    flow_from_class,
)

logger = logging.getLogger(__name__)


class BusinessRuleExtractor:
    """从 roam-code index 提取业务规则"""

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)

    def extract(self) -> list[BusinessRule]:
        """主入口：扫描 index.db 中所有 Java symbols，提取业务规则"""
        rules: list[BusinessRule] = []
        seen = set()  # 去重用

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # 查询所有 Java 方法/类
            rows = conn.execute("""
                SELECT s.id, s.name, s.kind, s.signature, s.decorators,
                       s.line_start, s.line_end, s.qualified_name,
                       f.path as file_path
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE f.language = 'java'
                  AND s.kind IN ('method', 'class', 'enum')
                ORDER BY f.path, s.line_start
            """).fetchall()

        for row in rows:
            extracted = self._extract_from_symbol(dict(row))
            for rule in extracted:
                rule_hash = rule.compute_hash()
                if rule_hash not in seen:
                    seen.add(rule_hash)
                    rules.append(rule)

        logger.info(f"Extracted {len(rules)} business rules")
        return rules

    def _extract_from_symbol(self, sym: dict) -> list[BusinessRule]:
        """从单个 symbol 提取所有规则"""
        rules = []
        name = sym["name"]
        file_path = sym["file_path"]
        decorators = (sym.get("decorators") or "").split(",")
        qname = sym.get("qualified_name") or name
        line = sym.get("line_start", 0)

        # 从包名和类名推断 domain/flow
        package = Path(file_path).parent.as_posix().replace("/", ".")
        domain = domain_from_package(package)
        flow = flow_from_class(name)

        # 1) 扫描注解
        for deco in decorators:
            deco = deco.strip()
            if not deco:
                continue
            # 提取注解名和参数: @Min(100) → "Min", "100"
            anno_name, anno_args = self._parse_annotation(deco)
            if anno_name in ANNOTATION_RULE_MAP:
                rt, op, param_key, severity = ANNOTATION_RULE_MAP[anno_name]
                params = self._build_params(op, param_key, anno_args)
                rule = BusinessRule(
                    rule_id=f"{name}.{deco}",
                    rule_type=rt,
                    domain=domain,
                    flow=flow,
                    description=self._describe(rt, op, params),
                    severity=severity,
                    source_file=file_path,
                    source_line=line,
                    source_symbol=name,
                    params=params,
                    annotations=[deco],
                    symbols=[sym["id"]],
                )
                rules.append(rule)

        # 2) 扫描方法命名模式
        for pattern, (rt, sub_type) in METHOD_NAME_PATTERNS.items():
            import re
            if re.match(pattern, name):
                params = {"method": name, "sub_type": sub_type}
                # 避免与注解规则重复
                if not any(r.rule_id.startswith(name) for r in rules):
                    rule = BusinessRule(
                        rule_id=f"{name}.{pattern}",
                        rule_type=rt,
                        domain=domain,
                        flow=flow,
                        description=f"{sub_type}: {name}",
                        source_file=file_path,
                        source_line=line,
                        source_symbol=name,
                        params=params,
                        symbols=[sym["id"]],
                    )
                    rules.append(rule)

        # 3) 枚举类型检测 (status enum)
        if sym.get("kind") == "enum" and "status" in name.lower():
            rule = BusinessRule(
                rule_id=f"{name}.status_enum",
                rule_type=RuleType.WORKFLOW,
                domain=domain,
                flow=flow,
                description=f"状态枚举: {name}",
                severity="medium",
                source_file=file_path,
                source_line=line,
                source_symbol=name,
                params={"enum_name": name},
                symbols=[sym["id"]],
            )
            rules.append(rule)

        return rules

    def _parse_annotation(self, anno_text: str) -> tuple[str, Optional[str]]:
        """解析注解文本: @Min(100) → ("Min", "100"), @NotNull → ("NotNull", None)"""
        text = anno_text.lstrip("@")
        if "(" in text:
            idx = text.index("(")
            name = text[:idx]
            args = text[idx+1:].rstrip(")")
            return name, args
        return text, None

    def _build_params(self, op: str, param_key, args: Optional[str]) -> dict:
        """构建规则参数"""
        params = {"operator": op}
        if args:
            if param_key:
                if isinstance(param_key, list):
                    # @Size(min=1, max=100)
                    for pk in param_key:
                        if pk in args:
                            params[pk] = args
                else:
                    params[param_key] = args
            else:
                params["value"] = args
        return params

    def _describe(self, rt: RuleType, op: str, params: dict) -> str:
        """模板化描述"""
        field = params.get("field", params.get("value", "?"))
        templates = {
            "required": f"字段不能为空",
            ">=": f"值必须 >= {field}",
            "<=": f"值必须 <= {field}",
            "email": "必须为邮箱格式",
            "regexp": f"必须匹配: {field}",
        }
        return templates.get(op, f"{rt.value}: {params}")
```

### 1.5 DB schema 扩展

在 `src/roam/db/schema.py` 的 `SCHEMA_SQL` 末尾追加：

```sql
-- ============================================================
-- Business Rules (business-rule-graph extension)
-- ============================================================
CREATE TABLE IF NOT EXISTS business_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL UNIQUE,
    rule_type TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    flow TEXT DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    severity TEXT DEFAULT 'medium',
    source_file TEXT NOT NULL,
    source_line INTEGER DEFAULT 0,
    source_symbol TEXT NOT NULL DEFAULT '',
    params JSON DEFAULT '{}',
    annotations JSON DEFAULT '[]',
    hash TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_br_type ON business_rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_br_domain ON business_rules(domain);
CREATE INDEX IF NOT EXISTS idx_br_file ON business_rules(source_file);
CREATE INDEX IF NOT EXISTS idx_br_hash ON business_rules(hash);

CREATE TABLE IF NOT EXISTS business_rule_code_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES business_rules(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL DEFAULT 'implemented_by'
);

CREATE INDEX IF NOT EXISTS idx_brce_rule ON business_rule_code_edges(rule_id);
CREATE INDEX IF NOT EXISTS idx_brce_symbol ON business_rule_code_edges(symbol_id);

CREATE TABLE IF NOT EXISTS business_rule_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_rule_id INTEGER NOT NULL REFERENCES business_rules(id) ON DELETE CASCADE,
    target_rule_id INTEGER NOT NULL REFERENCES business_rules(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_bre_source ON business_rule_edges(source_rule_id);
CREATE INDEX IF NOT EXISTS idx_bre_target ON business_rule_edges(target_rule_id);

CREATE TABLE IF NOT EXISTS business_rule_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,
    git_commit TEXT,
    snapshot_at TEXT DEFAULT (datetime('now')),
    rule_count INTEGER DEFAULT 0,
    added_rules JSON DEFAULT '[]',
    removed_rules JSON DEFAULT '[]',
    modified_rules JSON DEFAULT '[]'
);
```

### 1.6 `cmd_br_extract.py` — CLI 命令

```python
"""roam business-rules extract — 从代码提取业务规则"""
from __future__ import annotations

import json
import sqlite3
import click

from roam.db.connection import find_project_root, open_db


@click.command("business-rules-extract")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--update", is_flag=True, help="Incremental: only extract from changed files")
def cmd_br_extract(as_json=False, update=False):
    """Extract business rules from Java/Spring Boot code (pure AST, zero LLM)"""
    db_path = find_project_root() / ".roam" / "index.db"

    if not db_path.exists():
        click.echo("Error: No index found. Run 'roam init' first.", err=True)
        return

    # Lazy import to avoid circular deps
    from roam.business_rules.extractor import BusinessRuleExtractor

    extractor = BusinessRuleExtractor(db_path)
    rules = extractor.extract()

    if not rules:
        click.echo("No business rules detected.")
        return

    # Write to SQLite
    with sqlite3.connect(str(db_path)) as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO business_rules
            (rule_id, rule_type, domain, flow, description, severity,
             source_file, source_line, source_symbol, params, annotations, hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            (r.rule_id, r.rule_type, r.domain, r.flow, r.description,
             r.severity, r.source_file, r.source_line, r.source_symbol,
             json.dumps(r.params, ensure_ascii=False),
             json.dumps(r.annotations, ensure_ascii=False),
             r.compute_hash())
            for r in rules
        ])
        conn.commit()

    # Summary
    by_type = {}
    for r in rules:
        by_type[r.rule_type] = by_type.get(r.rule_type, 0) + 1

    if as_json:
        click.echo(json.dumps({
            "total": len(rules),
            "by_type": by_type,
        }, indent=2, ensure_ascii=False))
    else:
        click.echo(f"✅ Extracted {len(rules)} business rules")
        for rt, count in sorted(by_type.items()):
            click.echo(f"   {rt}: {count}")
```

### 1.7 注册 CLI 命令

在 `src/roam/cli.py` 中添加：

```python
# 在 CLI group 注册处追加:
from roam.business_rules.commands.cmd_br_extract import cmd_br_extract

# 在主命令组添加
cli.add_command(cmd_br_extract, name="business-rules-extract")
```

或者作为子命令组:

```python
@click.group(name="business-rules")
def business_rules_group():
    """Business rule extraction & conflict detection"""
    pass

business_rules_group.add_command(cmd_br_extract, name="extract")
cli.add_command(business_rules_group)
```

### 1.8 验证

```bash
cd /mnt/d/项目/svn/P2040直采与框架协议/某个java模块

# 先建 roam index（如果还没建过）
python -m roam init

# 提取业务规则
python -m roam business-rules extract

# 预期输出:
# ✅ Extracted 42 business rules
#    validation: 18
#    authorization: 8
#    workflow: 6
#    ...
```

---

## M2: 图谱 + 冲突检测（2-3天）

### 目标
`roam business-rules graph` 构建规则图谱，`roam business-rules check` 检测冲突。

### 2.1 `graph.py`

```python
"""规则图谱构建 — 纯计算，零 LLM"""
from __future__ import annotations

import sqlite3
from .models import BusinessRule


class RuleGraph:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def build_edges(self):
        """自动推断规则间关系"""
        rules = self._load_rules()
        edges = []

        # same_field: params["field"] 相同
        by_field = {}
        for r in rules:
            field = r.params.get("field") or r.params.get("value")
            if field:
                by_field.setdefault(field, []).append(r.rule_id)

        for field, rule_ids in by_field.items():
            for i in range(len(rule_ids)):
                for j in range(i+1, len(rule_ids)):
                    edges.append((rule_ids[i], rule_ids[j], "same_field"))

        # same_flow: flow 相同
        by_flow = {}
        for r in rules:
            if r.flow:
                by_flow.setdefault(r.flow, []).append(r.rule_id)

        for flow, rule_ids in by_flow.items():
            for i in range(len(rule_ids)):
                for j in range(i+1, len(rule_ids)):
                    edges.append((rule_ids[i], rule_ids[j], "same_flow"))

        # conflicts_with: same_field + 同类型同操作符但阈值不同
        for field, rule_ids in by_field.items():
            field_rules = [r for r in rules if r.rule_id in rule_ids and r.rule_type == "validation"]
            for i in range(len(field_rules)):
                for j in range(i+1, len(field_rules)):
                    a, b = field_rules[i], field_rules[j]
                    if a.params.get("operator") == b.params.get("operator"):
                        va = a.params.get("threshold") or a.params.get("value")
                        vb = b.params.get("threshold") or b.params.get("value")
                        if va != vb:
                            edges.append((a.rule_id, b.rule_id, "conflicts_with"))

        self._save_edges(edges)
        return edges

    def _load_rules(self) -> list[BusinessRule]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM business_rules").fetchall()
        return [BusinessRule(
            rule_id=r["rule_id"], rule_type=r["rule_type"],
            domain=r["domain"], flow=r["flow"] or "",
            source_file=r["source_file"], source_line=r["source_line"],
            source_symbol=r["source_symbol"],
            params=json.loads(r["params"]),
            annotations=json.loads(r["annotations"]),
        ) for r in rows]

    def _save_edges(self, edges):
        with sqlite3.connect(self.db_path) as conn:
            # 清旧边
            conn.execute("DELETE FROM business_rule_edges")
            conn.executemany("""
                INSERT INTO business_rule_edges (source_rule_id, target_rule_id, edge_type)
                SELECT br1.id, br2.id, ?
                FROM business_rules br1, business_rules br2
                WHERE br1.rule_id = ? AND br2.rule_id = ?
            """, [(edge_type, s, t) for s, t, edge_type in edges])
            conn.commit()
```

### 2.2 `conflict.py`

```python
"""冲突检测引擎 — 纯计算，零 LLM"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Conflict:
    conflict_type: str         # threshold_mismatch / status_deadend / auth_removed
    severity: str              # critical / high / medium
    rule_a: dict               # 规则 A 的摘要
    rule_b: dict               # 规则 B 的摘要（可为 None）
    description: str


class ConflictDetector:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def detect(self, previous_snapshot_id: Optional[int] = None) -> list[Conflict]:
        conflicts = []
        conflicts.extend(self._threshold_mismatch())
        conflicts.extend(self._auth_removed(previous_snapshot_id))
        conflicts.extend(self._status_deadend())
        return conflicts

    def _threshold_mismatch(self) -> list[Conflict]:
        """同字段同操作符但不同阈值"""
        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT br.rule_id, br.rule_type, br.domain, br.source_file,
                       br.source_line, br.source_symbol, br.params, br.description
                FROM business_rules br
                WHERE br.rule_type = 'validation'
                ORDER BY br.params
            """).fetchall()

        # 按 params 中的 field + operator 分组
        groups = {}
        for r in rows:
            try:
                p = json.loads(r["params"])
            except (json.JSONDecodeError, TypeError):
                continue
            field = p.get("field") or p.get("value")
            op = p.get("operator")
            threshold = p.get("threshold") or p.get("min") or p.get("max")
            if not field or not op:
                continue
            key = (field, op)
            groups.setdefault(key, []).append((r, threshold))

        for (field, op), items in groups.items():
            if len(items) < 2:
                continue
            thresholds = set(t for _, t in items)
            if len(thresholds) > 1:
                for i in range(len(items)):
                    for j in range(i+1, len(items)):
                        ra, ta = items[i]
                        rb, tb = items[j]
                        if ta != tb:
                            results.append(Conflict(
                                conflict_type="threshold_mismatch",
                                severity="critical",
                                rule_a=dict(ra),
                                rule_b=dict(rb),
                                description=f"字段 '{field}' 操作符 '{op}' 在不同位置阈值不一致: {ta} vs {tb}"
                            ))
        return results

    def _auth_removed(self, snapshot_id) -> list[Conflict]:
        """当前索引中缺少上一快照中的 AUTHORIZATION 规则"""
        if not snapshot_id:
            return []
        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            snap = conn.execute(
                "SELECT removed_rules FROM business_rule_snapshots WHERE id=?",
                (snapshot_id,)
            ).fetchone()
            if not snap:
                return []
            try:
                removed = json.loads(snap["removed_rules"])
            except (json.JSONDecodeError, TypeError):
                return []
            for rule_id in removed:
                old = conn.execute(
                    "SELECT * FROM business_rules WHERE rule_id=?",
                    (rule_id,)
                ).fetchone()
                if old and old["rule_type"] == "authorization":
                    results.append(Conflict(
                        conflict_type="auth_removed",
                        severity="high",
                        rule_a=dict(old),
                        rule_b=None,
                        description=f"权限规则被移除: {rule_id}"
                    ))
        return results

    def _status_deadend(self) -> list[Conflict]:
        """状态机断裂检测：WORKFLOW 规则形成的转移图中是否有死端"""
        # M2 先跳过，M3 实现完整的图遍历
        return []
```

### 2.3 `cmd_br_check.py` + `cmd_br_graph.py`

```python
# cmd_br_check.py
@click.command("business-rules-check")
@click.option("--json", "as_json", is_flag=True)
def cmd_br_check(as_json=False):
    """Detect business rule conflicts (pure computation, zero LLM)"""
    db_path = find_project_root() / ".roam" / "index.db"
    if not db_path.exists():
        click.echo("Error: No index found.", err=True)
        return

    from roam.business_rules.conflict import ConflictDetector
    detector = ConflictDetector(str(db_path))
    conflicts = detector.detect()

    if as_json:
        click.echo(json.dumps([c.__dict__ for c in conflicts], indent=2, ensure_ascii=False))
    else:
        if not conflicts:
            click.echo("✅ No business rule conflicts detected.")
        else:
            click.echo(f"⚠ Found {len(conflicts)} potential conflicts:\n")
            for c in conflicts:
                click.echo(f"  [{c.severity.upper()}] {c.conflict_type}")
                click.echo(f"  {c.description}\n")

# cmd_br_graph.py
@click.command("business-rules-graph")
@click.option("--stats", is_flag=True, help="Show graph statistics")
def cmd_br_graph(stats=False):
    """Build/update business rule knowledge graph"""
    db_path = find_project_root() / ".roam" / "index.db"
    from roam.business_rules.graph import RuleGraph
    graph = RuleGraph(str(db_path))
    edges = graph.build_edges()

    if stats:
        click.echo(f"Rule graph: {len(edges)} edges")
        by_type = {}
        for _, _, t in edges:
            by_type[t] = by_type.get(t, 0) + 1
        for t, c in sorted(by_type.items()):
            click.echo(f"  {t}: {c}")
    else:
        click.echo(f"✅ Built rule graph with {len(edges)} edges.")
```

---

## M3: 快照 + MCP + preflight 集成（1-2天）

### 3.1 `snapshot.py`

```python
"""规则版本快照 — 支持 diff 比对"""
class RuleSnapshot:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def create(self, label: str = "", commit: str = "") -> int:
        """创建当前规则的快照，返回 snapshot id"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # 获取当前所有规则
            current = {r["rule_id"]: r for r in
                       conn.execute("SELECT rule_id, hash FROM business_rules").fetchall()}
            current_ids = set(current.keys())

            # 获取上次快照
            last = conn.execute(
                "SELECT id, added_rules, removed_rules, modified_rules "
                "FROM business_rule_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()

            if last:
                prev_ids = set(json.loads(last["added_rules"])) | set(
                    json.loads(last.get("modified_rules") or "[]"))
            else:
                prev_ids = set()

            added = list(current_ids - prev_ids)
            removed = list(prev_ids - current_ids)

            # modified: 同 rule_id 但 hash 不同
            modified = []
            for rid in current_ids & prev_ids:
                # 需要上一快照时保存的 hash
                # 简化: 暂不实现深度修改检测
                pass

            conn.execute("""
                INSERT INTO business_rule_snapshots
                (label, git_commit, rule_count, added_rules, removed_rules, modified_rules)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (label, commit, len(current),
                  json.dumps(added), json.dumps(removed), json.dumps(modified)))
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def diff(self, from_id: int, to_id: int) -> dict:
        """对比两个快照"""
        # ...
```

### 3.2 MCP 注册

在 `src/roam/mcp_server.py` 中注册（参考现有工具注册方式）：

```python
from roam.business_rules.commands.cmd_br_extract import cmd_br_extract
from roam.business_rules.commands.cmd_br_check import cmd_br_check
from roam.business_rules.commands.cmd_br_graph import cmd_br_graph

# 在注册处添加（默认放到 core preset）
_business_rules_tools = {
    "business_rules_extract": cmd_br_extract,
    "business_rules_check": cmd_br_check,
    "business_rules_graph": cmd_br_graph,
}
```

### 3.3 preflight 集成

在 `src/roam/commands/cmd_preflight.py` 的 `_CHECKERS` 字典中添加：

```python
from roam.business_rules.conflict import ConflictDetector

def _check_business_rules(db_path: str, target: str):
    conflicts = ConflictDetector(db_path).detect()
    if conflicts:
        return {
            "verdict": "WARN",
            "conflicts": [c.__dict__ for c in conflicts],
        }
    return {"verdict": "PASS"}
```

---

## M4: 增强（持续）

- [ ] `describe.py` — LLM 可选增强：中文描述 + 语义归并
- [ ] 更多 tree-sitter 查询模式 (if-throw, switch, BigDecimal)
- [ ] HTML 可视化报告
- [ ] SVN 快照模式
- [ ] understand-anything skill 标记废弃

---

## 关键决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-07-20 | roam-code 为基座 | Python/SQLite/Apache2.0/preflight/ChangeEvidence |
| 2026-07-20 | 纯 AST，零 LLM | 80%+ 规则注解驱动，LLM 仅为可选增强 |
| 2026-07-20 | 废弃 understand-anything | 能力已吸收到 business-rule-graph |
| 2026-07-20 | SSH 代理隧道 | ProxyCommand nc -X connect -x 127.0.0.1:8888 |

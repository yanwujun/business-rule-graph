# Business Rule Graph — 实施计划

> 项目: https://github.com/yanwujun/business-rule-graph
> 基座: roam-code v13
> 原则: AST 确定性引擎 + LLM 语义引擎，双引擎驱动
> SVN 支持: roam-code 文件 mtime 检测，不依赖 git

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
├── patterns.py          # 提取优先级: 流程节点 > 方法命名 > 注解
├── extractor.py         # AST 核心提取器（确定性）
├── summarizer.py        # LLM 语义引擎（domain/flow/description/归并）
├── commands/
│   ├── __init__.py
│   ├── cmd_br_extract.py
│   ├── cmd_br_summarize.py
│   ├── cmd_br_graph.py
│   ├── cmd_br_check.py
│   └── cmd_br_diff.py
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

### 1.3 `patterns.py` — 提取优先级: 流程/判断节点 > 方法命名 > 注解

> **设计原则：** 政府采购系统（直采商城/框架协议）等业务代码少用 Spring 注解，
> 规则主体在 `if + throw`、状态判断、方法命名约定中。提取优先级：
> **tree-sitter 流程节点 → 方法命名模式 → 注解（兜底）**

```python
from .models import RuleType, Severity

# ============================================================
# 优先级 1: tree-sitter AST 查询 — 流程/判断节点（主力）
# ============================================================
TREE_SITTER_QUERIES = {
    # ——— if + throw 断言：if (条件) throw new XxxException ———
    # 这是政府采购代码中最常见的规则载体
    "if_throw": """
        (if_statement
          condition: (_) @condition
          consequence: (block
            (expression_statement
              (object_creation_expression
                type: (type_identifier) @exception_type
                (#match? @exception_type ".*Exception")
                arguments: (argument_list) @exc_args
              )
            )
          )
        )
    """,

    # ——— if + status 判断：if (x.getStatus() == OrderStatus.DRAFT) ———
    "if_status_check": """
        (if_statement
          condition: (binary_expression
            left: (method_invocation
              name: (identifier) @method_name
              (#match? @method_name "^(get|is).*[Ss]tatus$")
            )
            operator: _ @operator
            right: (_) @status_value
          )
        )
    """,

    # ——— switch + status 分支 ———
    "switch_on_status": """
        (switch_expression
          condition: (identifier) @switch_var
          (#match? @switch_var ".*[Ss]tatus$")
          body: (switch_block
            (switch_block_statement_group)+
          )
        )
    """,

    # ——— enum XxxStatus 定义 ———
    "status_enum": """
        (enum_declaration
          name: (identifier) @enum_name
          (#match? @enum_name ".*[Ss]tatus$")
        ) @enum_node
    """,

    # ——— throw 独立语句（不在 if 里）：throw new BusinessException(...) ———
    "standalone_throw": """
        (expression_statement
          (object_creation_expression
            type: (type_identifier) @exception_type
            (#match? @exception_type ".*Exception")
            arguments: (argument_list) @exc_args
          )
        )
    """,

    # ——— try-catch 业务异常包装 ———
    "try_catch_business": """
        (try_statement
          body: (_)
          catch_clause: (catch_clause
            parameter: (catch_formal_parameter
              type: (type_identifier) @caught_type
              (#match? @caught_type ".*Exception")
            )
          )
        )
    """,
}


def extract_if_condition_text(node, source_bytes: bytes) -> str:
    """从 tree-sitter if_statement 提取条件代码文本"""
    for child in node.children:
        if child.type == "condition":
            if child.type == "parenthesized_expression":
                inner = child.children[1] if len(child.children) > 1 else child
                return inner.text.decode() if hasattr(inner, 'text') else ""
            return source_bytes[child.start_byte:child.end_byte].decode()
    return ""


def extract_exception_message(node, source_bytes: bytes) -> str:
    """从 throw new XxxException(...) 提取异常消息"""
    text = source_bytes[node.start_byte:node.end_byte].decode()
    # 提取第一个字符串参数作为规则描述
    import re
    m = re.search(r'"([^"]*)"', text)
    return m.group(1) if m else text[:80]


def extract_status_value(node, source_bytes: bytes) -> str:
    """提取状态值: OrderStatus.DRAFT → DRAFT"""
    text = source_bytes[node.start_byte:node.end_byte].decode()
    if "." in text:
        return text.split(".")[-1]
    return text


def extract_enum_values(node, source_bytes: bytes) -> list[str]:
    """提取枚举的所有常量名"""
    values = []
    for child in node.children:
        if child.type == "enum_body_declarations":
            for sub in child.children:
                if sub.type == "enum_constant":
                    for c in sub.children:
                        if c.type == "identifier":
                            values.append(source_bytes[c.start_byte:c.end_byte].decode())
                            break
    return values


# ============================================================
# 优先级 2: 方法命名模式 → 规则类型
# ============================================================
METHOD_NAME_PATTERNS = {
    # workflow — 状态流转
    "setStatus":        (RuleType.WORKFLOW, "status_transition"),
    "changeStatus":     (RuleType.WORKFLOW, "status_transition"),
    "updateStatus":     (RuleType.WORKFLOW, "status_transition"),
    "transitionTo":     (RuleType.WORKFLOW, "status_transition"),
    # workflow — 审批链
    "submit":           (RuleType.WORKFLOW, "submit"),
    "approve":          (RuleType.WORKFLOW, "approve"),
    "reject":           (RuleType.WORKFLOW, "reject"),
    "audit":            (RuleType.WORKFLOW, "audit"),
    "review":           (RuleType.WORKFLOW, "review"),
    "publish":          (RuleType.WORKFLOW, "publish"),
    # validation — 自定义校验方法
    "validate":         (RuleType.VALIDATION, "custom_validate"),
    "check":            (RuleType.VALIDATION, "custom_check"),
    "assert":           (RuleType.VALIDATION, "custom_assert"),
    "verify":           (RuleType.VALIDATION, "custom_verify"),
    # data_integrity — 数据库查询
    "existsBy":         (RuleType.DATA_INTEGRITY, "unique_check"),
    "countBy":          (RuleType.DATA_INTEGRITY, "count_check"),
    "selectBy":         (RuleType.DATA_INTEGRITY, "query"),
    "findBy":           (RuleType.DATA_INTEGRITY, "query"),
    # calculation
    "calculate":        (RuleType.CALCULATION, "compute"),
    "compute":          (RuleType.CALCULATION, "compute"),
    "getDiscount":      (RuleType.CALCULATION, "discount"),
    "getTax":           (RuleType.CALCULATION, "tax"),
    "getPrice":         (RuleType.CALCULATION, "price"),
    "getTotal":         (RuleType.CALCULATION, "total"),
    "getAmount":        (RuleType.CALCULATION, "amount"),
    # process — 事件/定时
    "on":               (RuleType.PROCESS, "event_handler"),
    "handle":           (RuleType.PROCESS, "event_handler"),
    "sync":             (RuleType.PROCESS, "sync"),
    "push":             (RuleType.PROCESS, "push"),
}

# ============================================================
# 优先级 3: 注解 → 规则类型（兜底，少数有注解的情况）
# ============================================================
ANNOTATION_RULE_MAP = {
    # validation
    "NotNull":   (RuleType.VALIDATION, "required"),
    "NotBlank":  (RuleType.VALIDATION, "required"),
    "NotEmpty":  (RuleType.VALIDATION, "required"),
    "Min":       (RuleType.VALIDATION, ">="),
    "Max":       (RuleType.VALIDATION, "<="),
    "Valid":     (RuleType.VALIDATION, "cascade"),
    # authorization
    "PreAuthorize":    (RuleType.AUTHORIZATION, "spel"),
    "RolesAllowed":    (RuleType.AUTHORIZATION, "roles"),
    # integration
    "Retryable":       (RuleType.INTEGRATION, "retry"),
    "CircuitBreaker":  (RuleType.INTEGRATION, "circuit_breaker"),
    # configuration
    "Value":           (RuleType.CONFIGURATION, "property"),
    # workflow
    "Transactional":   (RuleType.WORKFLOW, "transactional"),
    "EventListener":   (RuleType.PROCESS, "event"),
}

# ============================================================
# 辅助函数
# ============================================================

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

### 1.4 `extractor.py` — 核心提取器（流程/判断节点优先）

```python
"""纯 AST 业务规则提取器 — 零 LLM 依赖
优先级: if-throw/status判断 → 方法命名 → 注解（兜底）
文件变更检测: roam-code 文件 mtime + hash（支持 SVN）
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from .models import BusinessRule, RuleType
from .patterns import (
    ANNOTATION_RULE_MAP,
    METHOD_NAME_PATTERNS,
    TREE_SITTER_QUERIES,
    domain_from_package,
    flow_from_class,
    extract_if_condition_text,
    extract_exception_message,
    extract_status_value,
    extract_enum_values,
)

logger = logging.getLogger(__name__)

try:
    from tree_sitter import Language, Parser, Query
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


class BusinessRuleExtractor:
    """从 roam-code index 提取业务规则 — 文件时间戳检测，不依赖 git"""

    def __init__(self, db_path: Path | str, project_root: Path | str = "."):
        self.db_path = str(db_path)
        self.project_root = Path(project_root)

    def extract(self, incremental: bool = False) -> list[BusinessRule]:
        """主入口"""
        rules: list[BusinessRule] = []
        seen = set()

        files_to_scan = self._get_files(incremental)

        for file_rel in files_to_scan:
            file_abs = self.project_root / file_rel
            if not file_abs.exists():
                continue
            try:
                source_bytes = file_abs.read_bytes()
            except Exception:
                continue

            file_rules = self._extract_from_source(
                source_bytes, str(file_rel)
            )
            for rule in file_rules:
                h = rule.compute_hash()
                if h not in seen:
                    seen.add(h)
                    rules.append(rule)

        logger.info(f"Extracted {len(rules)} business rules from {len(files_to_scan)} files")
        return rules

    def _get_files(self, incremental: bool) -> list[str]:
        """获取需要扫描的 Java 文件列表（支持 SVN）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if incremental:
                # 基于文件 mtime 检测变更（不依赖 git/svn）
                rows = conn.execute("""
                    SELECT f.path, f.mtime, f.hash
                    FROM files f
                    WHERE f.language = 'java'
                """).fetchall()
                changed = []
                for r in rows:
                    fp = self.project_root / r["path"]
                    if fp.exists():
                        import hashlib
                        new_mtime = fp.stat().st_mtime
                        if new_mtime != r["mtime"]:
                            changed.append(r["path"])
                return changed
            else:
                rows = conn.execute("""
                    SELECT path FROM files WHERE language = 'java'
                """).fetchall()
                return [r["path"] for r in rows]

    def _extract_from_source(self, source: bytes, file_path: str) -> list[BusinessRule]:
        """从 Java 源文件提取业务规则 — 三级优先级"""
        rules = []

        package = Path(file_path).parent.as_posix().replace("/", ".")
        domain = domain_from_package(package)

        # === 优先级 1: tree-sitter 流程/判断节点（主力） ===
        if HAS_TREE_SITTER:
            rules.extend(self._extract_tree_sitter(source, file_path, domain))

        # === 优先级 2: 方法命名模式 ===
        rules.extend(self._extract_method_names(source, file_path, domain))

        # === 优先级 3: 注解（兜底） ===
        rules.extend(self._extract_annotations(source, file_path, domain))

        return rules

    def _extract_tree_sitter(self, source: bytes, file_path: str, domain: str) -> list[BusinessRule]:
        """使用 tree-sitter 扫描 if-throw / status 判断 / enum 等"""
        rules = []
        try:
            import tree_sitter_java as tsjava
            JAVA_LANG = Language(tsjava.language())
            parser = Parser(JAVA_LANG)
            tree = parser.parse(source)
        except Exception:
            return rules

        root = tree.root_node

        # if + throw
        try:
            query = Query(JAVA_LANG, TREE_SITTER_QUERIES["if_throw"])
            captures = query.captures(root)
            for node, _ in captures:
                cond_text = extract_if_condition_text(node, source)
                exc_msg = extract_exception_message(node, source)
                line = node.start_point[0] + 1
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:if-throw",
                    rule_type=RuleType.VALIDATION,
                    domain=domain,
                    description=exc_msg or f"条件断言: {cond_text}",
                    severity="medium",
                    source_file=file_path,
                    source_line=line,
                    source_symbol="",
                    params={
                        "condition": cond_text,
                        "exception_message": exc_msg,
                        "extraction": "tree_sitter_if_throw",
                    },
                ))
        except Exception:
            pass

        # if + status 判断
        try:
            query = Query(JAVA_LANG, TREE_SITTER_QUERIES["if_status_check"])
            captures = query.captures(root)
            for node, _ in captures:
                status_val = extract_status_value(node, source)
                line = node.start_point[0] + 1
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:status-check",
                    rule_type=RuleType.WORKFLOW,
                    domain=domain,
                    description=f"状态判断: {status_val}",
                    source_file=file_path,
                    source_line=line,
                    source_symbol="",
                    params={
                        "status_value": status_val,
                        "extraction": "tree_sitter_status_check",
                    },
                ))
        except Exception:
            pass

        # enum XxxStatus
        try:
            query = Query(JAVA_LANG, TREE_SITTER_QUERIES["status_enum"])
            captures = query.captures(root)
            for node, _ in captures:
                enum_vals = extract_enum_values(node, source)
                line = node.start_point[0] + 1
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:status-enum",
                    rule_type=RuleType.WORKFLOW,
                    domain=domain,
                    description=f"状态枚举: {', '.join(enum_vals)}",
                    source_file=file_path,
                    source_line=line,
                    source_symbol="",
                    params={
                        "enum_values": enum_vals,
                        "extraction": "tree_sitter_status_enum",
                    },
                ))
        except Exception:
            pass

        return rules

    def _extract_method_names(self, source: bytes, file_path: str, domain: str) -> list[BusinessRule]:
        """基于方法命名约定提取"""
        rules = []
        text = source.decode(errors="replace")
        # Java 方法定义: public/private/protected 返回类型 方法名(
        for m in re.finditer(
            r'(?:public|private|protected)\s+\w+\s+(\w+)\s*\(', text
        ):
            name = m.group(1)
            for pattern, (rt, sub_type) in METHOD_NAME_PATTERNS.items():
                if re.match(f"^{pattern}", name):
                    line = text[:m.start()].count('\n') + 1
                    rules.append(BusinessRule(
                        rule_id=f"{name}.{pattern}",
                        rule_type=rt,
                        domain=domain,
                        flow=flow_from_class(name),
                        description=f"{sub_type}: {name}",
                        source_file=file_path,
                        source_line=line,
                        source_symbol=name,
                        params={"method": name, "sub_type": sub_type,
                                "extraction": "method_name"},
                    ))
                    break
        return rules

    def _extract_annotations(self, source: bytes, file_path: str, domain: str) -> list[BusinessRule]:
        """注解提取（兜底）"""
        rules = []
        text = source.decode(errors="replace")
        for m in re.finditer(r'@(\w+)(?:\(([^)]*)\))?', text):
            name = m.group(1)
            args = m.group(2)
            if name in ANNOTATION_RULE_MAP:
                rt, op = ANNOTATION_RULE_MAP[name]
                line = text[:m.start()].count('\n') + 1
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:@{name}",
                    rule_type=rt,
                    domain=domain,
                    description=f"@{name}: {args or op}",
                    source_file=file_path,
                    source_line=line,
                    source_symbol="",
                    params={"operator": op, "args": args or "",
                            "extraction": "annotation"},
                    annotations=[f"@{name}" + (f"({args})" if args else "")],
                ))
        return rules
```

### 1.4.1 SVN / 无 VCS 支持说明

roam-code 的文件变更检测不依赖 git：

```
roam init               → 全量扫描，记录每个文件的 mtime + hash
roam extract --update   → 比较当前文件 mtime 与 index 中记录，只处理变更文件
roam snapshot --label   → 快照用自定义标签，不绑定 git commit
```

SVN 项目直接可用。唯一差距是快照的 `git_commit` 字段为空 — 用 `label` 字段替代。

### 1.4.2 `summarizer.py` — LLM 语义引擎（内置，非可选）

> AST 拿到的是代码事实（`if(total<100) throw`），变不成业务语言（"订单金额不低于100元"）。
> `summarizer` 在 AST 提取之后，调用一次 LLM 做批量语义化。

```python
"""LLM 语义引擎 — 给 AST 规则补充业务含义
职责:
  ✅ domain 语义校准（不靠包名猜）
  ✅ flow 语义校准（不靠类名猜）
  ✅ description 自然语言生成
  ✅ 语义归并（同规则不同写法 → 合并）
  ✅ 冲突描述生成（不只是"阈值不一致"，而是业务含义）
❌ 不提取参数 — 参数由 AST 确定
"""
from __future__ import annotations

import json
import os
from typing import Optional


SYSTEM_PROMPT = """你是政府采购系统的业务分析师。你会收到一批从 Java 代码中自动提取的业务规则。
你的任务是对每条规则补充业务含义。

输入格式: JSON 数组，每条规则包含:
- rule_id: 规则唯一标识
- source_file/source_line: 代码位置
- condition: AST 提取的条件代码文本
- exception_message: 异常消息（如有）
- status_value: 状态值（如有）
- enum_values: 枚举值列表（如有）
- extraction: 提取方式 (tree_sitter_if_throw / tree_sitter_status_check / tree_sitter_status_enum / method_name / annotation)

输出要求: 对每条规则输出:
- domain: 业务域（订单管理/供应商管理/商品管理/支付管理/审核管理/合同管理/系统管理）
- flow: 业务流程（下单/支付/审核/发货/签约/退款/同步）
- description: 自然语言描述（30字以内）
- severity: critical/high/medium/low
- merge_with: 如果与其他规则是同一规则的不同写法，填写被合并的 rule_id

关键:
- description 必须用业务语言，不要复制代码
- domain 根据业务含义分类，不要依赖包名
- 发现 if(total>=100) 和 if(amount<100则抛异常) 应标记为同一规则（merge_with）
- 不要修改 rule_id / source_file / source_line
"""


class RuleSummarizer:
    """批量 LLM 语义化 — 一次调用处理所有规则"""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def summarize(self, rules: list[dict], batch_size: int = 50) -> list[dict]:
        """批量语义化，每批最多 50 条（控制 token）"""
        if not self.api_key:
            # 无 API key 时降级为模板生成
            return self._template_fallback(rules)

        all_results = []
        for i in range(0, len(rules), batch_size):
            batch = rules[i:i+batch_size]
            result = self._call_llm(batch)
            all_results.extend(result)
        return all_results

    def _call_llm(self, rules: list[dict]) -> list[dict]:
        """调用 LLM API"""
        import requests

        rules_json = json.dumps(rules, ensure_ascii=False, indent=2)

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.environ.get("LLM_MODEL", "gpt-4.1-mini"),
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"请分析以下业务规则并补充语义信息:\n{rules_json}"},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )

        if resp.status_code != 200:
            return self._template_fallback(rules)

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content).get("rules", [])
        except json.JSONDecodeError:
            return self._template_fallback(rules)

    def _template_fallback(self, rules: list[dict]) -> list[dict]:
        """无 LLM 时的模板降级方案"""
        for r in rules:
            r["domain"] = r.get("domain", "未分类")
            r["flow"] = r.get("flow", "")
            exc_msg = r.get("exception_message", "")
            cond = r.get("condition", "")
            status = r.get("status_value", "")
            if exc_msg:
                r["description"] = exc_msg
            elif status:
                r["description"] = f"状态必须为: {status}"
            elif cond:
                r["description"] = f"条件校验: {cond}"
            else:
                r["description"] = r.get("description", "")
            r["severity"] = r.get("severity", "medium")
            r["merge_with"] = None
        return rules
```

### 1.4.3 双引擎工作流程图

```
roam business-rules extract
        │
        ▼
    extractor.py (AST 确定性引擎)
        │
        ├── tree-sitter 扫 if-throw
        ├── 方法名正则匹配
        └── 注解兜底
        │
        ▼  产出: [{"rule_id":"...","condition":"total<100","exception_message":"金额不能低于100元"},...]
        │         参数精确，描述机械，domain 靠包名猜
        │
        ▼
roam business-rules summarize      ← 可选但推荐
        │
        ▼
    summarizer.py (LLM 语义引擎)
        │
        ├── domain: "订单管理" (不靠包名)
        ├── flow: "用户下单校验"
        ├── description: "订单金额不得低于100元"
        ├── 语义归并: total>=100 和 amount<100→抛异常 → 合并为一条
        └── 冲突描述: "下单校验50元但支付仍要求100元"
        │
        ▼  产出: 规则图谱 → conflict.py → 冲突报告
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

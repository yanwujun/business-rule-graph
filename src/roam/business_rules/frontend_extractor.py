"""前端业务规则提取器 — React + TypeScript + Ant Design

基于正则匹配，无需 tree-sitter。
提取模式:
  1. antd Form.Item rules: [{ required: true, message: '...' }]
  2. 数值约束: max/min/pattern
  3. TypeScript 状态枚举: enum XxxStatus { ... }
  4. 自定义 validator: rules: [{ validator: validateXxx }]
"""

from __future__ import annotations

import re
import logging
from pathlib import Path

from .models import BusinessRule, RuleType

logger = logging.getLogger(__name__)

# ---- 正则模式 ----

# rules: [{ required: true, message: '请选择重算时间段' }]
_RE_RULE_REQUIRED = re.compile(
    r"rules:\s*\[[^\]]*\{\s*required:\s*true[^}]*message:\s*['\"]([^'\"]+)['\"]",
    re.DOTALL,
)

# rules: [{ max: 200, message: '最多输入200个字符' }]
_RE_RULE_MAX = re.compile(
    r"rules:\s*\[[^\]]*\{\s*max:\s*(\d+)[^}]*message:\s*['\"]([^'\"]+)['\"]",
    re.DOTALL,
)

# rules: [{ min: N, message: '...' }]
_RE_RULE_MIN = re.compile(
    r"rules:\s*\[[^\]]*\{\s*min:\s*(\d+)[^}]*message:\s*['\"]([^'\"]+)['\"]",
    re.DOTALL,
)

# rules: [{ pattern: /.../, message: '...' }]
_RE_RULE_PATTERN = re.compile(
    r"rules:\s*\[[^\]]*\{\s*pattern:\s*(/\^?[^/]+/)[^}]*message:\s*['\"]([^'\"]+)['\"]",
    re.DOTALL,
)

# rules: [{ validator: validateXxx }]
_RE_RULE_VALIDATOR = re.compile(
    r"rules:\s*\[[^\]]*\{\s*validator:\s*(\w+)",
    re.DOTALL,
)

# enum XxxStatus { DRAFT = '草稿', SUBMITTED = '已提交', ... }
_RE_ENUM_STATUS = re.compile(
    r"enum\s+(\w*Status\w*)\s*\{([^}]+)\}",
    re.DOTALL,
)

# ---- domain 推断 ----

_DOMAIN_FROM_PATH = {
    "order": "订单管理", "bid": "招标管理", "contract": "合同管理",
    "goods": "商品管理", "supplier": "供应商管理", "payment": "支付管理",
    "fee": "费用管理", "plan": "计划管理", "stock": "库存管理",
    "settled": "入驻管理", "entrust": "委托管理", "trading": "交易管理",
    "notice": "公告管理", "collect": "征集管理", "protocol": "协议管理",
    "dispute": "争议管理", "account": "账户管理", "purchase": "采购管理",
}


class FrontendExtractor:
    """从 React/TypeScript 前端文件提取业务规则"""

    def __init__(self, project_root: Path | str = "."):
        self.project_root = Path(project_root)

    def extract_from_db(
        self, db_path: str, incremental: bool = False
    ) -> list[BusinessRule]:
        import sqlite3

        rules: list[BusinessRule] = []
        seen = set()

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT path FROM files WHERE language IN ('typescript', 'tsx')"
            ).fetchall()

        files = [r["path"] for r in rows]
        total = len(files)
        logger.info("Scanning %d frontend files for business rules", total)

        for i, rel_path in enumerate(files):
            if total > 10 and i % max(1, total // 10) == 0:
                logger.info("Frontend extract... %d/%d", i + 1, total)

            abs_path = self.project_root / rel_path
            if not abs_path.exists():
                continue
            try:
                source = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            file_rules = self.extract_from_source(source, str(rel_path))
            for r in file_rules:
                h = r.compute_hash()
                if h not in seen:
                    seen.add(h)
                    rules.append(r)

        logger.info("Extracted %d frontend business rules from %d files", len(rules), total)
        return rules

    def extract_from_source(self, source: str, file_path: str) -> list[BusinessRule]:
        rules: list[BusinessRule] = []

        path_lower = file_path.lower()
        domain = "系统管理"
        for key, name in _DOMAIN_FROM_PATH.items():
            if key in path_lower:
                domain = name
                break

        # required rules
        for m in _RE_RULE_REQUIRED.finditer(source):
            msg = m.group(1)
            line = source[: m.start()].count("\n") + 1
            rules.append(BusinessRule(
                rule_id=f"{file_path}:{line}:form-required",
                rule_type=RuleType.VALIDATION,
                domain=domain,
                description=msg,
                source_file=file_path, source_line=line,
                params={"required": True, "message": msg, "extraction": "frontend_form"},
                extraction="frontend_form",
            ))

        # max constraints
        for m in _RE_RULE_MAX.finditer(source):
            val, msg = m.group(1), m.group(2)
            line = source[: m.start()].count("\n") + 1
            rules.append(BusinessRule(
                rule_id=f"{file_path}:{line}:form-max",
                rule_type=RuleType.VALIDATION,
                domain=domain, description=msg,
                source_file=file_path, source_line=line,
                params={"max": int(val), "message": msg, "extraction": "frontend_form"},
                extraction="frontend_form",
            ))

        # min constraints
        for m in _RE_RULE_MIN.finditer(source):
            val, msg = m.group(1), m.group(2)
            line = source[: m.start()].count("\n") + 1
            rules.append(BusinessRule(
                rule_id=f"{file_path}:{line}:form-min",
                rule_type=RuleType.VALIDATION,
                domain=domain, description=msg,
                source_file=file_path, source_line=line,
                params={"min": int(val), "message": msg, "extraction": "frontend_form"},
                extraction="frontend_form",
            ))

        # custom validators
        for m in _RE_RULE_VALIDATOR.finditer(source):
            name = m.group(1)
            line = source[: m.start()].count("\n") + 1
            rules.append(BusinessRule(
                rule_id=f"{file_path}:{line}:validator-{name}",
                rule_type=RuleType.VALIDATION,
                domain=domain,
                description=f"自定义校验: {name}",
                source_file=file_path, source_line=line,
                params={"validator": name, "extraction": "frontend_validator"},
                extraction="frontend_validator",
            ))

        # status enums
        for m in _RE_ENUM_STATUS.finditer(source):
            name = m.group(1)
            body = m.group(2)
            line = source[: m.start()].count("\n") + 1
            values = re.findall(r"(\w+)\s*[=}]", body)
            rules.append(BusinessRule(
                rule_id=f"{file_path}:{line}:enum-{name}",
                rule_type=RuleType.WORKFLOW,
                domain=domain,
                description=f"状态枚举: {name} = [{', '.join(values[:6])}{'...' if len(values) > 6 else ''}]",
                source_file=file_path, source_line=line,
                params={"enum_name": name, "enum_values": values, "extraction": "frontend_enum"},
                extraction="frontend_enum",
            ))

        return rules

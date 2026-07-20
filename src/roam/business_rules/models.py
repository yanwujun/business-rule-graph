"""Business Rule Graph — 数据模型定义

吸收自 diff-to-business-rules 的 8 种规则类型分类。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RuleType(str, Enum):
    """8 种业务规则类型"""
    VALIDATION = "validation"           # 校验规则: if-throw, @NotNull, @Min
    AUTHORIZATION = "authorization"     # 权限规则: @PreAuthorize, @RolesAllowed
    WORKFLOW = "workflow"               # 状态流转: enum Status, setStatus()
    CALCULATION = "calculation"         # 业务计算: BigDecimal运算, 折扣/税费
    DATA_INTEGRITY = "data_integrity"   # 数据完整性: existsBy, unique约束
    PROCESS = "process"                 # 流程控制: @EventListener, 审批链
    CONFIGURATION = "configuration"     # 配置规则: @Value, feature flag
    INTEGRATION = "integration"         # 集成规则: @Retryable, @CircuitBreaker


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class BusinessRule:
    """一条业务规则"""
    rule_id: str = ""                    # "OrderService.java:145:if-throw"
    rule_type: RuleType = RuleType.VALIDATION
    domain: str = ""                     # LLM 语义分类或包名推断
    flow: str = ""                       # LLM 语义分类或类名推断
    description: str = ""                # 自然语言描述
    severity: Severity = Severity.MEDIUM
    source_file: str = ""
    source_line: int = 0
    source_symbol: str = ""              # 方法名/类名
    params: dict = field(default_factory=dict)
    annotations: list = field(default_factory=list)
    symbols: list = field(default_factory=list)
    # LLM 语义化字段
    merge_with: Optional[str] = None     # 被合并到的 rule_id（语义归并）
    extraction: str = ""                 # 提取方式标记

    def compute_hash(self) -> str:
        """SHA256 of (source_file|source_line|params) — 用于去重和 diff"""
        import hashlib
        import json
        payload = f"{self.source_file}|{self.source_line}|{json.dumps(self.params, sort_keys=True)}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.value,
            "domain": self.domain,
            "flow": self.flow,
            "description": self.description,
            "severity": self.severity.value,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "source_symbol": self.source_symbol,
            "params": self.params,
            "annotations": self.annotations,
            "extraction": self.extraction,
            "merge_with": self.merge_with,
            "hash": self.compute_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> BusinessRule:
        return cls(
            rule_id=d.get("rule_id", ""),
            rule_type=RuleType(d.get("rule_type", "validation")),
            domain=d.get("domain", ""),
            flow=d.get("flow", ""),
            description=d.get("description", ""),
            severity=Severity(d.get("severity", "medium")),
            source_file=d.get("source_file", ""),
            source_line=d.get("source_line", 0),
            source_symbol=d.get("source_symbol", ""),
            params=d.get("params", {}),
            annotations=d.get("annotations", []),
            extraction=d.get("extraction", ""),
            merge_with=d.get("merge_with"),
        )

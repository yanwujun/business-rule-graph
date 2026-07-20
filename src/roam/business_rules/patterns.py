"""业务规则匹配模式 — 三级优先级

优先级:
  1. tree-sitter AST 流程/判断节点（主力 — if-throw, status判断, enum）
  2. 方法命名约定
  3. 注解（兜底，少量使用）

设计假设: 政府采购系统代码少用 Spring 注解，规则在 if+throw 和状态判断中。
"""
from __future__ import annotations

from .models import RuleType


# ============================================================
# 优先级 1: tree-sitter AST 查询 — 流程/判断节点（主力）
# ============================================================

TREE_SITTER_QUERIES = {
    # if (条件) throw new XxxException(...)
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

    # if (x.getStatus() == OrderStatus.DRAFT) 或 if (x.isApproved())
    "if_status_check": """
        (if_statement
          condition: (binary_expression
            left: (method_invocation
              name: (identifier) @method_name
              (#match? @method_name "^(get|is).*[Ss]tatus$|^is.*")
            )
            operator: _ @operator
            right: (_) @status_value
          )
        )
    """,

    # switch (status) { case ... }
    "switch_on_status": """
        (switch_expression
          condition: (identifier) @switch_var
          (#match? @switch_var ".*[Ss]tatus$")
          body: (switch_block
            (switch_block_statement_group)+
          )
        )
    """,

    # enum XxxStatus { DRAFT, SUBMITTED, ... }
    "status_enum": """
        (enum_declaration
          name: (identifier) @enum_name
          (#match? @enum_name ".*[Ss]tatus$")
        ) @enum_node
    """,

    # throw new XxxException(...) — 不在 if 里的独立 throw
    "standalone_throw": """
        (expression_statement
          (object_creation_expression
            type: (type_identifier) @exception_type
            (#match? @exception_type ".*Exception")
            arguments: (argument_list) @exc_args
          )
        )
    """,

    # try { ... } catch (XxxException e) { ... }
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


# ============================================================
# 优先级 2: 方法命名约定 → 规则类型
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
    "cancel":           (RuleType.WORKFLOW, "cancel"),
    # validation
    "validate":         (RuleType.VALIDATION, "custom_validate"),
    "check":            (RuleType.VALIDATION, "custom_check"),
    "assert":           (RuleType.VALIDATION, "custom_assert"),
    "verify":           (RuleType.VALIDATION, "custom_verify"),
    # data_integrity
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
    # process — 事件/定时/同步
    "on":               (RuleType.PROCESS, "event_handler"),
    "handle":           (RuleType.PROCESS, "event_handler"),
    "sync":             (RuleType.PROCESS, "sync"),
    "push":             (RuleType.PROCESS, "push"),
}


# ============================================================
# 优先级 3: 注解 → 规则类型（兜底）
# ============================================================

ANNOTATION_RULE_MAP = {
    "NotNull":   (RuleType.VALIDATION, "required"),
    "NotBlank":  (RuleType.VALIDATION, "required"),
    "NotEmpty":  (RuleType.VALIDATION, "required"),
    "Min":       (RuleType.VALIDATION, ">="),
    "Max":       (RuleType.VALIDATION, "<="),
    "Valid":     (RuleType.VALIDATION, "cascade"),
    "PreAuthorize":    (RuleType.AUTHORIZATION, "spel"),
    "RolesAllowed":    (RuleType.AUTHORIZATION, "roles"),
    "Retryable":       (RuleType.INTEGRATION, "retry"),
    "CircuitBreaker":  (RuleType.INTEGRATION, "circuit_breaker"),
    "Value":           (RuleType.CONFIGURATION, "property"),
    "Transactional":   (RuleType.WORKFLOW, "transactional"),
    "EventListener":   (RuleType.PROCESS, "event"),
}


# ============================================================
# 辅助函数
# ============================================================

def domain_from_package(package: str) -> str:
    """从 Java 包名推断业务域（LLM 语义化之前的兜底方案）"""
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
    """从类名推断业务流程（LLM 语义化之前的兜底方案）"""
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


def extract_exception_message(source_bytes: bytes, node_start: int, node_end: int) -> str:
    """从 throw new XxxException("消息") 提取中文消息"""
    import re
    text = source_bytes[node_start:node_end].decode(errors="replace")
    m = re.search(r'"([^"]*)"', text)
    return m.group(1) if m else ""


def extract_status_value(source_bytes: bytes, node_start: int, node_end: int) -> str:
    """提取状态值: OrderStatus.DRAFT → DRAFT"""
    text = source_bytes[node_start:node_end].decode(errors="replace")
    if "." in text:
        return text.split(".")[-1]
    return text


def extract_enum_values(node, source_bytes: bytes) -> list[str]:
    """提取 enum 的所有常量名"""
    values = []
    for child in node.children:
        if child.type == "enum_body_declarations":
            for sub in child.children:
                if sub.type == "enum_constant":
                    for c in sub.children:
                        if c.type == "identifier":
                            values.append(
                                source_bytes[c.start_byte:c.end_byte].decode()
                            )
                            break
    return values

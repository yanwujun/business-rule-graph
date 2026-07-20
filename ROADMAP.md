---
name: business-rule-graph
description: 基于 roam-code 改造 — 从 Java/Spring Boot 代码中提取业务规则，构建规则知识图谱，代码变更后自动检测业务冲突。纯 AST 驱动，零 LLM 依赖（LLM 为可选增强层）。
---

# Business Rule Graph — 改造方案

## 项目定位

基于 [roam-code](https://github.com/Cranot/roam-code) 改造，吸收 understand-anything 中业务规则相关能力，专注解决：

> **AI 修改代码后，自动判断是否引入了业务规则冲突。纯 AST，零 LLM。**

## understand-anything → 本项目 吸收映射

| understand-anything 能力 | 吸收方式 | 说明 |
|---|---|---|
| `diff-to-business-rules` 的 8 种规则分类 | → `business_rules/patterns.py` | 直接用，架构不依赖 LLM |
| `diff-to-business-rules` 的规则提取逻辑 | → `business_rules/extractor.py` | 改为纯 AST，不依赖 diff |
| `understand-domain` 的域/流程概念 | → `business_rules/models.py` 的 domain/flow 字段 | 从包名/类名推断 |
| `understand` 的 knowledge-graph.json | → **废弃**。roam-code SQLite 替代 | 更精确、可增量 |
| LLM 提取 pipeline | → **降级为可选增强层** | AST 覆盖 80%+ |

**understand-anything 相关 skill 后续标记为 deprecated。**

## roam-code 已有的能力（直接复用）

| 能力 | 模块 | 说明 |
|------|------|------|
| 多语言 AST 解析 | `src/roam/languages/` | 含 Java tree-sitter，已有注解/修饰符/方法签名提取 |
| SQLite 图存储 | `src/roam/db/` | files + symbols + edges 三张核心表，可扩展 |
| 代码索引 | `src/roam/index/` | 增量索引、文件变更检测 |
| 变更追踪 | `src/roam/evidence/` | ChangeEvidence 包、preflight 风险评估 |
| Git 集成 | `src/roam/git_utils.py` | 变更文件列表、commit 历史 |
| MCP Server | `src/roam/mcp_server.py` | 244 个 MCP 工具，可直接注册新工具 |
| CLI 框架 | `src/roam/cli.py` | Click-based，新增命令只需加模块 |
| 图算法 | `src/roam/graph/` | 路径查找、社区检测、影响传播 |

## 改造架构

```
roam-code (现有)
├── src/roam/
│   ├── languages/java_lang.py    ← 已有，扩展规则提取
│   ├── db/schema.py               ← 已有，新增 4 张表
│   ├── index/                     ← 已有，复用索引管线
│   ├── evidence/                  ← 已有，复用变更追踪
│   │
│   └── business_rules/           ← 🆕 新增模块（纯 AST，零 LLM）
│       ├── __init__.py
│       ├── models.py              # 数据模型 + 8 种规则类型定义
│       ├── patterns.py            # AST 匹配模式（吸收 diff-to-business-rules）
│       ├── extractor.py           # 规则提取器（纯 tree-sitter AST）
│       ├── graph.py               # 规则图谱（规则→代码溯源 + 规则→规则关系）
│       ├── conflict.py            # 冲突检测引擎（纯计算，零 LLM）
│       ├── snapshot.py            # 规则版本快照 + diff
│       ├── describe.py            # [可选] LLM 增强：中文描述 + 域分类
│       └── commands/              # CLI 命令
│           ├── cmd_br_extract.py
│           ├── cmd_br_graph.py
│           ├── cmd_br_check.py
│           └── cmd_br_diff.py
```

---

## 核心原则：纯 AST，零 LLM

### AST 直接提取 vs 需要 LLM

| 规则信息 | AST 能做到 | 来源 |
|----------|-----------|------|
| rule_id | ✅ 自动生成: `{file}-{method}-{annotation}` | 文件路径 + 符号名 + 注解名 |
| rule_type | ✅ 注解名映射: `@Min` → validation, `@PreAuthorize` → authorization | patterns.py 映射表 |
| source_file | ✅ 文件路径 | tree-sitter file_path |
| source_line | ✅ 行号 | tree-sitter node.start_point |
| source_symbol | ✅ 方法名/类名 | JavaExtractor.extract_symbols() |
| field (约束的字段) | ✅ 从注解所在位置推断 | tree-sitter AST 父子节点 |
| operator | ✅ `@Min` → ≥, `@Max` → ≤, `@NotNull` → required | 硬编码映射 |
| threshold | ✅ `@Min(100)` → 100 | 注解参数 |
| annotations | ✅ 完整列表 | modifiers → annotations |
| domain (业务域) | ⚠️ 从包名推断: `order` → 订单管理 | 推测，可能不准 |
| flow (业务流程) | ⚠️ 从类名推断: `OrderService` → 下单流程 | 推测，可能不准 |
| description (中文描述) | ⚠️ 模板生成: "`{field}` 必须 ≥ `{threshold}`" | 机械化，不自然 |
| 语义归并 | ❌ | 多处表达同一规则时需要 LLM |

**结论：核心链路（提取→图谱→冲突检测）100% AST 可完成。domain/flow/description 用模板兜底，LLM 仅在需要高质量中文输出时可选启用。**

---

## Phase 1: 业务规则提取器（纯 AST）

### 1.1 数据模型 (`models.py`)

```python
class RuleType(Enum):
    """8 种规则类型 — 吸收自 diff-to-business-rules"""
    VALIDATION = "validation"         # @NotNull, @Min, @Max, if-throw
    AUTHORIZATION = "authorization"   # @PreAuthorize, @RolesAllowed
    WORKFLOW = "workflow"             # enum Status, setStatus(), @Transactional
    CALCULATION = "calculation"       # BigDecimal 运算, 折扣/税费
    DATA_INTEGRITY = "data_integrity" # @Column(unique=true), existsBy
    PROCESS = "process"               # @EventListener, 审批链
    CONFIGURATION = "configuration"   # @Value, @ConfigurationProperties
    INTEGRATION = "integration"       # @Retryable, @CircuitBreaker

@dataclass
class BusinessRule:
    rule_id: str          # "OrderService.validateOrder.@Min.total"
    rule_type: RuleType
    domain: str           # 从包名推断: "订单管理"
    flow: str             # 从类名推断: "用户下单"
    description: str      # 模板生成: "total 字段必须 >= 100"
    severity: str         # 注解推断: @Min→medium, @PreAuthorize→high
    source_file: str
    source_line: int
    source_symbol: str
    params: dict          # {"field":"total","operator":">=","threshold":100}
    annotations: list     # ["@Min(100)"]
    related_symbols: list # AST 提取的关联符号
```

### 1.2 注解→规则映射表 (`patterns.py`)

```python
# 吸收自 diff-to-business-rules 的 8 种模式定义
ANNOTATION_RULE_MAP = {
    # validation
    "NotNull":  (RuleType.VALIDATION, "required", None),
    "NotBlank": (RuleType.VALIDATION, "required", None),
    "NotEmpty": (RuleType.VALIDATION, "required", None),
    "Min":      (RuleType.VALIDATION, ">=", "value"),
    "Max":      (RuleType.VALIDATION, "<=", "value"),
    "Size":     (RuleType.VALIDATION, "size", ["min","max"]),
    "Pattern":  (RuleType.VALIDATION, "regexp", "regexp"),
    "Email":    (RuleType.VALIDATION, "email", None),
    "Valid":    (RuleType.VALIDATION, "cascade", None),

    # authorization
    "PreAuthorize":   (RuleType.AUTHORIZATION, "has_role", "value"),
    "RolesAllowed":   (RuleType.AUTHORIZATION, "roles", "value"),
    "Secured":        (RuleType.AUTHORIZATION, "secured", "value"),

    # data_integrity
    "Column":         (RuleType.DATA_INTEGRITY, "column", None),  # 需解析 unique/nullable

    # integration
    "Retryable":      (RuleType.INTEGRATION, "retry", None),
    "CircuitBreaker": (RuleType.INTEGRATION, "circuit_breaker", None),

    # configuration
    "Value":          (RuleType.CONFIGURATION, "property", "value"),

    # workflow
    "Transactional":  (RuleType.WORKFLOW, "transactional", None),
}
```

### 1.3 提取流程 (`extractor.py`)

```
输入: roam-code index 后的 .roam/index.db
输出: business_rules 表 + business_rule_code_edges 表

流程:
1. 遍历 symbols 表中 kind IN ('method','class) 的行
2. 按 file_id 加载 AST 树（通过 tree-sitter 重新解析源文件）
3. 对每个 symbol:
   a. 遍历 modifiers → annotations → 匹配 ANNOTATION_RULE_MAP
   b. 遍历方法体 if-throw → 匹配 BusinessException 模式
   c. 扫描方法签名 → 匹配 existsBy*/findBy* 模式
   d. 扫描类定义 → 匹配 enum *Status 模式
4. 生成 BusinessRule 对象 → 写入 business_rules 表
5. 生成 business_rule_code_edges → 关联到 symbols 表
```

---

## Phase 2: 业务规则图谱

### 2.1 新增 DB 表 (`db/schema.py` 扩展)

```sql
-- 业务规则主表
CREATE TABLE IF NOT EXISTS business_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL UNIQUE,
    rule_type TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    flow TEXT DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    severity TEXT DEFAULT 'medium',
    source_file TEXT NOT NULL,
    source_line INTEGER,
    source_symbol TEXT,
    params JSON,
    annotations JSON,
    hash TEXT,                 -- params + source 的 SHA256，用于 diff
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 规则↔代码符号关联
CREATE TABLE IF NOT EXISTS business_rule_code_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER REFERENCES business_rules(id),
    symbol_id INTEGER REFERENCES symbols(id),
    edge_type TEXT NOT NULL   -- implemented_by / constrains / references
);

-- 规则↔规则关联（纯计算得出）
CREATE TABLE IF NOT EXISTS business_rule_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_rule_id INTEGER REFERENCES business_rules(id),
    target_rule_id INTEGER REFERENCES business_rules(id),
    edge_type TEXT NOT NULL,  -- same_field / same_flow / conflicts_with / depends_on
    confidence REAL DEFAULT 1.0
);

-- 规则快照（用于 diff）
CREATE TABLE IF NOT EXISTS business_rule_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,               -- 可选标签: "基线 v1", "PR #42 合并后"
    snapshot_at TEXT DEFAULT (datetime('now')),
    rule_count INTEGER,
    added_rules JSON,         -- [rule_id, ...]
    removed_rules JSON,
    modified_rules JSON
);
```

### 2.2 图谱构建 (`graph.py`)

```
Layer 1 — 规则→代码溯源（自动生成）
    business_rule:OrderService.validateOrder.@Min.total
        ├── [implemented_by] → symbol:OrderService.validateOrder
        ├── [constrains]     → symbol:Order.total
        └── [in_file]        → file:OrderService.java

Layer 2 — 规则→规则关系（纯计算，零 LLM）
    触发条件:
    - same_field: params["field"] 相同 → 自动建边
    - same_flow: flow 字段相同 → 自动建边
    - conflicts_with: 同 field + 不同 threshold → 自动标记
```

---

## Phase 3: 冲突检测引擎（纯计算）

### 3.1 检测算法 (`conflict.py`)

| # | 检测类型 | 算法 | 严重度 |
|---|---------|------|--------|
| 1 | **同字段阈值冲突** | 按 params.field 分组 → 比较 operator+threshold → 不一致则报 | CRITICAL |
| 2 | **状态机断裂** | 提取所有 WORKFLOW 规则 → 构建状态转移图 → 检测死端 | CRITICAL |
| 3 | **权限移除** | 当前快照 vs 上一快照 → AUTHORIZATION 规则减少 → 报警 | HIGH |
| 4 | **计算不一致** | 按 params.formula 分组 → 比较 CALCULATION 规则参数 | HIGH |
| 5 | **配置漂移** | 按 params.property 分组 → 比较 CONFIGURATION 规则 default | MEDIUM |
| 6 | **唯一性重叠** | 按 params.field 分组 → 多个 existsBy 覆盖相同字段 | MEDIUM |

### 3.2 检测流程

```
1. 加载当前 business_rules + 上一次 business_rule_snapshots
2. diff: 找出 added / removed / modified 规则
3. 对每条 modified 规则:
   a. 按 rule_type 找同类型规则
   b. 按 params.field 找同字段规则
   c. 比较阈值 → 不一致则记录冲突
4. 对每条 removed 规则:
   a. 如果是 AUTHORIZATION 类型 → 权限泄露警告
   b. 如果是 WORKFLOW 类型 → 检查上下游是否有规则引用它
5. 生成冲突报告 JSON
```

---

## Phase 4: CLI 和 MCP 命令

### 4.1 CLI 命令

```bash
# 规则提取（纯 AST，零 API 调用）
roam business-rules extract              # 全量提取
roam business-rules extract --update     # 增量提取（仅变更文件）

# 图谱操作
roam business-rules graph                # 构建/重建规则图谱
roam business-rules graph --stats        # 统计概览
roam business-rules explain <rule-id>    # 解释单条规则
roam business-rules related <rule-id>    # 查看关联规则

# 冲突检测（纯计算）
roam business-rules check                # 全面检测
roam business-rules check --domain 订单管理
roam business-rules check --preflight    # 集成到 preflight

# 快照管理
roam business-rules snapshot             # 创建快照
roam business-rules diff                 # 对比最新两个快照
roam business-rules diff --from <label> --to <label>
```

### 4.2 MCP 工具

```python
# 注册到 mcp_server.py core preset:
"business_rules_extract": cmd_br_extract.extract,
"business_rules_check":   cmd_br_check.check,
"business_rules_graph":   cmd_br_graph.graph,
"business_rules_diff":    cmd_br_diff.diff,
```

---

## 实施路线图

### Milestone 1: 规则提取（MVP，零 LLM）

- [x] Fork → business-rule-graph 仓库
- [ ] 新增 `src/roam/business_rules/` 模块骨架
- [ ] 实现 `patterns.py` — ANNOTATION_RULE_MAP + 枚举/if-throw 模式
- [ ] 实现 `extractor.py` — 纯 AST 提取，从 index.db 读取 symbols
- [ ] 新增 DB schema（business_rules + business_rule_code_edges）
- [ ] 实现 `cmd_br_extract.py` — roam business-rules extract
- [ ] 在 P2040 项目上跑通

### Milestone 2: 图谱 + 冲突

- [ ] 实现 `graph.py` — 规则图谱构建（same_field/same_flow 自动建边）
- [ ] 实现 `conflict.py` — 3 种核心检测（阈值冲突/权限移除/状态机断裂）
- [ ] 新增 business_rule_edges 表
- [ ] 实现 `cmd_br_check.py` + `cmd_br_graph.py`

### Milestone 3: 快照 + MCP + 集成

- [ ] 实现 `snapshot.py` — 快照 + diff
- [ ] MCP 工具注册
- [ ] 集成到 roam preflight（代码变更自动触发）
- [ ] understand-anything skill 标记废弃

### Milestone 4: 可选增强

- [ ] `describe.py` — LLM 可选增强：中文描述 + 域分类
- [ ] 支持更多 Java 模式（MyBatis、Redis 锁等）
- [ ] HTML 可视化报告
- [ ] SVN 快照模式支持

---

## 风险与边界

| 风险 | 缓解 |
|------|------|
| AST 提取的 domain 不准确 | 默认从包名推断 + 可选 LLM 修正 |
| SVN 项目无 git history | snapshot 用时间戳 + 自定义 label |
| roam-code 上游更新 | 改动集中在 business_rules/ 模块，定期 rebase |
| 语义归并（同规则不同写法） | 用 hash(params + field) 做去重，LLM 归并为可选增强 |

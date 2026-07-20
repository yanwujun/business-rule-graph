---
name: business-rule-graph
description: 基于 roam-code 改造 — 从 Java/Spring Boot 代码中提取业务规则，构建规则知识图谱，代码变更后自动检测业务冲突。
---

# Business Rule Graph — 改造方案

## 项目定位

基于 [roam-code](https://github.com/Cranot/roam-code)（本地代码智能 CLI，SQLite 图存储，28 语言支持）改造，
专注解决一个核心问题：

> **AI 修改代码后，自动判断是否引入了业务规则冲突。**

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
│   └── business_rules/           ← 🆕 新增模块
│       ├── __init__.py
│       ├── extractor.py           # Phase 1: 规则提取器
│       ├── patterns.py            # AST 匹配模式定义
│       ├── models.py              # 规则数据模型
│       ├── graph.py               # Phase 2: 规则图谱
│       ├── conflict.py            # Phase 3: 冲突检测
│       ├── snapshot.py            # 规则版本快照
│       └── commands/              # CLI 命令
│           ├── cmd_br_extract.py
│           ├── cmd_br_graph.py
│           ├── cmd_br_check.py
│           └── cmd_br_diff.py
```

---

## Phase 1: 业务规则提取器

### 1.1 数据模型 (`models.py`)

```python
@dataclass
class BusinessRule:
    rule_id: str          # "order-minimum-amount"
    rule_type: RuleType   # validation | authorization | workflow | calculation
    domain: str           # "订单管理"
    flow: str             # "用户下单流程"  
    description: str      # "订单金额必须 ≥ ¥100"
    severity: str         # critical | high | medium | low
    source_file: str      # "src/.../OrderService.java"
    source_line: int      # 145
    source_symbol: str    # "validateOrder"
    params: dict          # {"field": "total", "operator": ">=", "threshold": 100}
    annotations: list     # ["@NotNull", "@Min(100)"]
    related_symbols: list # ["Order.total", "BusinessException"]
```

### 1.2 Java AST 规则匹配模式 (`patterns.py`)

基于 roam-code 已有的 `JavaExtractor` (tree-sitter)，新增规则识别模式：

| 模式 | AST 特征 | 规则类型 |
|------|----------|----------|
| 校验注解 | `@NotNull`, `@Min`, `@Max`, `@Size`, `@Pattern`, `@Valid` | validation |
| 断言异常 | `if (condition) throw new BusinessException(msg)` | validation |
| 权限检查 | `@PreAuthorize`, `@RolesAllowed`, `hasRole(...)` | authorization |
| 状态枚举 | `enum *Status { ... }` + `setStatus()` 方法 | workflow |
| 金额计算 | Service 层带有 `BigDecimal` 运算的方法 | calculation |
| 唯一性校验 | `existsBy*()`, `findBy*() != null` 模式 | data_integrity |
| 配置开关 | `@Value("${...}")` 控制行为分支 | configuration |
| 外部调用 | `@Retryable`, `@CircuitBreaker`, `RestTemplate` | integration |

### 1.3 提取流程 (`extractor.py`)

```
1. 复用 roam-code indexer 扫描所有 .java 文件
2. 对每个文件调用 JavaExtractor.extract_symbols() 获取符号
3. 对每个 symbol 的 AST 子树：
   a. 遍历 annotations → 匹配校验规则
   b. 遍历 if-throw 模式 → 匹配断言规则
   c. 遍历方法体 → 匹配计算规则
4. 存储到 SQLite 新表 business_rules
```

---

## Phase 2: 业务规则图谱

### 2.1 新增 DB 表 (`db/schema.py` 扩展)

```sql
-- 业务规则表
CREATE TABLE IF NOT EXISTS business_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL UNIQUE,
    rule_type TEXT NOT NULL,        -- validation/authorization/workflow/calculation/...
    domain TEXT NOT NULL,           -- 业务域
    flow TEXT,                      -- 业务流程
    description TEXT NOT NULL,
    severity TEXT DEFAULT 'medium', -- critical/high/medium/low
    source_file TEXT NOT NULL,
    source_line INTEGER,
    source_symbol TEXT,
    params JSON,                    -- {"field":"total","operator":">=","threshold":100}
    annotations JSON,               -- ["@NotNull","@Min(100)"]
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 规则-代码关联边
CREATE TABLE IF NOT EXISTS business_rule_code_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER REFERENCES business_rules(id),
    symbol_id INTEGER REFERENCES symbols(id),   -- roam-code symbols 表
    edge_type TEXT NOT NULL,                     -- implemented_by / constrains / references
    file_id INTEGER REFERENCES files(id)
);

-- 规则-规则关联边
CREATE TABLE IF NOT EXISTS business_rule_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_rule_id INTEGER REFERENCES business_rules(id),
    target_rule_id INTEGER REFERENCES business_rules(id),
    edge_type TEXT NOT NULL,        -- related / conflicts_with / depends_on / supersedes
    confidence REAL DEFAULT 0.5
);

-- 规则版本快照
CREATE TABLE IF NOT EXISTS business_rule_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    git_commit TEXT,
    snapshot_at TEXT DEFAULT (datetime('now')),
    rule_count INTEGER,
    changed_rules JSON             -- [{"rule_id":"...","change_type":"added|modified|removed"}]
);
```

### 2.2 图谱构建 (`graph.py`)

```
输入: business_rules 表 + roam-code symbols/edges 表
输出: 双层知识图谱

Layer 1 — 规则→代码溯源
    business_rule:order-minimum-amount
        ├── [implemented_by] → symbol:OrderService.validateOrder
        ├── [constrains] → symbol:Order.total
        └── [in_file] → file:OrderService.java

Layer 2 — 规则→规则关系
    business_rule:order-minimum-amount
        ├── [same_field_as] → business_rule:payment-minimum-amount
        ├── [same_flow] → business_rule:order-status-transition
        └── [conflicts_with] → business_rule:payment-minimum-amount
```

---

## Phase 3: 冲突检测引擎

### 3.1 检测规则 (`conflict.py`)

| 检测类型 | 触发条件 | 严重度 | 示例 |
|----------|----------|--------|------|
| **阈值不一致** | 同一字段在不同 Service 中被不同阈值校验 | CRITICAL | OrderService: total≥50, PaymentService: total≥100 |
| **状态机断裂** | 流程链中某一环节的允许状态与上下游不匹配 | CRITICAL | A→B→C 中 B 删除了，但 C 还在检查 B |
| **权限泄露** | 新代码移除了原本存在的权限注解 | HIGH | 删除了 @PreAuthorize 的方法 |
| **计算规则冲突** | 同一业务值的计算逻辑在多处不一致 | HIGH | 折扣率在 A 处 0.9，B 处 0.85 |
| **配置漂移** | 同一 @Value 在不同文件中的默认值不一致 | MEDIUM | maxRetry: 3 vs maxRetry: 5 |
| **唯一性约束重复** | 多个 existsBy 检查同一组字段但逻辑不同 | MEDIUM | existsByNameAndStatus vs existsByNameAndType |

### 3.2 检测流程

```
1. 加载当前规则快照 + 上一版本规则快照
2. 按 rule_type 分组
3. 对每组：
   a. 同域规则：提取所有 params["field"] 相同的规则 → 比对阈值
   b. 流程链：提取同一 flow 的规则 → 按 flow step 排序 → 检查一致性
   c. 变更追踪：added 规则的 params 与已有规则比对
4. 生成冲突报告 JSON
```

---

## Phase 4: CLI 和 MCP 命令

### 4.1 CLI 命令

```bash
# 规则提取
roam business-rules extract          # 从当前代码提取所有业务规则
roam business-rules extract --domain 订单管理  # 指定域
roam business-rules extract --diff            # 与上次快照对比

# 图谱操作
roam business-rules graph            # 构建/更新规则图谱
roam business-rules graph --export   # 导出为 JSON/HTML
roam business-rules explain <rule-id>  # 解释单条规则
roam business-rules path <rule-a> <rule-b>  # 规则间关系路径

# 冲突检测
roam business-rules check            # 全面冲突检测
roam business-rules check --domain 订单管理  # 指定域检测
roam business-rules check --preflight  # 作为 preflight 的一环

# 快照管理
roam business-rules snapshot         # 创建当前快照
roam business-rules diff             # 对比两个快照
```

### 4.2 MCP 工具（注册到 mcp_server.py）

```python
# 在 MCP core preset 中新增：
"business_rules_extract": cmd_br_extract.extract,
"business_rules_check": cmd_br_check.check,
"business_rules_graph": cmd_br_graph.graph,
"business_rules_diff": cmd_br_diff.diff,
```

---

## 实施路线图

### Milestone 1: 最小可行版（2-3 天）

- [x] Fork roam-code → business-rule-graph
- [ ] 新增 `src/roam/business_rules/` 模块骨架
- [ ] 实现 `patterns.py` — 5 种核心 Java 规则模式
- [ ] 实现 `extractor.py` — 基础规则提取
- [ ] 新增 DB schema（business_rules 表）
- [ ] 实现 `cmd_br_extract.py` — 第一条 CLI 命令
- [ ] 在 P2040 项目上跑通第一个规则提取

### Milestone 2: 图谱 + 冲突（2-3 天）

- [ ] 实现 `models.py` — 完整规则数据模型
- [ ] 实现 `graph.py` — 规则图谱构建/查询
- [ ] 实现 `conflict.py` — 3 种核心冲突检测
- [ ] 新增 business_rule_edges 等辅助表
- [ ] 实现 `cmd_br_check.py` — 冲突检测 CLI

### Milestone 3: 快照 + MCP（1-2 天）

- [ ] 实现 `snapshot.py` — 规则版本快照
- [ ] 实现 `cmd_br_diff.py` — 快照对比
- [ ] MCP 工具注册
- [ ] 集成到 preflight 流程（代码变更自动触发检查）

### Milestone 4: 生产化（持续）

- [ ] 支持更多 Java 规则模式（Spring Security、MyBatis、Redis 锁等）
- [ ] 冲突检测规则扩展
- [ ] HTML 可视化报告
- [ ] 支持 Python/Django 等其他语言

---

## 风险与边界

| 风险 | 缓解措施 |
|------|----------|
| AST 无法识别复杂业务语义 | 先用固定模式覆盖 80% 场景，剩余的留 LLM fallback |
| SVN 项目无 git history | 用 snapshot 时间戳替代 commit hash |
| roam-code 上游更新冲突 | 定期 rebase，改动集中在 `business_rules/` 独立模块 |
| 中文业务术语识别 | 从类名/包名/注解 message 中提取中文关键词 |

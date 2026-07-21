# Business Rule Graph — 需求规格说明书

> **项目名称:** business-rule-graph
> **基座:** roam-code v13.10.0 (Apache 2.0)
> **版本:** 1.0.0
> **日期:** 2026-07-21
> **状态:** 草稿
> **关联文档:** ROADMAP.md, IMPLEMENTATION.md, OPTIMIZATION.md

---

## 术语表

| 术语 | 定义 |
|------|------|
| **业务规则 (Business Rule)** | 从 Java/Spring Boot 代码中可识别的、表达业务约束的代码片段，如 if-throw 断言、注解、状态枚举等 |
| **规则类型 (RuleType)** | 8 种业务规则分类：validation / authorization / workflow / calculation / data_integrity / process / configuration / integration |
| **AST 引擎** | 基于 tree-sitter 的确定性规则提取器，不依赖 LLM，零 API 成本 |
| **LLM 引擎** | 基于大语言模型的语义增强器，补充 domain/flow/description，支持无 API key 时模板降级 |
| **规则图谱 (Rule Graph)** | 规则之间的关系网络，存储在 SQLite 中，含 same_field / same_flow / conflicts_with 三类边 |
| **规则快照 (Snapshot)** | 某一时刻全部规则的版本记录，含新增/删除/修改的规则清单 |
| **冲突 (Conflict)** | 两条规则之间存在业务矛盾：阈值不一致、权限被移除、状态机出现死端等 |
| **增量提取** | 只扫描 mtime 变化的文件，避免全量重扫，兼容 SVN（不依赖 git diff） |
| **语义归并** | LLM 引擎发现两条规则是同一业务含义的不同代码写法时，标记 merge_with 合并 |
| **政府采购系统** | 目标分析对象，Java + Spring Boot 架构，SVN 版本管理 |

---

## 业务目标 (OBJ)

### OBJ-01: AST 规则提取
从 Java/Spring Boot 项目源码中，使用 tree-sitter AST 解析自动识别 8 类业务规则（校验/权限/状态流转/业务计算/数据完整性/流程控制/配置/集成），支持增量提取（仅扫描变更文件），兼容 SVN 环境。

### OBJ-02: LLM 语义增强
为 AST 提取的规则批量补充业务语义：业务域（domain）、业务流程（flow）、自然语言描述（description），并自动归并语义相同的规则（不同写法→同一规则）。无 API key 时降级为模板生成。

### OBJ-03: 规则图谱构建
基于提取和语义增强后的规则，自动建立规则间的关系网络：同字段规则关联（same_field）、同流程规则关联（same_flow）、跨类型冲突关联（conflicts_with），支持图谱拓扑查询。

### OBJ-04: 冲突检测
自动检测业务规则之间的潜在冲突：同一字段存在不同阈值、权限规则被移除、状态机出现死端/孤立入口/不可达状态，输出冲突类型、严重级别和业务语言描述。

### OBJ-05: 版本快照与变更对比
支持创建规则版本快照作为基线，在代码变更后对比两个快照的规则差异（新增/删除/修改），输出可追溯的变更报告。

### OBJ-06: CLI 与 MCP 集成接口
提供 8 个 CLI 命令和 6 个 MCP 工具，支持人工和 AI 智能体两种使用方式。所有命令支持 --json 输出和进度反馈，适配 AI 编码工作流。

---

## 核心场景 (SCN)

### SCN-01: 首次建立规则基线
- **角色:** 开发者 / AI 编码智能体
- **触发条件:** 项目首次接入 business-rule-graph
- **前置条件:** 项目已运行 `roam init` 建立代码索引
- **主流程:**
  1. 执行 `roam business-rules extract` 全量扫描 Java 源码
  2. AST 引擎识别 if-throw 断言、状态判断、枚举定义、方法命名约定、注解等
  3. 规则写入 SQLite business_rules 表
  4. 执行 `roam business-rules summarize` 调用 LLM 补充语义
  5. 执行 `roam business-rules graph` 构建规则间关系边
  6. 执行 `roam business-rules snapshot --label "基线"` 创建版本快照
- **关键异常:**
  - 项目无 Java 文件 → 输出 "No business rules detected"
  - 未运行 roam init → 提示 "No index found. Run 'roam init' first"
  - LLM API key 未配置 → 降级为模板生成，不阻塞流程

### SCN-02: 代码变更后检测规则冲突
- **角色:** 开发者 / AI 编码智能体
- **触发条件:** 修改了 Java 源码（如调整阈值、删除权限注解、修改状态枚举）
- **前置条件:** 已存在基线快照
- **主流程:**
  1. 执行 `roam business-rules extract --update` 增量提取变更文件的规则
  2. 执行 `roam business-rules summarize` 为新增/变更规则补充语义
  3. 执行 `roam business-rules check` 检测冲突
  4. 如有冲突，输出冲突类型、严重级别、业务描述
  5. 执行 `roam business-rules diff` 对比基线看规则增删改
- **关键异常:**
  - 变更未引入新规则 → check 输出 "No conflicts detected"

### SCN-03: AI 智能体通过 MCP 自主检测
- **角色:** AI 编码智能体（如 Claude Code、Codex）
- **触发条件:** AI 完成代码修改后，通过 MCP 工具调用检测
- **前置条件:** 项目已建立索引和基线
- **主流程:**
  1. AI 调用 `business_rules_extract` MCP tool (update=true)
  2. AI 调用 `business_rules_check` MCP tool
  3. AI 根据冲突报告决定是否调整代码
  4. AI 调用 `business_rules_diff` MCP tool 确认变更范围
- **关键异常:**
  - 安全模式只读 → MCP policy_decision 拦截写操作

---

## 功能需求 (REQ)

### REQ-01: tree-sitter AST 规则识别
**关联:** SCN-01, OBJ-01

系统使用 tree-sitter Java parser 扫描源码，通过以下 AST 查询节点识别规则：
- `if_throw`: if (条件) + throw 异常
- `if_status_check`: if 语句中调用 getStatus()/isXxx() 方法
- `switch_on_status`: switch 语句基于状态变量分发
- `status_enum`: 名称含 "Status" 的 enum 定义
- `standalone_throw`: 不在 if 块内的独立 throw 语句
- `exception_catch`: try-catch 块捕获特定异常
- `validation_annotation`: @NotNull, @Min, @Max, @Size, @NotEmpty 等校验注解
- `auth_annotation`: @PreAuthorize, @RolesAllowed, @Secured 等权限注解
- `transactional`: @Transactional 注解
- `retryable`: @Retryable, @CircuitBreaker 等容错注解

### REQ-02: 方法命名约定识别
**关联:** SCN-01, OBJ-01

当 tree-sitter 查询未命中时，系统通过方法命名约定兜底识别规则：
- 方法名含 `check`/`validate`/`verify`/`ensure`/`assert` → validation
- 方法名含 `approve`/`reject`/`submit`/`audit`/`review` → workflow
- 方法名含 `calculate`/`compute`/`calc` → calculation
- 方法名含 `existsBy`/`findBy.*Unique` → data_integrity
- 方法名含 `sync`/`publish`/`notify`/`send`/`call` → integration

### REQ-03: 注解兜底识别
**关联:** SCN-01, OBJ-01

当 tree-sitter 和方法命名均未命中时，系统通过注解兜底识别：
- `@Transactional`, `@EventListener` → process
- `@Value`, `@ConfigurationProperties`, `@FeatureFlag` → configuration
- `@Retryable`, `@CircuitBreaker`, `@Bulkhead` → integration

### REQ-04: 规则去重
**关联:** OBJ-01

每条规则基于 (source_file | source_line | params) 计算 SHA256 hash，同一 hash 的规则不重复入库。

### REQ-05: 增量提取
**关联:** SCN-02, OBJ-01

`--update` 模式下，系统利用 roam-code 的文件 mtime 检测能力，只扫描变更过的 Java 文件，跳过未修改的文件。SVN 环境不依赖 git diff。

### REQ-06: LLM 批量语义增强
**关联:** SCN-01, SCN-02, OBJ-02

`roam business-rules summarize` 将当前所有规则批量发送给 LLM，每批最多 50 条。LLM 为每条规则补充：
- `domain`: 业务域（订单管理/供应商管理/商品管理/支付管理/审核管理/合同管理/框架协议/直采商城/系统管理）
- `flow`: 业务流程（下单/支付/审核/发货/签约/退款/同步/提交/审批）
- `description`: 30 字以内自然语言业务描述
- `severity`: critical/high/medium/low
- `merge_with`: 语义相同规则的 rule_id（归并标记）

### REQ-07: LLM 不可用时降级
**关联:** OBJ-02

当无 API key 或 LLM 调用失败时，系统降级为模板生成：
- domain: 从包名推断（如 `*.order.*` → 订单管理）
- flow: 从类名推断（如 `OrderController` → 下单）
- description: 模板拼接（如 `{rule_type}: {source_symbol} at {source_file}:{source_line}`）
- merge_with: 不标记归并

### REQ-08: 同字段规则关联
**关联:** OBJ-03

系统根据规则的 params.field/params.value/params.status_value/params.exception_message 字段，将引用相同字段或值的规则建立 `same_field` 边。

### REQ-09: 同流程规则关联
**关联:** OBJ-03

系统根据规则的 flow 字段（LLM 补充或模板推断），将属于同一业务流程的规则建立 `same_flow` 边。

### REQ-10: 跨类型冲突边
**关联:** OBJ-03

系统对引用相同字段但 rule_type 不同的规则，自动建立 `conflicts_with` 边（如 validation 规则和 authorization 规则操作同一字段）。

### REQ-11: 阈值冲突检测
**关联:** SCN-02, OBJ-04

系统检测同一字段在不同规则中存在不一致的阈值。例如 `total >= 100` 和 `amount < 50则抛异常` 被识别为阈值冲突（critical 级别）。

### REQ-12: 权限移除检测
**关联:** SCN-02, OBJ-04

当对比快照发现 authorization 类型规则被删除时，系统标记为权限移除冲突（critical 级别），提示可能引入安全风险。

### REQ-13: 状态机断裂检测
**关联:** OBJ-04

系统收集所有 workflow 规则的 status_value 和 enum_values，构建状态转移图，检测：
- 死端状态：只有入边无出边
- 孤立入口：只有出边无入边
- 不可达状态：枚举定义但无规则引用

### REQ-14: 规则快照创建
**关联:** OBJ-05

`roam business-rules snapshot --label "标签"` 记录当前全部规则的 rule_id 集合，包含：快照标签、规则总数、新增规则列表（相对上一快照）、删除规则列表、git commit 号（可选）。

### REQ-15: 快照变更对比
**关联:** OBJ-05

`roam business-rules diff --from <id> --to <id>` 对比两个快照，输出：
- 新增规则：出现在 to 快照但不在 from 快照中的规则
- 删除规则：出现在 from 快照但不在 to 快照中的规则
- 修改规则：rule_id 相同但 hash 不同的规则

### REQ-16: 规则列表查询
**关联:** OBJ-06

`roam business-rules list` 列出所有已提取规则，支持 `--type`（按 RuleType 过滤）、`--domain`（按业务域过滤）、`--json`（JSON 输出）。

### REQ-17: 单条规则详情
**关联:** OBJ-06

`roam business-rules explain <rule-id>` 输出：规则基本信息（类型/域/流程/描述/源码位置/参数）、关联规则列表（含 edge_type）。

### REQ-18: JSON 输出
**关联:** OBJ-06

所有 CLI 命令支持 `--json` 标志，输出结构化 JSON 供 AI 智能体解析。非 JSON 模式输出人类可读文本。

### REQ-19: MCP 工具接口
**关联:** SCN-03, OBJ-06

提供 6 个 MCP 工具：`business_rules_extract`、`business_rules_summarize`、`business_rules_graph`、`business_rules_check`、`business_rules_snapshot`、`business_rules_diff`。每个工具通过 subprocess 调用 CLI 命令的 `--json` 模式，返回结构化结果。

### REQ-20: HTML 报告生成
**关联:** OBJ-04, OBJ-05

系统支持将规则图谱和冲突检测结果导出为 HTML 报告，包含规则分类统计、图谱可视化、冲突清单。

---

## 业务不变量 (INV)

### INV-01: 规则可追溯
每条规则必须包含 source_file 和 source_line，可追溯到具体代码位置。rule_id 格式为 `{文件名}:{行号}:{提取方式}`。

### INV-02: 规则幂等
同一 hash 的规则只存储一条。重复提取不产生重复记录。

### INV-03: AST 与 LLM 解耦
AST 提取不依赖 LLM。LLM 不可用时系统仍可通过模板降级完成语义补充，不阻塞下游流程（图谱/冲突/快照）。

### INV-04: 数据本地化
源码不离开本机。LLM 调用仅发送规则结构化摘要（不含源代码）。所有结果存储在本地 SQLite。

### INV-05: 快照不可变
已创建的快照记录不可修改或删除。每次新的快照创建新记录，保留完整历史。

---

## 验收标准 (AC)

### AC-01: 全量提取
**关联:** REQ-01, REQ-02, REQ-03

- **Given** 一个 Java/Spring Boot 项目已运行 `roam init`
- **When** 执行 `roam business-rules extract`
- **Then** 系统扫描所有 Java 文件，输出提取到的规则数量和按 RuleType 分类的统计

### AC-02: 增量提取
**关联:** REQ-05

- **Given** 已执行过一次全量提取，且修改了 3 个 Java 文件
- **When** 执行 `roam business-rules extract --update`
- **Then** 系统仅扫描变更的 3 个文件，跳过来修改的文件，输出更新后的规则统计

### AC-03: LLM 语义增强
**关联:** REQ-06

- **Given** 已提取 80 条规则，配置了 LLM API key
- **When** 执行 `roam business-rules summarize`
- **Then** 系统分两批（50+30）发送 LLM 请求，将返回的 domain/flow/description/merge_with 写回数据库，输出增强规则数和归并数

### AC-04: 模板降级
**关联:** REQ-07

- **Given** 已提取规则，但未配置 LLM API key
- **When** 执行 `roam business-rules summarize`
- **Then** 系统提示 "No API key — using template fallback"，用包名/类名推断 domain/flow，模板生成 description，不标记 merge_with

### AC-05: 图谱构建
**关联:** REQ-08, REQ-09, REQ-10

- **Given** 数据库中有 50 条已增强的规则
- **When** 执行 `roam business-rules graph`
- **Then** 系统输出总边数和按类型（same_field/same_flow/conflicts_with）分类的边统计

### AC-06: 阈值冲突检测
**关联:** REQ-11

- **Given** 数据库中有两条规则引用同一字段 `total`，阈值分别为 `100` 和 `50`
- **When** 执行 `roam business-rules check`
- **Then** 系统输出 `[CRITICAL] threshold_mismatch: 字段 'total' 阈值不一致: 100 vs 50`，包含两条规则的源码位置

### AC-07: 权限移除检测
**关联:** REQ-12

- **Given** 基线快照中有一条 authorization 规则，当前已删除
- **When** 执行 `roam business-rules check --snapshot-id <baseline_id>`
- **Then** 系统检测到权限规则被移除，输出 critical 级别冲突

### AC-08: 状态机断裂检测
**关联:** REQ-13

- **Given** workflow 规则中有 DRAFT→SUBMITTED 和 SUBMITTED→APPROVED 的转移，但 APPROVED 状态无出边
- **When** 执行 `roam business-rules check`
- **Then** 系统输出 APPROVED 为死端状态的冲突

### AC-09: 快照与 diff
**关联:** REQ-14, REQ-15

- **Given** 已创建快照 #1（100 条规则），修改代码后执行 extract 和 snapshot --label "v2" 创建快照 #2（103 条规则）
- **When** 执行 `roam business-rules diff --from 1 --to 2`
- **Then** 系统输出 +3 新增规则、-0 删除规则、可能存在的修改规则

### AC-10: 规则列表
**关联:** REQ-16

- **Given** 数据库中有 30 条规则
- **When** 执行 `roam business-rules list`
- **Then** 系统输出表格：rule_id, type, domain, description
- **When** 执行 `roam business-rules list --type validation`
- **Then** 系统仅输出 validation 类型的规则

### AC-11: 规则详情
**关联:** REQ-17

- **Given** 数据库中有规则 `OrderService.java:145:if-throw`
- **When** 执行 `roam business-rules explain OrderService.java:145:if-throw`
- **Then** 系统输出规则完整信息（类型/域/流程/描述/源码位置/参数/提取方式）和关联规则列表

### AC-12: JSON 输出
**关联:** REQ-18

- **Given** 任意 CLI 命令
- **When** 加上 `--json` 标志执行
- **Then** 系统输出合法 JSON，可由程序解析

### AC-13: CLI 熔断 — 无索引
**关联:** REQ-01

- **Given** 项目未运行 `roam init`，`.roam/index.db` 不存在
- **When** 执行 `roam business-rules extract`
- **Then** 系统输出 "Error: No index found. Run 'roam init' first."，退出

### AC-14: 无规则检出
**关联:** REQ-01

- **Given** 项目中没有匹配的 Java 业务规则模式
- **When** 执行 `roam business-rules extract`
- **Then** 系统输出 "No business rules detected."

### AC-15: 无冲突
**关联:** REQ-11, REQ-12, REQ-13

- **Given** 数据库中的规则两两之间无冲突
- **When** 执行 `roam business-rules check`
- **Then** 系统输出 "No conflicts detected."

---

## 非功能需求 (NFR)

### NFR-01: 性能 — 大项目提取
- **场景:** 1000+ Java 文件的中大型政府采购项目
- **指标:** 全量提取 < 60 秒，增量提取 < 10 秒
- **验证:** `time roam business-rules extract` 计时

### NFR-02: LLM 调用效率
- **场景:** 200 条规则需语义增强
- **指标:** 每批 50 条，共 4 次 API 调用，总耗时 < 30 秒（不含 LLM 响应时间）
- **验证:** summarize 命令输出进度日志

### NFR-03: 数据安全
- **场景:** AI 智能体通过 MCP 调用
- **指标:** 源码不离开本机，LLM 调用仅发送规则结构化摘要（不含完整源码）
- **验证:** 审查 summarizer.py 的批量方法输入内容

### NFR-04: 兼容性
- **场景:** SVN 管理的政府采购项目
- **指标:** extract --update 增量检测基于文件 mtime，不依赖 git
- **验证:** 在 SVN 工作副本中修改 2 个文件后执行 --update，确认仅扫描变更文件

---

## 待确认事项 (TBD)

### TBD-01: 状态机断裂检测完整度
OPTIMIZATION.md 标记 `_status_deadend()` 为待完善项，但 conflict.py 中已有实现。需确认当前实现是否覆盖死端/孤立入口/不可达状态三种检测，还是仅实现了部分。

### TBD-02: 进度条实现方式
OPTIMIZATION.md 建议引入 click.progressbar，需确认是否直接使用 Click 内置（零依赖）还是引入 tqdm。

### TBD-03: 规则提取的性能测试
对 P2040 直采商城项目（5 个工程，Java 源码规模未知）的实际执行时间需实测。

---

## 变更记录

| 版本 | 日期 | 变更摘要 |
|------|------|----------|
| 1.0.0 | 2026-07-21 | 初始版本，覆盖 6 个 OBJ、3 个 SCN、20 个 REQ、5 个 INV、15 个 AC、4 个 NFR |

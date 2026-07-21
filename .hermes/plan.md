# Business Rule Graph — 技术实施方案

> **项目:** business-rule-graph | **基座:** roam-code v13.10.0
> **日期:** 2026-07-21 | **状态:** 草稿
> **上游:** [spec.md](./spec.md) | **下游:** tasks.md

---

## 1. 审查结论与架构决策

### 1.1 系统定位

| 维度 | 决策 |
|------|------|
| **系统类型** | Python CLI + MCP Server（对 roam-code 的扩展模块） |
| **运行方式** | `roam business-rules <command>` 子命令组，或 MCP tool 调用 |
| **技术栈** | Python 3.10+, tree-sitter + tree-sitter-language-pack, networkx, SQLite, Click, MCP (fastmcp + mcp>=1.28.1) |
| **打包方式** | pip install -e ".[mcp]" 开发模式，pyproject.toml 声明入口 `roam = "roam.cli:cli"` |
| **扩展方式** | 对 roam-code 最小侵入：DB schema 追加、CLI lazy-load map 追加、MCP tool 注册追加 |

[来源: pyproject.toml, ROADMAP.md]

### 1.2 Spec 审查结果

| 类别 | 条目 | 处理方式 |
|------|------|----------|
| 已明确 | OBJ-01~06 全部有对应 REQ | ✅ 可进入设计 |
| 已明确 | 8 种 RuleType、6 种冲突检测 | ✅ |
| 待确认 | TBD-01 状态机断裂检测完整度 | 假设：`_status_deadend()` 已实现三种检测（死端/孤立入口/不可达），需代码审查验证 |
| 待确认 | TBD-02 进度条实现方式 | 假设：使用 Click 内置 `click.progressbar`（零额外依赖） |
| 待确认 | TBD-03 P2040 项目性能实测 | 延期到集成测试阶段 |
| 非功能缺口 | NFR-01 性能指标 | 当前未量化验证，需增加 benchmark |
| 非功能缺口 | 测试覆盖 | business_rules 模块无独立单元测试 |

[来源: spec.md TBD-01~03, NFR-01]

### 1.3 核心架构决策

| # | 决策 | 选择 | 候选方案 | 取舍理由 | 来源 |
|---|------|------|----------|----------|------|
| ADR-01 | 扩展方式 | 模块内嵌 roam-code | 独立 pip 包 / fork 仓库 | 最小侵入，跟随上游升级成本最低 | ROADMAP.md |
| ADR-02 | 规则提取引擎 | tree-sitter AST（确定性） | Regex / javaparser / LLM-only | tree-sitter 零网络、强类型、精确；LLM 做语义增强而非提取 | ROADMAP.md |
| ADR-03 | LLM 引擎 | 批量 OpenAI-compatible API + 模板降级 | 逐文件调用 / 强制 LLM | 批量减少 API 调用次数；降级保证 LLM 不可用时不阻塞 | summarizer.py |
| ADR-04 | 存储 | SQLite（复用 roam-code .roam/index.db） | 独立 JSON 文件 / PostgreSQL | 复用基座 DB，零运维；ACID 事务保证 | db/schema.py |
| ADR-05 | CLI 框架 | Click（复用 roam-code） | Typer / argparse | 不引入新框架，与基座一致 | cli.py |
| ADR-06 | 图谱引擎 | networkx（复用 roam-code） | igraph / 自建 | roam-code 已依赖 networkx，零新增依赖 | pyproject.toml |
| ADR-07 | 文件变更检测 | roam-code mtime 检测 | git diff / 文件 hash | 支持 SVN，不依赖 git | ROADMAP.md |
| ADR-08 | 进度条 | click.progressbar | tqdm | 零额外依赖，与 CLI 框架一致 | 假设，TBD-02 |

---

## 2. 领域建模与核心抽象

### 2.1 核心领域概念

| 概念 | 类型 | 职责 | 关键规则 | 来源 |
|------|------|------|----------|------|
| BusinessRule | Entity | 一条业务规则的完整描述 | rule_id 唯一标识；hash=(source_file\|line\|params) SHA256 去重 | spec.md REQ-01~04 |
| RuleType | Enum (8值) | 规则分类 | validation/authorization/workflow/calculation/data_integrity/process/configuration/integration | spec.md 术语表 |
| Severity | Enum (4值) | 严重级别 | critical/high/medium/low | spec.md REQ-06 |
| Conflict | Value Object | 一个检测到的冲突 | 含 conflict_type, severity, rule_a, rule_b, description | spec.md REQ-11~13 |
| RuleSnapshot | Entity | 一个版本的规则集合 | 不可变；含 label, rule_count, added/removed/modified 清单 | spec.md INV-05 |
| RuleGraph | Domain Service | 规则间关系网络 | same_field/same_flow/conflicts_with 三类边 | spec.md OBJ-03 |
| ConflictDetector | Domain Service | 冲突检测引擎 | threshold_mismatch / auth_removed / status_deadend | spec.md OBJ-04 |

### 2.2 状态流转与业务不变量

```
项目生命周期:
  未初始化 ──(roam init)──► 已索引 ──(extract)──► 规则已提取
                                                      │
                                              (summarize)
                                                      ▼
                                                 语义已增强
                                                      │
                                               (graph)
                                                      ▼
                                                 图谱已构建
                                                      │
                                              (snapshot)
                                                      ▼
                                              基线已建立 ──(改代码)──► 增量提取 ──(check)──► 冲突报告
```

**不变量：**
- INV-01: 每条规则可追溯到 source_file:source_line [来源: spec.md INV-01]
- INV-02: 同一 hash 的规则只存一条 [来源: spec.md INV-02]
- INV-03: AST 引擎独立于 LLM，LLM 不可用时不阻塞 [来源: spec.md INV-03]
- INV-04: 源码不离开本机，LLM 仅发送规则摘要 [来源: spec.md INV-04]
- INV-05: 快照不可变，完整保留历史 [来源: spec.md INV-05]

### 2.3 模块分层与依赖方向

```
┌─────────────────────────────────────────────────────┐
│ Interfaces: CLI (cmd_br_extract.py) + MCP (mcp_server.py) │
│   职责: 参数解析、输入校验、输出格式化、Exit Code 映射      │
│   依赖: → Application                                  │
├─────────────────────────────────────────────────────┤
│ Application: (当前合并于 CLI 层)                        │
│   职责: 用例编排、事务边界                              │
│   依赖: → Domain                                       │
├─────────────────────────────────────────────────────┤
│ Domain: business_rules/                               │
│   models.py    — 实体 + 值对象                         │
│   patterns.py  — 规则匹配模式                          │
│   extractor.py — AST 确定性引擎                        │
│   summarizer.py— LLM 语义引擎                          │
│   graph.py     — 规则图谱                              │
│   conflict.py  — 冲突检测                              │
│   snapshot.py  — 版本快照                              │
│   loader.py    — 共享数据加载                           │
│   html_report.py— HTML 报告                            │
│   依赖: → 无框架依赖，仅依赖 SQLite (infrastructure)      │
├─────────────────────────────────────────────────────┤
│ Infrastructure:                                       │
│   roam.db.connection — SQLite 连接池                  │
│   roam.db.schema      — DDL (含 business_rules 表)    │
│   roam.index.indexer  — 文件索引 (mtime 检测)          │
│   roam.languages.*    — tree-sitter Java parser       │
└─────────────────────────────────────────────────────┘
```

**当前架构评估：**

> ⚠️ 当前实现中 Application 层与 CLI 层存在**轻度耦合**——`cmd_br_extract.py` 中直接调用 Domain 层（`BusinessRuleExtractor`、`RuleSummarizer` 等）并自行管理 SQLite 连接。对于当前规模（<2000 行业务代码），这在可接受范围内，但未来复杂化时应抽离 UseCase 层。

[来源: 代码分析, cmd_br_extract.py]

### 2.4 关键抽象

| 抽象 | 所在层 | 职责 | 是否必要 | 来源 |
|------|--------|------|----------|------|
| BusinessRuleExtractor | Domain | tree-sitter AST 规则提取 | ✅ 核心引擎 | spec.md OBJ-01 |
| RuleSummarizer | Domain | LLM 批量语义增强 + 模板降级 | ✅ 双引擎之一 | spec.md OBJ-02 |
| RuleGraph | Domain | 规则间关系边构建 + 拓扑查询 | ✅ 图谱核心 | spec.md OBJ-03 |
| ConflictDetector | Domain | 三类冲突检测算法 | ✅ 核心价值 | spec.md OBJ-04 |
| RuleSnapshot | Domain | 快照创建/diff/列表 | ✅ 版本管理 | spec.md OBJ-05 |
| load_rules() | Domain | 共享 SQLite 加载 + JSON 解析 | ✅ 去重复用 | OPTIMIZATION.md #4 |

---

## 3. CLI 命令模型与输入输出契约

### 3.1 命令总览

| 命令 | 用途 | 关键参数 | 输出格式 | Exit Code | 来源 |
|------|------|----------|----------|-----------|------|
| `business-rules-extract` | AST 提取规则 | `--update`, `--json`, `--project-root` | text/JSON | 0/1 | spec.md REQ-01~05 |
| `business-rules-summarize` | LLM 语义增强 | `--api-key`, `--model`, `--batch-size`, `--json` | text/JSON | 0/1 | spec.md REQ-06~07 |
| `business-rules-graph` | 构建图谱 | `--stats`, `--json` | text/JSON | 0/1 | spec.md REQ-08~10 |
| `business-rules-check` | 冲突检测 | `--snapshot-id`, `--json` | text/JSON | 0/1 | spec.md REQ-11~13 |
| `business-rules-snapshot` | 创建快照 | `--label`, `--commit`, `--list`, `--json` | text/JSON | 0/1 | spec.md REQ-14 |
| `business-rules-diff` | 对比快照 | `--from`, `--to` | text | 0/1 | spec.md REQ-15 |
| `business-rules-list` | 规则列表 | `--type`, `--domain`, `--json` | table/JSON | 0/1 | spec.md REQ-16 |
| `business-rules-explain` | 规则详情 | `<rule-id>`, `--json` | text/JSON | 0/1 | spec.md REQ-17 |

### 3.2 输入来源

| 来源 | 支持 | 使用方式 | 约束 |
|------|------|----------|------|
| CLI 参数 | ✅ | Click options/arguments | 必填参数无默认值 |
| 环境变量 | ✅ | OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / LLM_MODEL | 仅 summarizer 使用 |
| SQLite DB | ✅ | `.roam/index.db`（由 roam init 创建） | 所有命令的输入源 |
| 配置文件 | ❌ | 不适用 | 无额外配置需求 |
| stdin | ❌ | 不适用 | — |

### 3.3 输出契约

| 输出类型 | 位置 | 格式 | 可脚本消费 | 说明 |
|----------|------|------|-----------|------|
| 正常结果 | stdout | text（默认）/ JSON（--json） | ✅ | --json 时只输出合法 JSON |
| 错误信息 | stderr | text | ❌ | 如 "No index found" |
| HTML 报告 | 文件 | HTML | ❌ | html_report.py 生成 |
| 日志 | logging | text | ❌ | 不污染 stdout |

### 3.4 Exit Code 规范

| Exit Code | 含义 | 触发场景 |
|----------:|------|----------|
| 0 | 成功 | 命令正常完成 |
| 1 | 通用失败 | 索引不存在、规则未找到、未知错误 |

> ⚠️ 当前实现中所有错误统一返回 `1`。按 plan prompt 规范应细化为 2(参数错误)/3(业务冲突)/4(输入错误)/5(外部依赖失败)/10(未预期错误)。此项为**待优化项**。

[来源: exit_codes.py 分析, plan prompt §四.4]

### 3.5 命令 → 模块映射

| 命令 | Click 函数 | 调用的 Domain 类 | 主要输出 |
|------|-----------|-----------------|----------|
| extract | `cmd_br_extract` | `BusinessRuleExtractor` | 规则统计 + by_type |
| summarize | `cmd_br_summarize` | `RuleSummarizer` | 增强数 + 归并数 |
| graph | `cmd_br_graph` | `RuleGraph` | 边统计 |
| check | `cmd_br_check` | `ConflictDetector` | 冲突列表 |
| snapshot | `cmd_br_snapshot` | `RuleSnapshot` | 快照 ID |
| diff | `cmd_br_diff` | `RuleSnapshot` | 变更摘要 |
| list | `cmd_br_list` | SQLite 直查 | 规则表格 |
| explain | `cmd_br_explain` | `RuleGraph.related()` | 单规则 + 关联 |

---

## 4. 非功能性设计

### 4.1 防御性策略

| 场景 | 处理方式 | 输出 | Exit Code | 来源 |
|------|----------|------|-----------|------|
| 未运行 roam init | 检测 `.roam/index.db` 不存在 | stderr: "No index found" | 1 | spec.md AC-13 |
| 无 Java 文件/无规则 | 空结果集 | stdout: "No business rules detected" | 0 | spec.md AC-14 |
| LLM API key 缺失 | 降级为模板生成 | stdout: 增强数 | 0 | spec.md REQ-07 |
| LLM API 调用失败 | logging.error + 模板降级 | stdout: 部分增强数 | 0 | summarizer.py |
| tree-sitter 不可用 | HAS_TREE_SITTER=False | 跳过 AST 提取，仅用方法命名+注解 | 0 | extractor.py |
| SQLite 写入冲突 | roam-code atomic_io | 事务回滚 | 1 | atomic_io.py |
| 规则 rule_id 不存在 | SQL 查询返回 None | stderr: "Rule not found" | 1 | cmd_br_extract.py |

### 4.2 配置与环境

| 配置项 | 来源优先级 | 默认值 | 说明 |
|--------|-----------|--------|------|
| LLM API key | 环境变量 > CLI --api-key | 无 | OPENAI_API_KEY/ANTHROPIC_API_KEY/DEEPSEEK_API_KEY |
| LLM base URL | 环境变量 > CLI --base-url | https://api.openai.com/v1 | OpenAI 兼容 API |
| LLM model | 环境变量 > CLI --model | gpt-4.1-mini | — |
| batch_size | CLI --batch-size | 50 | 每批 LLM 调用规则数 |
| project_root | CLI --project-root | roam.db.connection.find_project_root() | 自动检测或手动指定 |
| db_path | 计算 | {project_root}/.roam/index.db | 与 roam-code 共享 |

### 4.3 持久化边界

- **存储引擎:** SQLite，文件路径 `{project_root}/.roam/index.db`
- **表:** 5 张（business_rules, business_rule_code_edges, business_rule_edges, business_rule_snapshots）+ 对应索引
- **事务:** 每条命令内使用 `with sqlite3.connect() as conn` 管理，commit 在 with 块结束时自动提交
- **并发:** 无并发写入场景（CLI 单进程），无需 WAL 模式或锁管理
- **迁移:** 表创建使用 `CREATE TABLE IF NOT EXISTS`，随 roam-code schema.py 初始化

### 4.4 性能与资源约束

| 指标 | 目标 | 当前状态 | 来源 |
|------|------|----------|------|
| 全量提取 <60s (1000 文件) | NFR-01 | 未验证 | spec.md NFR-01 |
| 增量提取 <10s | NFR-01 | 未验证 | spec.md NFR-01 |
| LLM 批量调用 <30s（不含 LLM 响应） | NFR-02 | 未验证 | spec.md NFR-02 |
| 内存占用 | 未定义 | — | — |

### 4.5 可观测性

- **日志:** Python `logging` 标准库，模块级 `logger = logging.getLogger(__name__)`
- **进度:** extractor.py 每 10% 输出 info 日志；计划增加 `click.progressbar`
- **遥测:** 复用 roam-code `roam.telemetry`（opt-in）

---

## 5. 实施路径与待优化项

### 5.1 分阶段建议

| 阶段 | 内容 | 状态 | 预计工时 |
|------|------|------|----------|
| M1 | 规则提取 MVP（models/patterns/extractor/summarizer/graph/conflict/snapshot + 8 CLI + 6 MCP） | ✅ 已完成 | 2-3天 |
| M2 | 剩余优化项（进度条 + _find_rule 索引 + Exit Code 细化） | 🔲 待实施 | ~0.5天 |

### 5.2 待优化项详表

| # | 项 | 文件 | 优先级 | 来源 |
|---|------|------|--------|------|
| OPT-01 | `_find_rule` 字典索引替代 O(n×m) 线性查找 | summarizer.py | 🟢 P3 | OPTIMIZATION.md #5 |
| OPT-02 | 添加 `click.progressbar` 进度条 | extractor.py | 🟢 P3 | OPTIMIZATION.md #6 |
| OPT-03 | Exit Code 细化（0/1/2/3/4/5/10） | cmd_br_extract.py, exit_codes.py | 🟡 P2 | plan prompt §四.4 |
| OPT-04 | business_rules 模块单元测试 | tests/ | 🟡 P2 | 代码审查 |

### 5.3 OPT-01: _find_rule 字典索引

**位置:** `summarizer.py` `_merge_results()` 方法

**当前实现（假设）:**
```python
def _merge_results(self, rules, results):
    for r in rules:
        for llm in results:
            if llm["rule_id"] == r["rule_id"]:
                r.update(...)  # O(n×m)
```

**优化方案:**
```python
def _merge_results(self, rules, results):
    by_id = {r["rule_id"]: r for r in results}  # O(m)
    for r in rules:                              # O(n)
        llm = by_id.get(r["rule_id"])
        if llm:
            r.update({k: v for k, v in llm.items() if k != "rule_id"})
```

**影响:** 200 条规则时从 40,000 次比较降至 200 次

### 5.4 OPT-02: 进度条

**位置:** `extractor.py` `extract_from_db()` 方法

**方案:**
```python
from click import progressbar

for file_rel in progressbar(files_to_scan, label="Extracting business rules"):
    ...
```

**风险评估:** click.progressbar 在 stderr 输出，不污染 --json 的 stdout。无风险。

### 5.5 OPT-03: Exit Code 细化

| Exit Code | 枚举名 | 映射场景 |
|----------:|--------|----------|
| 0 | SUCCESS | 命令正常完成 |
| 1 | GENERAL_ERROR | 索引不存在、规则未找到 |
| 2 | INVALID_ARGS | 参数校验失败 |
| 3 | BUSINESS_CONFLICT | 暂不使用（conflict 不是命令级错误） |
| 5 | EXTERNAL_ERROR | LLM API 调用失败（非降级场景） |
| 10 | UNEXPECTED | 未捕获异常 |

**实现策略:** 在 cmd_br_extract.py 各命令函数中捕获特定异常，映射到对应 exit code。

### 5.6 OPT-04: 单元测试

**目标模块:**
- `test_models.py` — BusinessRule.compute_hash() 确定性、to_dict/from_dict 往返
- `test_extractor.py` — Mock 源码提取正确 RuleType
- `test_conflict.py` — 阈值冲突 / 权限移除 / 状态机检测
- `test_snapshot.py` — 创建/diff/list
- `test_summarizer.py` — 模板降级输出正确字段

---

## 6. 风险与限制

| 风险 | 影响 | 缓解措施 | 来源 |
|------|------|----------|------|
| roam-code 上游 API 变更 | 高：_LAZY_COMMAND_MAP / _tool 装饰器签名变化 | 锁定 v13.x，升级前 diff 对比 | 架构分析 |
| tree-sitter Java grammar 覆盖不全 | 中：部分 Java 语法结构误报/漏报 | patterns.py 三级兜底（方法命名 + 注解） | patterns.py |
| LLM 语义归并错误 | 中：不同规则被错误合并 | merge_with 为软标记，不删除原规则；人工审核 | summarizer.py |
| P2040 项目规模未知 | 低：可能超 NFR-01 时间目标 | 增量提取 --update 缓解 | TBD-03 |

### 明确不引入的设计

| 设计 | 理由 |
|------|------|
| 独立 pip 包 | 与 roam-code 共享 DB 和索引，独立包增加集成复杂度 |
| FastAPI/Django Web 服务 | 无 Web 界面需求，CLI + MCP 已满足 AI 智能体和人工两种使用方式 |
| ORM (SQLAlchemy) | SQLite 表结构简单，直接 SQL 更可控、零学习成本 |
| 复杂的 Result Pattern | 当前规模下 Click 异常 + exit code 足够 |
| tqdm | Click 内置 progressbar 满足需求，避免新增依赖 |
| pytest-benchmark | OPT-01~02 变更量极小，无需基准测试框架 |

---

## 7. 追踪矩阵

| Spec AC | 测试目标 | 验证方式 |
|---------|----------|----------|
| AC-01 全量提取 | test_extractor_full_scan | 给定项目 → 正确规则数和 by_type 统计 |
| AC-02 增量提取 | test_extractor_incremental | 修改 3 文件 → 仅扫描 3 文件 |
| AC-03 LLM 增强 | test_summarizer_batch | 80 条规则 → 分 2 批调用 |
| AC-04 模板降级 | test_summarizer_fallback | 无 API key → 模板生成 domain/flow/desc |
| AC-05 图谱构建 | test_graph_build | 50 条规则 → 正确边统计 |
| AC-06 阈值冲突 | test_conflict_threshold | 同字段不同阈值 → critical 冲突 |
| AC-07 权限移除 | test_conflict_auth_removed | 基线有 auth 规则 → check 检出 |
| AC-08 状态机断裂 | test_conflict_deadend | workflow 死端 → 检出 |
| AC-09 快照 diff | test_snapshot_diff | 快照 #1 → #2 → 正确 +n/-m |
| AC-10 规则列表 | test_cli_list | --type validation → 仅输出该类型 |
| AC-11 规则详情 | test_cli_explain | rule_id → 基本信息 + 关联规则 |
| AC-12 JSON 输出 | test_cli_json | --json → stdout 为合法 JSON |
| AC-13 无索引熔断 | test_cli_no_index | 无 .roam/index.db → 错误提示 |
| AC-14 无规则 | test_cli_no_rules | 无匹配规则 → "No business rules detected" |
| AC-15 无冲突 | test_cli_no_conflicts | 规则间无冲突 → "No conflicts detected" |

---

**已生成 ./plan.md**

---

### 📋 核心小结

| 维度 | 结论 |
|------|------|
| 架构模式 | 对 roam-code 的**最小侵入式模块扩展** |
| 分层 | CLI → Domain → Infrastructure（Application 层轻度耦合，可接受） |
| 待优化 | 4 项：字典索引、进度条、Exit Code 细化、单元测试 |
| 预计总工时 | ~0.5 天（OPT-01~04） |
| 风险 | 低，核心引擎已完工，优化项为代码质量改进 |

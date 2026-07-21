# Business Rule Graph — 多根工作区支持 需求规格

> **项目:** business-rule-graph | **版本:** 1.1.0
> **日期:** 2026-07-21 | **状态:** 草稿
> **上游需求:** OBJ-07 多根工作区支持

---

## 术语表（增量）

| 术语 | 定义 |
|------|------|
| **工作区 (Workspace)** | VS Code `.code-workspace` 文件，包含 `folders` 数组，每个元素指定一个项目目录的相对路径 |
| **多根项目 (Multi-root)** | 一个工作区包含多个独立的项目目录，各项目可以有不同技术栈、不同 `.roam/index.db` |
| **跨项目报告 (Cross-project Report)** | 汇总所有项目的规则统计、冲突清单，标注每条规则/冲突的来源项目 |

---

## 业务目标

### OBJ-07: 多根工作区支持
解析 `.code-workspace` 文件，对其 `folders` 中所有项目目录统一执行规则提取、语义增强、图谱构建和冲突检测，产出跨项目统一报告。支持单文件指定（`--workspace`）和自动发现（当前目录向上搜索 `*.code-workspace`）两种方式。

---

## 核心场景

### SCN-04: 首次对工作区建立规则基线
- **角色:** 开发者 / AI 编码智能体
- **触发条件:** 拿到一个 `.code-workspace` 文件，需对所有子项目建立规则基线
- **前置条件:** 各子项目已分别运行 `roam init` 建立代码索引
- **主流程:**
  1. 执行 `roam business-rules extract --workspace "框架协议后端.code-workspace"`
  2. 系统解析工作区文件，获取 5 个项目路径（相对路径→绝对路径）
  3. 对每个项目依次执行 AST 规则提取
  4. 汇总输出：总规则数、各项目规则数、按 RuleType 分类
  5. 可选：对全部规则统一执行 summarize / graph / snapshot
- **关键异常:**
  - 某子项目无 `.roam/index.db` → 跳过该项目并输出警告
  - 工作区文件格式错误 → 输出错误信息并退出

### SCN-05: 跨项目冲突检测
- **角色:** 开发者 / AI 编码智能体
- **触发条件:** 工作区中多个项目有共享字段或业务流程
- **前置条件:** 已对各项目完成 extract + summarize
- **主流程:**
  1. 执行 `roam business-rules check --workspace "框架协议后端.code-workspace"`
  2. 系统加载所有项目的规则到统一上下文
  3. 执行跨项目阈值冲突检测、权限移除检测、状态机断裂检测
  4. 冲突报告中标注每条规则的来源项目
- **关键异常:**
  - 仅 1 个项目有规则 → 降级为单项目检测

---

## 功能需求

### REQ-21: 工作区文件解析
系统能解析 VS Code `.code-workspace` JSON 格式，提取 `folders[].path` 列表，将相对路径（相对于工作区文件所在目录）解析为绝对路径。

### REQ-22: `--workspace` 参数
所有 `business-rules-*` 命令支持 `--workspace <path>` 参数，指定 `.code-workspace` 文件路径。提供后，命令对工作区中所有项目执行操作。

### REQ-23: 自动发现工作区
当未指定 `--workspace` 时，系统在当前目录及父目录中搜索 `*.code-workspace` 文件。若找到恰好 1 个，自动使用；找到多个时列出候选让用户选择；未找到时降级为单项目模式。

### REQ-24: 跨项目规则汇总
`extract --workspace` 输出按项目分组的规则统计：每个项目的规则总数、RuleType 分布，以及工作区总计。

### REQ-25: 跨项目冲突检测
`check --workspace` 将所有项目的规则加载到统一上下文执行冲突检测，每条冲突标注来源项目。

### REQ-26: 向后兼容
不带 `--workspace` 时，行为与当前单项目模式完全一致，零回归。

---

## 验收标准

### AC-16: 工作区全量提取
- **Given** 工作区文件含 3 个 Java 项目，均已 `roam init`
- **When** 执行 `roam business-rules extract --workspace xxx.code-workspace`
- **Then** 系统依次扫描 3 个项目，输出每个项目的规则数和工作区总计

### AC-17: 子项目无索引时跳过
- **Given** 工作区中 1 个项目未 `roam init`
- **When** 执行 `roam business-rules extract --workspace xxx.code-workspace`
- **Then** 系统输出该项目的跳过警告，继续处理其余项目

### AC-18: 跨项目冲突检测
- **Given** 两个项目中有引用相同字段 `total` 且阈值不同的规则
- **When** 执行 `roam business-rules check --workspace xxx.code-workspace`
- **Then** 系统检测到跨项目阈值冲突，冲突描述中标注双方来源项目

### AC-19: 自动发现工作区
- **Given** 当前目录或其父目录存在恰好 1 个 `.code-workspace` 文件
- **When** 执行 `roam business-rules extract`（不带 --workspace）
- **Then** 系统自动使用该工作区文件

### AC-20: 向后兼容
- **Given** 当前目录及父目录均无 `.code-workspace` 文件
- **When** 执行 `roam business-rules extract`（不带 --workspace）
- **Then** 行为与当前单项目模式完全一致

---

## 变更记录

| 版本 | 日期 | 变更摘要 |
|------|------|----------|
| 1.1.0 | 2026-07-21 | 新增 OBJ-07 多根工作区支持，SCN-04/05，REQ-21~26，AC-16~20 |

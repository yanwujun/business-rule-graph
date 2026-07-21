# Business Rule Graph — 多根工作区 任务清单

> **上游:** [spec-workspace.md](./spec-workspace.md) · [plan-workspace.md](./plan-workspace.md)
> **日期:** 2026-07-21 | **总任务:** 8 | **预计:** ~2h

---

## 任务依赖图

```
Phase 1: workspace 核心模块
  T101 [P] (workspace 单元测试) ──► T102 (实现 workspace.py)

Phase 2: 命令改造
  T103 (extract --workspace 测试) ──► T104 (实现 extract --workspace)
  T105 (check --workspace 测试)   ──► T106 (实现 check --workspace)

Phase 3: 收尾
  T107 (graph/snapshot/diff 接入)  [P]
  T108 (P2040 工作区实测)
```

---

## Phase 1: workspace 核心模块

- [ ] **T101** [P] [REQ-21] [REQ-23] [AC-19] [Phase 1] [Size: S]
  **编写 `test_workspace.py`：parse_workspace / discover_workspace / resolve_workspace。**
  依赖：无。
  文件：`tests/test_workspace.py`（新建）。
  验证：`uv run pytest tests/test_workspace.py -v` 通过。
  完成判据：
  - `test_parse_valid_workspace`: 解析合法 JSON → 正确数量的项目 + 路径
  - `test_parse_invalid_json`: 非法 JSON → 抛出明确异常
  - `test_parse_relative_paths_resolved`: 相对路径 → 解析为绝对路径
  - `test_discover_finds_workspace`: 临时目录创建 `.code-workspace` → 发现
  - `test_discover_none_found`: 无工作区文件 → 返回 None
  - `test_resolve_explicit_path`: 显式指定 → 不触发自动发现
  来源：`spec-workspace.md AC-19, AC-20`

- [ ] **T102** [REQ-21] [REQ-23] [Phase 1] [Size: M]
  **实现 `workspace.py`：`WorkspaceProject` dataclass + `parse_workspace` + `discover_workspace` + `resolve_workspace`。**
  依赖：T101。
  文件：`src/roam/business_rules/workspace.py`（新建）。
  验证：`uv run pytest tests/test_workspace.py -v` 全部通过。
  完成判据：T101 所有测试通过。
  来源：`plan-workspace.md §2.3`

---

## Phase 2: 命令改造

- [ ] **T103** [REQ-22] [REQ-24] [AC-16] [AC-17] [Phase 2] [Size: S]
  **编写 `test_br_workspace_extract.py`：多项目 extract + 子项目跳过。**
  依赖：T102。
  文件：`tests/test_br_workspace_extract.py`（新建）。
  验证：`uv run pytest tests/test_br_workspace_extract.py -v` 通过。
  完成判据：
  - 创建临时工作区（2 个模拟项目，各有 business_rules 表），验证 extract 输出含两个项目的规则统计
  - 1 个项目无 index.db → 跳过警告，另一项目正常提取
  来源：`spec-workspace.md AC-16, AC-17`

- [ ] **T104** [REQ-22] [REQ-24] [Phase 2] [Size: M]
  **改造 `cmd_br_extract` + `cmd_br_list` + `cmd_br_explain`：支持 `--workspace`。**
  依赖：T103。
  文件：`src/roam/business_rules/commands/cmd_br_extract.py`。
  变更：
  - `cmd_br_extract` 新增 `--workspace` option
  - 实现 `_extract_workspace()` 遍历项目
  - 实现 `_print_workspace_summary()` 汇总输出
  验证：`uv run pytest tests/test_br_workspace_extract.py -v` 全部通过。
  完成判据：T103 所有测试通过。
  来源：`plan-workspace.md §2.4`

- [ ] **T105** [REQ-25] [AC-18] [Phase 2] [Size: S]
  **编写 `test_br_workspace_check.py`：跨项目冲突检测。**
  依赖：T102。
  文件：`tests/test_br_workspace_check.py`（新建）。
  验证：`uv run pytest tests/test_br_workspace_check.py -v` 通过。
  完成判据：
  - 两个项目各有引用字段 `total` 且阈值不同的规则 → check --workspace 检测到跨项目冲突
  - 冲突描述含项目来源标注
  来源：`spec-workspace.md AC-18`

- [ ] **T106** [REQ-25] [Phase 2] [Size: M]
  **改造 `cmd_br_check` + `cmd_br_graph`：支持 `--workspace`。**
  依赖：T105。
  文件：`src/roam/business_rules/commands/cmd_br_extract.py`。
  变更：
  - `cmd_br_check` 新增 `--workspace` option，加载所有项目规则到统一上下文
  - `cmd_br_graph` 新增 `--workspace` option，跨项目构建边
  验证：`uv run pytest tests/test_br_workspace_check.py -v` 全部通过。
  完成判据：T105 所有测试通过。
  来源：`plan-workspace.md §3.2`

---

## Phase 3: 收尾

- [ ] **T107** [P] [REQ-22] [Phase 3] [Size: S]
  **改造 `cmd_br_snapshot` + `cmd_br_diff` + `cmd_br_summarize`：支持 `--workspace`。**
  依赖：T102。
  文件：`src/roam/business_rules/commands/cmd_br_extract.py`。
  变更：三个命令各新增 `--workspace` option，遍历项目执行。
  验证：手动测试。
  完成判据：三个命令均接受 `--workspace` 且不报错。
  来源：`plan-workspace.md §3.3`

- [ ] **T108** [Phase 3] [Size: S]
  **P2040 工作区实测。**
  依赖：T104, T106, T107。
  验证：
  ```bash
  roam business-rules extract --workspace "/mnt/d/项目/svn/P2040直采与框架协议/框架协议后端.code-workspace"
  ```
  完成判据：输出 5 个项目的规则统计，2 个 Java 项目有规则数 > 0。
  来源：`plan-workspace.md §4`

---

## 任务统计

| Phase | 任务数 | 预计 |
|-------|--------|------|
| Phase 1 | 2 | 45min |
| Phase 2 | 4 | 50min |
| Phase 3 | 2 | 25min |
| **合计** | **8** | **~2h** |

## 可并行

| 组 | 任务 |
|----|------|
| 组1 | T101 (写测试时可先不依赖 T102) |
| 组2 | T103, T105 (同依赖 T102) |
| 组3 | T107 独立于 T103-T106 |

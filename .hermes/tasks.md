# Business Rule Graph — 任务清单

> **项目:** business-rule-graph | **上游:** [spec.md](./spec.md) · [plan.md](./plan.md)
> **日期:** 2026-07-21 | **总任务:** 12 | **预计总工时:** ~3 小时

---

## 任务依赖图

```
Phase 1: 准备与审查
  T001 (审查当前代码状态)
    │
    ├──► T002 (审查 _status_deadend 完整度) [P]
    │
    ▼
Phase 2: 代码优化
  T003 [AC-03] (写 _find_rule 测试) ──► T004 [AC-03] (实现字典索引)
  T005 [AC-01] (写 progressbar 测试) ──► T006 [AC-01] (实现 progressbar)

Phase 3: 质量加强
  T007 [AC-12] (写 Exit Code 测试) ──► T008 [AC-12] (实现 Exit Code 细化)
  T009 [AC-06~08] (conflict 单元测试)
  T010 [AC-09] (snapshot 单元测试)
  T011 [AC-03~04] (summarizer 单元测试)

Phase 4: 验证与收尾
  T012 (全链路 smoke test)
```

---

## Phase 1: 准备与审查

- [ ] **T001** [ARCH-01] [Phase 1] [Size: S]
  **审查 `_find_rule` 当前实现，确认是否已优化。**
  依赖：无。
  文件：`src/roam/business_rules/summarizer.py`。
  验证：阅读 `_merge_results` 方法，确认是 O(n×m) 线性查找还是 O(1) 字典索引。
  完成判据：产出审查结论（"已优化"或"待优化，当前为线性查找"），若待优化则 T004 执行。
  来源：`plan.md §5.3 OPT-01`; `OPTIMIZATION.md #5`

- [ ] **T002** [P] [REQ-13] [AC-08] [Phase 1] [Size: S]
  **审查 `_status_deadend` 实现完整度，确认是否覆盖死端/孤立入口/不可达三种检测。**
  依赖：无（与 T001 并行）。
  文件：`src/roam/business_rules/conflict.py`。
  验证：阅读 `_status_deadend()` 方法体，检查是否实现了三种检测逻辑。
  完成判据：产出审查结论和覆盖率矩阵（死端/孤立入口/不可达 各 ✅/❌）。若缺检测则标记为后续任务。
  来源：`spec.md TBD-01`; `plan.md §1.2`

---

## Phase 2: 代码优化

### OPT-01: _find_rule 字典索引 → T003 + T004

- [ ] **T003** [REQ-06] [AC-03] [Phase 2] [Size: S]
  **编写 `test__merge_results_performance` 测试：验证 200 条规则合并时字典索引的正确性。**
  依赖：T001（确认当前为线性查找）。
  文件：`tests/test_summarizer_merge.py`（新建）。
  验证：`pytest tests/test_summarizer_merge.py -v` 通过。
  完成判据：
  - 测试构造 200 条 rules + 200 条 LLM results，验证每条 rule 的 domain/flow/description 被正确合并
  - 覆盖 results 中缺少某 rule_id 的边界情况
  来源：`spec.md AC-03`; `plan.md §5.3`

- [ ] **T004** [REQ-06] [AC-03] [Phase 2] [Size: S]
  **将 `_merge_results` 改为字典索引（O(n×m) → O(n+m)）。**
  依赖：T003。
  文件：`src/roam/business_rules/summarizer.py`。
  变更：
  ```python
  # Before: for r in rules: for llm in results: if llm["rule_id"] == r["rule_id"]: ...
  # After:
  by_id = {r["rule_id"]: r for r in results}
  for rule in rules:
      llm = by_id.get(rule["rule_id"])
      if llm:
          rule.update({k: v for k, v in llm.items() if k != "rule_id"})
  ```
  验证：`pytest tests/test_summarizer_merge.py -v` 全部通过。
  完成判据：测试通过，200 条规则合并时间从 O(n×m) 降至 O(n+m)。
  来源：`plan.md §5.3`; `OPTIMIZATION.md #5`

### OPT-02: 进度条 → T005 + T006

- [ ] **T005** [REQ-01] [AC-01] [Phase 2] [Size: S]
  **编写 extractor 进度条行为测试：验证 progressbar 输出到 stderr 且不污染 --json stdout。**
  依赖：无。
  文件：`tests/test_extractor_progress.py`（新建）。
  验证：`pytest tests/test_extractor_progress.py -v` 通过。
  完成判据：
  - 测试执行 extract（含进度条），捕获 stdout/stderr
  - 断言 stderr 包含进度输出（如 "Extracting business rules"）
  - 断言 stdout 在 --json 模式下为合法 JSON，不含进度文本
  来源：`spec.md AC-01, AC-12`; `plan.md §5.4`

- [ ] **T006** [REQ-01] [AC-01] [Phase 2] [Size: S]
  **在 `extract_from_db` 中添加 `click.progressbar` 包装文件迭代。**
  依赖：T005。
  文件：`src/roam/business_rules/extractor.py`。
  变更：
  ```python
  from click import progressbar
  
  for file_rel in progressbar(files_to_scan, label="Extracting business rules"):
  ```
  验证：`pytest tests/test_extractor_progress.py -v` 全部通过。
  完成判据：测试通过，progressbar 仅在 stderr 输出。
  来源：`plan.md §5.4`; `OPTIMIZATION.md #6`

---

## Phase 3: 质量加强

### OPT-03: Exit Code 细化 → T007 + T008

- [ ] **T007** [REQ-18] [AC-12] [AC-13] [Phase 3] [Size: S]
  **编写 CLI Exit Code 黑盒测试：覆盖无索引(exit 1)、JSON 模式(exit 0)、规则不存在(exit 1)。**
  依赖：无。
  文件：`tests/test_br_cli_exit_codes.py`（新建）。
  验证：`pytest tests/test_br_cli_exit_codes.py -v` 通过。
  完成判据：
  - 测试 `business-rules-extract` 无索引场景 → exit_code != 0, stderr 含 "No index found"
  - 测试 `business-rules-explain nonexistent-id` → exit_code != 0
  - 测试 `business-rules-list --json` 正常场景 → exit_code == 0, stdout 合法 JSON
  来源：`spec.md AC-12, AC-13`; `plan.md §5.5`

- [ ] **T008** [REQ-18] [AC-12] [AC-13] [Phase 3] [Size: S]
  **在 `cmd_br_extract.py` 各命令中添加明确的 exit code 返回（替换隐式 return）。**
  依赖：T007。
  文件：`src/roam/business_rules/commands/cmd_br_extract.py`。
  变更：在无索引检测处添加 `raise SystemExit(1)` 或 `ctx.exit(1)`，确保非零退出码。
  验证：`pytest tests/test_br_cli_exit_codes.py -v` 全部通过。
  完成判据：测试全部通过，所有错误场景返回非零 exit code。
  来源：`plan.md §5.5`

### OPT-04: 单元测试 → T009 + T010 + T011

- [ ] **T009** [P] [REQ-11] [REQ-12] [REQ-13] [AC-06] [AC-07] [AC-08] [Phase 3] [Size: M]
  **编写 `ConflictDetector` 单元测试：阈值冲突 / 权限移除 / 状态机断裂。**
  依赖：T002（确认 _status_deadend 完整度）。
  文件：`tests/test_conflict_detector.py`（新建）。
  验证：`pytest tests/test_conflict_detector.py -v` 通过。
  完成判据：
  - `test_threshold_mismatch`: 同字段 total 阈值 100 vs 50 → 检出 critical 冲突
  - `test_auth_removed`: 基线有 auth 规则，当前无 → 检出
  - `test_status_deadend`: workflow 规则 DRAFT→SUBMITTED→APPROVED（死端）→ 检出
  - 至少 3 个测试用例，覆盖 spec.md AC-06/07/08
  来源：`spec.md AC-06, AC-07, AC-08`; `plan.md §5.6`

- [ ] **T010** [P] [REQ-14] [REQ-15] [AC-09] [Phase 3] [Size: S]
  **编写 `RuleSnapshot` 单元测试：创建快照、diff、列表。**
  依赖：无（与 T009 并行）。
  文件：`tests/test_snapshot.py`（新建）。
  验证：`pytest tests/test_snapshot.py -v` 通过。
  完成判据：
  - `test_create_snapshot`: 创建快照后查询 business_rule_snapshots 表确认记录
  - `test_diff`: 快照 #1(100条) vs #2(103条) → added=3, removed=0
  - 使用临时 SQLite 文件，不污染真实 DB
  来源：`spec.md AC-09`; `plan.md §5.6`

- [ ] **T011** [P] [REQ-06] [REQ-07] [AC-03] [AC-04] [Phase 3] [Size: S]
  **编写 `RuleSummarizer` 单元测试：模板降级输出正确字段。**
  依赖：无（与 T009/T010 并行）。
  文件：`tests/test_summarizer_fallback.py`（新建）。
  验证：`pytest tests/test_summarizer_fallback.py -v` 通过。
  完成判据：
  - `test_template_fallback`: 无 API key 时 `_template_fallback()` 返回的每条规则含 domain/flow/description 且非空
  - `test_fallback_domain_from_package`: 包名含 "order" → domain="订单管理"
  - `test_fallback_flow_from_class`: 类名含 "Controller" → flow 非空
  来源：`spec.md AC-03, AC-04`; `plan.md §5.6`

---

## Phase 4: 验证与收尾

- [ ] **T012** [Phase 4] [Size: S]
  **全链路 smoke test：在测试项目上运行完整管线。**
  依赖：T004, T006, T008（所有优化完成后）。
  验证：
  ```bash
  cd /home/administrator/business-rule-graph
  python -m pytest tests/ -v --tb=short  # 全部测试通过
  ```
  完成判据：
  - 所有新增测试（T003/T005/T007/T009/T010/T011）通过
  - 已有的 1400+ roam-code 测试无回归（可选，耗时长）
  - `roam business-rules --help` 列出 8 个命令
  来源：`plan.md §5.1 Phase M2`

---

## 任务统计

| Phase | 任务数 | 预计工时 | 说明 |
|-------|--------|----------|------|
| Phase 1 | 2 | 0.5h | 代码审查 |
| Phase 2 | 4 | 1.0h | 字典索引 + 进度条 |
| Phase 3 | 5 | 1.0h | Exit Code + 单元测试 |
| Phase 4 | 1 | 0.5h | Smoke test |
| **合计** | **12** | **~3h** | |

## 可并行任务

| 并行组 | 任务 |
|--------|------|
| 组1 | T001 ↔ T002 |
| 组2 | T005（独立于 T003/T004） |
| 组3 | T007（独立于 T005/T006） |
| 组4 | T009 ↔ T010 ↔ T011（三个测试文件互不依赖） |

## 追踪矩阵

| Spec AC | 对应任务 |
|---------|----------|
| AC-01 全量提取 | T005, T006 |
| AC-03 LLM 增强 | T003, T004, T011 |
| AC-04 模板降级 | T011 |
| AC-06 阈值冲突 | T009 |
| AC-07 权限移除 | T009 |
| AC-08 状态机断裂 | T002, T009 |
| AC-09 快照 diff | T010 |
| AC-12 JSON 输出 | T005, T007, T008 |
| AC-13 无索引熔断 | T007, T008 |

# Business Rule Graph — 多根工作区 技术方案

> **上游:** [spec-workspace.md](./spec-workspace.md) | **日期:** 2026-07-21

---

## 1. 架构决策

| # | 决策 | 选择 | 理由 | 来源 |
|---|------|------|------|------|
| ADR-09 | 多项目数据模型 | 每项目独立 `.roam/index.db`，命令层聚合 | 不破坏 roam-code 单项目假设；各项目 DB 独立可并行操作 | OBJ-07 |
| ADR-10 | 工作区解析位置 | 新增 `workspace.py` 模块 | 复用逻辑（extract/check/graph 都需解析工作区） | REQ-21 |
| ADR-11 | `--workspace` 注入方式 | Click callback 在命令执行前设置 `ctx.obj["workspace_projects"]` | 不改各命令函数签名，兼容现有代码 | REQ-22 |
| ADR-12 | 自动发现策略 | 从 `cwd` 向上搜索，找到多个时列表提示；恰好 1 个自动使用 | 与 VS Code 行为一致 | REQ-23 |
| ADR-13 | 跨项目聚合 | 每个项目的规则加载后合并为统一列表，规则 `rule_id` 加项目名前缀 | 避免 rule_id 冲突；可追溯来源 | REQ-25 |

---

## 2. 模块设计

### 2.1 新增文件

```
src/roam/business_rules/
├── workspace.py          ← 新增：工作区解析 + 自动发现 + 项目列表
```

### 2.2 修改文件

```
src/roam/business_rules/commands/cmd_br_extract.py   ← 新增 --workspace 参数
src/roam/cli.py                                       ← (无改动，lazy-load 已支持)
```

### 2.3 `workspace.py` 设计

```python
@dataclass
class WorkspaceProject:
    """工作区中的一个项目"""
    name: str           # 目录名（如 "xcj-trade"）
    root: Path          # 绝对路径
    db_path: Path       # .roam/index.db 路径
    has_index: bool     # 是否已 roam init

def parse_workspace(ws_path: str | Path) -> list[WorkspaceProject]:
    """解析 .code-workspace → 项目列表"""

def discover_workspace(start_dir: str | Path = ".") -> Path | None:
    """从 start_dir 向上搜索 *.code-workspace"""

def resolve_workspace(ws_path: str | None = None) -> list[WorkspaceProject]:
    """统一入口: --workspace > 自动发现 > 单项目降级"""
```

### 2.4 命令改造模式

每个命令改造遵循相同模式（以 extract 为例）：

```python
# Before:
@click.command("business-rules-extract")
def cmd_br_extract(update, as_json, project_root):
    root = project_root or _root()
    db_path = f"{root}/.roam/index.db"
    # ... 单项目处理

# After:
@click.command("business-rules-extract")
@click.option("--workspace", default=None, help=".code-workspace file path")
def cmd_br_extract(update, as_json, project_root, workspace):
    projects = resolve_workspace(workspace)
    all_results = []
    for proj in projects:
        result = _extract_one(proj, update)
        all_results.append(result)
    _print_workspace_summary(all_results, as_json)
```

---

## 3. 输出格式

### 3.1 extract 输出（多项目）

```text
Workspace: 框架协议后端 (5 projects)
─────────────────────────────────────────
  xcj-trade        [Java]  312 rules (validation:142, auth:56, ...)
  xcj-ezc          [Java]  198 rules (validation:89, workflow:45, ...)
  kjxy             [Vue]     0 business rules (not a Java project)
  kjxy-backstage   [Vue]     0 business rules (not a Java project)
  web              [Web]     0 business rules (not a Java project)
─────────────────────────────────────────
  Total: 510 rules across 2 Java projects
```

### 3.2 check 输出（多项目）

```text
[CRITICAL] threshold_mismatch: 字段 'total' 阈值不一致
  xcj-trade/OrderServiceImpl.java:145: >=100
  xcj-ezc/PaymentService.java:89: >=50
```

---

## 4. 实施策略

| 阶段 | 内容 | 文件 | 预计 |
|------|------|------|------|
| M3.1 | `workspace.py` 解析 + 自动发现 + 测试 | workspace.py | 30min |
| M3.2 | `extract --workspace` 改造 | cmd_br_extract.py | 20min |
| M3.3 | `check/graph/snapshot/diff --workspace` 改造 | cmd_br_extract.py | 30min |
| M3.4 | 集成测试 + 对 P2040 工作区实测 | tests/ | 30min |
| **合计** | | | **~2h** |

---

## 5. 风险

| 风险 | 缓解 |
|------|------|
| 多项目 rule_id 冲突 | ADR-13: 前缀 `{project_name}/` |
| 不同项目 DB schema 版本不一致 | 依赖 roam-code 版本锁定 |
| 非 Java 项目无规则提取 | 静默跳过（输出 0 rules），不报错 |

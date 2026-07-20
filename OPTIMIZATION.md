# 剩余优化项 — 执行计划

## 🟡 功能缺项（3项）

### 1. `roam business-rules list` — 列出已提取规则

```
roam business-rules list                    # 全部
roam business-rules list --type validation  # 按类型筛选
roam business-rules list --domain 订单管理   # 按域筛选
roam business-rules list --json             # JSON输出
```

**实现**: 在 `cmd_br_extract.py` 新增 `cmd_br_list`，查 `business_rules` 表，输出表格:
```
rule_id                               type         domain     description
OrderService.java:145:if-throw        validation   订单管理    订单金额不能低于100元
PaymentService.java:89:if-throw       validation   支付管理    支付金额不能低于100元
```

### 2. `roam business-rules explain <rule-id>` — 单条规则详情

```
roam business-rules explain OrderService.java:145:if-throw
```

**输出**:
```
Rule: OrderService.java:145:if-throw
Type: validation
Domain: 订单管理
Description: 订单金额不能低于100元
Source: OrderService.java:145
Params: {"exception_message":"订单金额不能低于100元"}
Extraction: tree_sitter_if_throw

Related rules (3):
  → PaymentService.java:89:if-throw  [same_field]
  → OrderAuditService.java:23:status-check  [same_flow]
```

**实现**: 新方法 `cmd_br_explain`，查 `business_rules` + `business_rule_edges`，导出关联规则。

### 3. `_status_deadend()` — 状态机断裂检测

**算法**:
```
1. 收集所有 WORKFLOW 规则的 status_value + enum_values
2. 构建状态转移图: {(from_status, to_status), ...}
3. 检测:
   a. 只进不出 → 死端 (dead end state)
   b. 只出不进 → 孤立入口 (orphan entry)
   c. 不可达状态 → 枚举定义但无规则引用
```

**实现**: `conflict.py` 新增 `_status_deadend()`，在 `detect()` 中调用。

---

## 🟢 代码质量（3项）

### 4. 共享 DataLoader — `graph.py` + `conflict.py` 去重

两个文件都重复「加载所有 business_rules + 解析 params JSON」的逻辑。

**方案**: 新增 `src/roam/business_rules/loader.py`:
```python
def load_rules(db_path: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM business_rules").fetchall()
    rules = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d["params"]) if isinstance(d["params"], str) else d["params"]
        except:
            d["params"] = {}
        rules.append(d)
    return rules
```
graph.py 和 conflict.py 改为 `from .loader import load_rules`。

### 5. `summarizer.py` `_find_rule` — 字典索引

当前 O(n×m) 线性查找 → 改为 dict 索引:
```python
def _merge_results(self, rules, results):
    by_id = {r["rule_id"]: r for r in results}
    for r in rules:
        llm = by_id.get(r["rule_id"])
        if llm:
            r.update(...)
```

### 6. 进度条 — `extractor.py` 大项目

`extract_from_db` 添加 tqdm 进度条（`pip install tqdm` 或简单的 `click.progressbar`）:
```python
from click import progressbar

for file_rel in progressbar(files_to_scan, label="Extracting"):
    ...
```

---

## 预计工时

| 项 | 文件 | 行数 | 预计 |
|----|------|------|------|
| list 命令 | cmd_br_extract.py + cli.py | ~40行 | 20分钟 |
| explain 命令 | cmd_br_extract.py + cli.py | ~50行 | 30分钟 |
| _status_deadend | conflict.py | ~80行 | 1小时 |
| DataLoader | loader.py + graph.py + conflict.py | ~30行 | 15分钟 |
| _find_rule 索引 | summarizer.py | ~10行 | 10分钟 |
| 进度条 | extractor.py | ~5行 | 5分钟 |

**总计: ~2-3小时**

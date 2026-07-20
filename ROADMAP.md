# Business Rule Graph

> https://github.com/yanwujun/business-rule-graph
> 基座: roam-code v13 | 原则: AST 确定性引擎 + LLM 语义引擎，双引擎驱动
> SVN 支持: roam-code 文件 mtime 检测，不依赖 git

## 项目定位

基于 roam-code 改造，吸收 understand-anything 业务规则能力，解决：

> **AI 修改代码后，自动判断是否引入了业务规则冲突。**

## 架构

```
AST 引擎 (extractor.py)          LLM 引擎 (summarizer.py)
    │                                │
    ├── tree-sitter 扫 if-throw      ├── domain/flow 语义分类
    ├── 方法命名约定                  ├── description 自然语言
    ├── 注解兜底                      ├── 语义归并(同规则合并)
    └── 参数提取(精确,零成本)         └── 冲突描述(业务语言)
            │                                │
            └──────────┬─────────────────────┘
                       ▼
              规则图谱 (graph.py)
          same_field / same_flow / conflicts_with
                       │
                       ▼
              冲突检测 (conflict.py)
          阈值冲突 / 权限移除 / 状态机断裂
                       │
                       ▼
              版本快照 (snapshot.py)
              创建基线 → 改代码 → diff → 冲突报告
```

## understand-anything → 本项目 吸收

| 来源 | 吸收到 |
|------|--------|
| `diff-to-business-rules` 8种规则分类 | `patterns.py` RuleType |
| `diff-to-business-rules` 规则字段结构 | `models.py` BusinessRule |
| `understand-domain` domain/flow 概念 | summarizer.py LLM语义 |
| `understand` knowledge-graph.json | → 废弃，roam-code SQLite 替代 |

## 模块清单

```
src/roam/business_rules/
├── models.py         8种规则类型 + dataclass
├── patterns.py       三级提取 (tree-sitter > 方法命名 > 注解)
├── extractor.py      AST 确定性引擎
├── summarizer.py     LLM 语义引擎
├── graph.py          规则图谱
├── conflict.py       冲突检测
├── snapshot.py       版本快照
└── commands/cmd_br_extract.py  6个CLI命令
```

## 使用方式

```bash
roam init                              # 建代码索引
roam business-rules extract            # AST 提取规则
roam business-rules summarize          # LLM 语义增强
roam business-rules graph              # 构建图谱
roam business-rules snapshot --label "基线"  # 版本快照
# ... 改代码 ...
roam business-rules extract --update   # 增量提取
roam business-rules check              # 冲突检测
roam business-rules diff               # 对比变更
```

## 详细实施计划

→ **IMPLEMENTATION.md** — 含全部代码实现、DB schema、冲突算法

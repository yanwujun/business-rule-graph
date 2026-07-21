# OBJ-08: 前端规则提取 — 需求规格（精简版）

> **目标:** 对 React/TypeScript 前端项目提取业务规则，补全工作区覆盖

## OBJ-08: 前端规则提取
对 React + Ant Design + TypeScript 前端项目，自动提取表单校验规则、状态枚举定义、自定义 validator，支持多根工作区。

## REQ

| REQ | 内容 | 前端模式 |
|-----|------|----------|
| REQ-27 | 表单校验提取 | `rules: [{ required: true, message: '...' }]` |
| REQ-28 | 数值约束提取 | `rules: [{ max: 200, message: '...' }]`、`min:`、`pattern:` |
| REQ-29 | 状态枚举提取 | `enum XxxStatus { DRAFT, SUBMITTED, ... }` |
| REQ-30 | 自定义 validator | `rules: [{ validator: validateXxx }]` |
| REQ-31 | 多语言支持 | `.tsx` + `.ts` 文件 |

## AC

- **AC-21**: kjxy 项目检出 rules > 0
- **AC-22**: 检测到 `required: true` → type=validation
- **AC-23**: 检测到 `max: 200` → 记录数值约束
- **AC-24**: 检测到 `enum XxxStatus` → type=workflow

## 实施

- 新增 `src/roam/business_rules/frontend_extractor.py`：正则扫描 .tsx/.ts 文件
- 扩 `_get_files_from_db` WHERE language IN ('typescript','tsx')
- 无需 tree-sitter（正则匹配 antd rules 模式足够精准）

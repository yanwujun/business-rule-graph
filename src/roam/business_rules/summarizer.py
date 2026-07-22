"""LLM 语义引擎 — 给 AST 规则补充业务含义

双引擎架构之语义引擎:
  ✅ domain 语义校准（不靠包名猜）
  ✅ flow 语义校准（不靠类名猜）
  ✅ description 自然语言生成
  ✅ 语义归并（同规则不同写法 → 合并）
  ❌ 不提取参数 — 参数由 AST 确定

调用策略: 一次 extract 后做一次批量 summarize，不是每个文件都调。
无 API key 时降级为模板生成。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是政府采购系统的业务分析师。你会收到一批从 Java 代码中自动提取的业务规则。
你的任务是对每条规则补充业务语义。

输入格式: JSON 数组 "rules"，每条规则包含:
- rule_id: 唯一标识（不可修改）
- source_file: 源文件路径
- source_line: 行号
- rule_type: validation/authorization/workflow/calculation/data_integrity/process/configuration/integration
- exception_message: 异常消息（如有 — 这是最可靠的语义来源）
- status_value: 状态值（如有）
- enum_values: 枚举值列表（如有）
- extraction: 提取方式标记

输出格式: JSON 对象 {"rules": [...]}，对每条输入规则输出:
- rule_id: 保持原样
- domain: 业务域（订单管理/供应商管理/商品管理/支付管理/审核管理/合同管理/框架协议/直采商城/系统管理）
- flow: 业务流程（下单/支付/审核/发货/签约/退款/同步/提交/审批）
- description: 自然语言业务描述（30字以内，用业务用语）
- severity: critical/high/medium/low
- merge_with: 如果与输入中另一条规则是同一规则的不同写法，填对方的 rule_id；否则 null

关键规则:
- description 必须用业务语言，不要复制代码
- domain 根据业务含义分类，不要依赖包名
- 发现同一业务含义的不同写法应标记 merge_with（如 total>=100 和 amount<100则抛异常）
- 状态枚举要描述业务场景（如 "订单从草稿到已提交"）
- 不要修改 rule_id / source_file / source_line
"""


class RuleSummarizer:
    """批量 LLM 语义化 — 一次调用处理所有规则"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
        )
        self.base_url = base_url or os.environ.get(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1",
        )
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4.1-mini")

    def summarize(
        self, rules: list[dict], batch_size: int = 50
    ) -> list[dict]:
        """批量语义化，每批最多 50 条"""
        if not self.api_key:
            logger.info("No API key — using template fallback")
            return self._template_fallback(rules)

        all_results = []
        total = len(rules)
        for i in range(0, total, batch_size):
            batch = rules[i : i + batch_size]
            logger.info(
                "Summarizing batch %d/%d (%d rules)",
                i // batch_size + 1,
                (total + batch_size - 1) // batch_size,
                len(batch),
            )
            result = self._call_llm(batch)
            all_results.extend(result)
        return all_results

    def export_for_agent(self, rules: list[dict], batch_size: int = 50) -> str:
        """导出为 Agent 可处理的 prompt JSON（用于 --agent 模式）

        输出结构:
        {
          "system": "<SYSTEM_PROMPT>",
          "batches": [
            {"batch": 1, "rules": [...]},
            ...
          ],
          "instruction": "对每个 batch 的 rules 调用 LLM，输出 {rules: [...]}，写回文件后执行 --agent-apply"
        }
        """
        slim_batches = []
        total = len(rules)
        n_batches = (total + batch_size - 1) // batch_size

        for i in range(0, total, batch_size):
            batch = rules[i : i + batch_size]
            slim = []
            for r in batch:
                slim.append({
                    "rule_id": r.get("rule_id", ""),
                    "source_file": r.get("source_file", ""),
                    "source_line": r.get("source_line", 0),
                    "rule_type": r.get("rule_type", "validation"),
                    "exception_message": r.get("exception_message", "") or (
                        (r.get("params", {}) or {}).get("exception_message", "")
                    ),
                    "status_value": r.get("status_value", "") or (
                        (r.get("params", {}) or {}).get("status_value", "")
                    ),
                    "enum_values": r.get("enum_values", []) or (
                        (r.get("params", {}) or {}).get("enum_values", [])
                    ),
                    "extraction": r.get("extraction", ""),
                })
            slim_batches.append({
                "batch": i // batch_size + 1,
                "total_batches": n_batches,
                "rules": slim,
            })

        return json.dumps({
            "system": SYSTEM_PROMPT.strip(),
            "batches": slim_batches,
            "instruction": (
                "对每个 batch，用 system prompt 指引 LLM 输出 JSON: "
                '{"rules": [{"rule_id":"...","domain":"...","flow":"...",'
                '"description":"...","severity":"...","merge_with":null}, ...]}。'
                "将所有 batch 的结果合并到一个 JSON 文件 "
                '(格式: {"rules": [...]})，'
                "然后执行 roam business-rules-summarize --agent-apply <文件路径>"
            ),
        }, ensure_ascii=False, indent=2)

    def apply_agent_result(self, rules: list[dict], response_path: str) -> list[dict]:
        """读取 Agent 返回的 LLM 结果文件，合并回规则（用于 --agent-apply 模式）"""
        with open(response_path, "r", encoding="utf-8") as f:
            response = json.load(f)

        result_rules = response.get("rules", [])
        if not result_rules:
            raise ValueError(f"No 'rules' found in agent response: {response_path}")

        logger.info("Applying %d agent-enriched rules to %d original rules",
                     len(result_rules), len(rules))
        return self._merge_results(rules, result_rules)

    def _call_llm(self, rules: list[dict]) -> list[dict]:
        """调用 LLM API"""
        import requests

        # 精简输入：只传 LLM 需要的字段
        slim = []
        for r in rules:
            slim.append({
                "rule_id": r.get("rule_id", ""),
                "source_file": r.get("source_file", ""),
                "source_line": r.get("source_line", 0),
                "rule_type": r.get("rule_type", "validation"),
                "exception_message": r.get("exception_message", ""),
                "status_value": r.get("status_value", ""),
                "enum_values": r.get("enum_values", []),
                "extraction": r.get("extraction", ""),
            })

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"rules": slim},
                                ensure_ascii=False,
                                indent=2,
                            ),
                        },
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=120,
            )

            if resp.status_code != 200:
                logger.warning(
                    "LLM API returned %d — falling back to template",
                    resp.status_code,
                )
                return self._template_fallback(rules)

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            result_rules = result.get("rules", [])

            # 合并 LLM 输出回原始规则 — 使用 O(1) _merge_results 替代 O(n*m) _find_rule
            return self._merge_results(rules, result_rules)

        except Exception as e:
            logger.warning("LLM call failed: %s — falling back to template", e)
            return self._template_fallback(rules)

    def _merge_results(self, rules: list[dict], results: list[dict]) -> list[dict]:
        """O(1) 索引合并 — 替代 O(n*m) find_rule"""
        by_id = {r["rule_id"]: r for r in results if r.get("rule_id")}
        merged = []
        for orig in rules:
            llm = by_id.get(orig.get("rule_id", ""))
            if llm:
                orig["domain"] = llm.get("domain", orig.get("domain", ""))
                orig["flow"] = llm.get("flow", orig.get("flow", ""))
                orig["description"] = llm.get("description", orig.get("description", ""))
                orig["severity"] = llm.get("severity", orig.get("severity", "medium"))
                orig["merge_with"] = llm.get("merge_with")
            merged.append(orig)
        return merged

    def _template_fallback(self, rules: list[dict]) -> list[dict]:
        """无 LLM 时的模板降级方案 — 直接赋值覆盖空值"""
        for r in rules:
            exc_msg = r.get("exception_message", "") or (r.get("params", {}) or {}).get("exception_message", "")
            status = r.get("status_value", "") or (r.get("params", {}) or {}).get("status_value", "")

            # 推断 domain（从 source_file 的包名）
            if not r.get("domain"):
                from .patterns import domain_from_package
                pkg = r.get("source_file", "").replace("/", ".").replace(".java", "")
                r["domain"] = domain_from_package(pkg)
            if not r.get("domain"):
                r["domain"] = "未分类"

            # 推断 flow（从类名）
            if not r.get("flow"):
                from .patterns import flow_from_class
                r["flow"] = flow_from_class(r.get("source_symbol", ""))
            if not r.get("flow"):
                r["flow"] = "通用流程"

            if exc_msg:
                r["description"] = exc_msg
            elif status:
                r["description"] = f"状态必须为: {status}"
            elif not r.get("description"):
                r["description"] = r.get("rule_id", "")

            if not r.get("severity"):
                r["severity"] = "medium"
            if "merge_with" not in r:
                r["merge_with"] = None
        return rules

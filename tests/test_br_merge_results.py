"""T003 [AC-03] _merge_results 字典索引测试

验证 _merge_results 正确合并 LLM 结果到原始规则。
"""
import pytest
from roam.business_rules.summarizer import RuleSummarizer


class TestMergeResults:
    """验证 O(1) 字典索引合并的正确性"""

    def test_merge_basic(self):
        """200 条规则 → 全部被正确合并"""
        summarizer = RuleSummarizer()  # 无 API key，但不影响 _merge_results

        rules = [
            {"rule_id": f"rule_{i}", "domain": "", "flow": "", "description": "", "severity": "medium"}
            for i in range(200)
        ]
        results = [
            {"rule_id": f"rule_{i}", "domain": "订单管理", "flow": "下单", "description": f"规则{i}", "severity": "high"}
            for i in range(200)
        ]

        merged = summarizer._merge_results(rules, results)
        assert len(merged) == 200
        for i, r in enumerate(merged):
            assert r["domain"] == "订单管理", f"rule_{i} domain 未合并"
            assert r["flow"] == "下单", f"rule_{i} flow 未合并"
            assert r["description"] == f"规则{i}", f"rule_{i} description 未合并"
            assert r["severity"] == "high", f"rule_{i} severity 未合并"

    def test_merge_partial_results(self):
        """results 中缺少某些 rule_id → 保留原始值"""
        summarizer = RuleSummarizer()

        rules = [
            {"rule_id": "rule_0", "domain": "", "flow": "", "description": "", "severity": "low"},
            {"rule_id": "rule_1", "domain": "", "flow": "", "description": "", "severity": "low"},
            {"rule_id": "rule_2", "domain": "", "flow": "", "description": "", "severity": "low"},
        ]
        # LLM 只返回了 rule_0 和 rule_2
        results = [
            {"rule_id": "rule_0", "domain": "订单管理", "flow": "下单", "description": "desc0", "severity": "high"},
            {"rule_id": "rule_2", "domain": "支付管理", "flow": "支付", "description": "desc2", "severity": "critical"},
        ]

        merged = summarizer._merge_results(rules, results)
        assert len(merged) == 3

        # rule_0 被增强
        assert merged[0]["domain"] == "订单管理"
        assert merged[0]["flow"] == "下单"
        assert merged[0]["severity"] == "high"

        # rule_1 保持原值（LLM 未返回）
        assert merged[1]["domain"] == ""
        assert merged[1]["severity"] == "low"

        # rule_2 被增强
        assert merged[2]["domain"] == "支付管理"
        assert merged[2]["flow"] == "支付"
        assert merged[2]["severity"] == "critical"

    def test_merge_empty_results(self):
        """空 results → 所有规则保持原值"""
        summarizer = RuleSummarizer()

        rules = [
            {"rule_id": "rule_0", "domain": "orig", "flow": "orig", "description": "orig", "severity": "low"},
        ]
        merged = summarizer._merge_results(rules, [])
        assert len(merged) == 1
        assert merged[0]["domain"] == "orig"

    def test_merge_with_none_rule_id(self):
        """results 中含 None rule_id → 不崩溃"""
        summarizer = RuleSummarizer()

        rules = [{"rule_id": "rule_0", "domain": "", "flow": "", "description": "", "severity": "low"}]
        results = [{"rule_id": None, "domain": "bad", "flow": "bad"}]

        merged = summarizer._merge_results(rules, results)
        assert len(merged) == 1
        assert merged[0]["domain"] == ""  # 未被污染

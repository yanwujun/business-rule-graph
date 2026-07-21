"""T011 [AC-03/04] RuleSummarizer 模板降级测试

覆盖: 无 API key 降级，domain/flow/description 生成正确性
"""
import pytest
from roam.business_rules.summarizer import RuleSummarizer


class TestTemplateFallback:
    """AC-04: LLM 不可用时模板降级"""

    def test_fallback_produces_all_fields(self):
        """降级后每条规则含 domain/flow/description 且非空"""
        summarizer = RuleSummarizer()  # 无 API key

        rules = [
            {
                "rule_id": "com.example.order.OrderService:145:if-throw",
                "rule_type": "validation",
                "source_file": "com/example/order/OrderService.java",
                "source_line": 145,
                "source_symbol": "validateOrder",
                "params": {"exception_message": "订单金额不能低于100元"},
                "domain": "",
                "flow": "",
                "description": "",
                "severity": "medium",
            },
            {
                "rule_id": "com.example.payment.PaymentController:89:if-throw",
                "rule_type": "validation",
                "source_file": "com/example/payment/PaymentController.java",
                "source_line": 89,
                "source_symbol": "processPayment",
                "params": {},
                "domain": "",
                "flow": "",
                "description": "",
                "severity": "low",
            },
        ]

        enriched = summarizer._template_fallback(rules)
        assert len(enriched) == 2

        for r in enriched:
            assert r.get("domain"), f"{r['rule_id']}: domain 不应为空"
            assert r.get("flow"), f"{r['rule_id']}: flow 不应为空"
            assert r.get("description"), f"{r['rule_id']}: description 不应为空"

    def test_fallback_domain_from_package(self):
        """包名含 'order' → domain='订单管理'"""
        summarizer = RuleSummarizer()

        rules = [{
            "rule_id": "com.example.order.OrderService:145:if-throw",
            "rule_type": "validation",
            "source_file": "com/example/order/OrderService.java",
            "source_line": 145,
            "source_symbol": "validateOrder",
            "params": {},
            "domain": "",
            "flow": "",
        }]

        enriched = summarizer._template_fallback(rules)
        assert enriched[0]["domain"] == "订单管理"

    def test_fallback_flow_from_exception_message(self):
        """异常消息可用于生成 description"""
        summarizer = RuleSummarizer()

        rules = [{
            "rule_id": "com.example.order.OrderService:145:if-throw",
            "rule_type": "validation",
            "source_file": "com/example/order/OrderService.java",
            "source_line": 145,
            "source_symbol": "validateOrder",
            "params": {"exception_message": "订单金额不能低于100元"},
            "domain": "",
            "flow": "",
        }]

        enriched = summarizer._template_fallback(rules)
        assert "100" in enriched[0]["description"] or "金额" in enriched[0]["description"]

    def test_fallback_no_api_key_succeeds(self):
        """无 API key 的 summarizer 调用 summarize → 走 fallback"""
        summarizer = RuleSummarizer()  # api_key=None

        rules = [{
            "rule_id": "test:1",
            "rule_type": "validation",
            "source_file": "test.java",
            "source_line": 1,
            "source_symbol": "test",
            "params": {},
            "domain": "",
            "flow": "",
        }]

        result = summarizer.summarize(rules)
        assert len(result) == 1
        assert result[0]["domain"]  # 降级后不应为空

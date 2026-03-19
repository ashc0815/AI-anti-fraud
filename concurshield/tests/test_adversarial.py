"""对抗性测试用例 - 测试系统对各类欺诈手段的检测能力"""

import pytest


class TestTamperedReceipts:
    """篡改发票检测测试"""

    def test_modified_amount(self) -> None:
        """测试检测金额被篡改的发票。"""
        pass

    def test_modified_date(self) -> None:
        """测试检测日期被篡改的发票。"""
        pass

    def test_modified_merchant(self) -> None:
        """测试检测商户名被篡改的发票。"""
        pass


class TestAIGeneratedReceipts:
    """AI 生成发票检测测试"""

    def test_fully_generated_receipt(self) -> None:
        """测试检测完全由 AI 生成的发票。"""
        pass

    def test_partially_generated_receipt(self) -> None:
        """测试检测部分由 AI 生成的发票。"""
        pass


class TestDuplicateReceipts:
    """重复发票检测测试"""

    def test_exact_duplicate(self) -> None:
        """测试检测完全相同的重复发票。"""
        pass

    def test_slightly_modified_duplicate(self) -> None:
        """测试检测经过轻微修改的重复发票。"""
        pass

    def test_resized_duplicate(self) -> None:
        """测试检测缩放后的重复发票。"""
        pass


class TestPromptInjection:
    """Prompt 注入攻击防御测试"""

    def test_injection_in_merchant_name(self) -> None:
        """测试商户名中包含 prompt 注入的情况。"""
        pass

    def test_injection_in_receipt_text(self) -> None:
        """测试发票文本中包含 prompt 注入的情况。"""
        pass


class TestRuleEngine:
    """规则引擎测试"""

    def test_amount_exceeds_limit(self) -> None:
        """测试金额超限检测。"""
        pass

    def test_weekend_transaction(self) -> None:
        """测试周末交易检测。"""
        pass

    def test_round_amount_detection(self) -> None:
        """测试整数金额检测。"""
        pass

    def test_missing_fields(self) -> None:
        """测试缺失字段检测。"""
        pass

"""确定性规则引擎 - 基于预定义规则检测发票异常"""

from concurshield.models.schemas import ReceiptData, RuleCheckResult


def check_all_rules(receipt_data: ReceiptData) -> list[RuleCheckResult]:
    """对 OCR 结果执行所有规则检查。

    Args:
        receipt_data: OCR 结构化数据。

    Returns:
        所有规则的检查结果列表。
    """
    pass


def check_amount_limit(receipt_data: ReceiptData, max_amount: float = 50000.0) -> RuleCheckResult:
    """检查金额是否超过上限。

    Args:
        receipt_data: OCR 结构化数据。
        max_amount: 允许的最大金额，默认 50000。

    Returns:
        规则检查结果。
    """
    pass


def check_weekend_transaction(receipt_data: ReceiptData) -> RuleCheckResult:
    """检查交易是否发生在周末。

    Args:
        receipt_data: OCR 结构化数据。

    Returns:
        规则检查结果。
    """
    pass


def check_round_amount(receipt_data: ReceiptData) -> RuleCheckResult:
    """检查金额是否为整数（可疑的凑整行为）。

    Args:
        receipt_data: OCR 结构化数据。

    Returns:
        规则检查结果。
    """
    pass


def check_missing_fields(receipt_data: ReceiptData) -> RuleCheckResult:
    """检查关键字段是否缺失。

    Args:
        receipt_data: OCR 结构化数据。

    Returns:
        规则检查结果。
    """
    pass

"""确定性规则引擎 - 基于预定义规则检测发票异常"""

from concurshield.models.schemas import OCRResult, RuleCheckResult


def check_all_rules(ocr_result: OCRResult) -> list[RuleCheckResult]:
    """对 OCR 结果执行所有规则检查。

    Args:
        ocr_result: OCR 识别结果。

    Returns:
        所有规则的检查结果列表。
    """
    pass


def check_amount_limit(ocr_result: OCRResult, max_amount: float = 50000.0) -> RuleCheckResult:
    """检查金额是否超过上限。

    Args:
        ocr_result: OCR 识别结果。
        max_amount: 允许的最大金额，默认 50000。

    Returns:
        规则检查结果。
    """
    pass


def check_weekend_transaction(ocr_result: OCRResult) -> RuleCheckResult:
    """检查交易是否发生在周末。

    Args:
        ocr_result: OCR 识别结果。

    Returns:
        规则检查结果。
    """
    pass


def check_round_amount(ocr_result: OCRResult) -> RuleCheckResult:
    """检查金额是否为整数（可疑的凑整行为）。

    Args:
        ocr_result: OCR 识别结果。

    Returns:
        规则检查结果。
    """
    pass


def check_missing_fields(ocr_result: OCRResult) -> RuleCheckResult:
    """检查关键字段是否缺失。

    Args:
        ocr_result: OCR 识别结果。

    Returns:
        规则检查结果。
    """
    pass

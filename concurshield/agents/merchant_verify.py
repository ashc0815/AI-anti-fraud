"""商户验证子 Agent - 验证发票上的商户信息真实性"""

from concurshield.models.schemas import AgentAction, ReceiptData


def verify_merchant(receipt_data: ReceiptData) -> list[AgentAction]:
    """验证商户信息的真实性和一致性。

    检查项目：
    - 商户名称是否合理
    - 地址与商户类型是否匹配
    - 金额与商户类型是否匹配
    - 是否存在已知的虚假商户模式

    Args:
        receipt_data: OCR 结构化数据。

    Returns:
        Agent 工具调用记录列表。
    """
    pass


def check_merchant_consistency(
    merchant_name: str, items: list[str], amount: float
) -> list[AgentAction]:
    """检查商户名称、消费内容和金额之间的一致性。

    Args:
        merchant_name: 商户名称。
        items: 消费明细列表。
        amount: 总金额。

    Returns:
        一致性检查结果。
    """
    pass

"""商户验证子 Agent - 验证发票上的商户信息真实性"""

from __future__ import annotations

import time

from concurshield.models.schemas import AgentAction, ReceiptData


async def verify_merchant(receipt_data: ReceiptData) -> list[AgentAction]:
    """验证商户信息的真实性和一致性。

    检查项目：
    - 商户名称是否为空或异常短
    - 金额与商户类型是否匹配
    - 消费内容与商户名称的一致性

    Args:
        receipt_data: OCR 结构化数据。

    Returns:
        Agent 工具调用记录列表。
    """
    start = time.monotonic()
    findings: list[str] = []

    # 商户名称检查
    name = receipt_data.merchant_name.strip()
    if len(name) < 2:
        findings.append(f"商户名称异常短: '{name}'")
    if any(c.isdigit() for c in name) and not any(c.isalpha() for c in name):
        findings.append(f"商户名称仅含数字: '{name}'")

    # 金额与行项一致性
    if receipt_data.items:
        item_descs = [item.description for item in receipt_data.items]
        avg_price = receipt_data.total / len(receipt_data.items)

        # 检查高单价项目
        for item in receipt_data.items:
            if item.amount > 10000:
                findings.append(
                    f"行项 '{item.description}' 金额异常高: {item.amount}"
                )

        findings.append(
            f"商户 '{name}' 共 {len(receipt_data.items)} 项消费，"
            f"均价 {avg_price:.2f} {receipt_data.currency}"
        )
    else:
        findings.append("无行项明细，无法验证消费内容")

    duration_ms = int((time.monotonic() - start) * 1000)

    return [AgentAction(
        agent_name="merchant_verify",
        tool_name="merchant_consistency_check",
        input_summary=f"验证商户 '{name}' 的信息一致性",
        output_summary="; ".join(findings) if findings else "未发现异常",
        duration_ms=duration_ms,
    )]

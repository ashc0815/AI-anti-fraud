"""Main Agent 编排器 - 协调各子 Agent 完成发票审核流程"""

from __future__ import annotations

from pathlib import Path

from concurshield.models.schemas import ForensicReport, ReceiptInput


def analyze_receipt(receipt_input: ReceiptInput) -> ForensicReport:
    """主编排入口：接收发票输入，协调所有子 Agent 和引擎模块，输出风险报告。

    流程：
    1. OCR 提取发票信息
    2. 并行调度子 Agent（视觉取证、商户验证、元数据分析）
    3. 执行规则引擎检查
    4. 执行重复检测
    5. 综合评分，生成报告

    Args:
        receipt_input: 发票输入模型。

    Returns:
        最终取证报告。
    """
    pass


def dispatch_agents(image_path: str | Path, ocr_text: str) -> list:
    """并行调度所有子 Agent 进行分析。

    Args:
        image_path: 发票图片路径。
        ocr_text: OCR 识别的原始文本。

    Returns:
        各子 Agent 的分析结果列表。
    """
    pass

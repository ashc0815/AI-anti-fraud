"""视觉取证子 Agent - 检测发票图片的篡改和伪造痕迹"""

from __future__ import annotations

from pathlib import Path

from concurshield.models.schemas import AgentAction


def analyze_visual_integrity(image_path: str | Path) -> list[AgentAction]:
    """分析发票图片的视觉完整性，检测篡改痕迹。

    检测项目：
    - 像素级修改痕迹
    - 字体一致性
    - 噪声模式异常
    - AI 生成特征

    Args:
        image_path: 发票图片路径。

    Returns:
        Agent 工具调用记录列表。
    """
    pass


def check_ai_generated(image_path: str | Path) -> list[AgentAction]:
    """检测图片是否由 AI 生成。

    Args:
        image_path: 发票图片路径。

    Returns:
        Agent 工具调用记录列表。
    """
    pass

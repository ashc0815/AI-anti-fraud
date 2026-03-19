"""视觉取证子 Agent - 检测发票图片的篡改和伪造痕迹"""

from pathlib import Path

from concurshield.models.schemas import AgentFinding


def analyze_visual_integrity(image_path: str | Path) -> AgentFinding:
    """分析发票图片的视觉完整性，检测篡改痕迹。

    检测项目：
    - 像素级修改痕迹
    - 字体一致性
    - 噪声模式异常
    - AI 生成特征

    Args:
        image_path: 发票图片路径。

    Returns:
        视觉取证分析结果。
    """
    pass


def check_ai_generated(image_path: str | Path) -> AgentFinding:
    """检测图片是否由 AI 生成。

    Args:
        image_path: 发票图片路径。

    Returns:
        AI 生成检测结果。
    """
    pass

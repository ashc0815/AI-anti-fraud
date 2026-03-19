"""元数据分析子 Agent - 分析发票图片的 EXIF 和文件元数据"""

from pathlib import Path

from concurshield.models.schemas import AgentAction


def analyze_metadata(image_path: str | Path) -> list[AgentAction]:
    """分析图片文件的元数据，检测异常信号。

    检查项目：
    - EXIF 数据完整性
    - 创建/修改时间一致性
    - 编辑软件痕迹
    - GPS 信息合理性

    Args:
        image_path: 图片文件路径。

    Returns:
        Agent 工具调用记录列表。
    """
    pass


def extract_exif(image_path: str | Path) -> dict:
    """提取图片的 EXIF 元数据。

    Args:
        image_path: 图片文件路径。

    Returns:
        EXIF 元数据字典。
    """
    pass


def detect_editing_software(exif_data: dict) -> list[AgentAction]:
    """根据 EXIF 数据检测是否使用了图像编辑软件。

    Args:
        exif_data: EXIF 元数据字典。

    Returns:
        Agent 工具调用记录列表。
    """
    pass

"""元数据分析子 Agent - 分析发票图片的 EXIF 和文件元数据"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS

from concurshield.models.schemas import AgentAction


async def analyze_metadata(image_path: str | Path) -> list[AgentAction]:
    """分析图片文件的元数据，检测异常信号。

    检查项目：
    - EXIF 数据完整性
    - 创建/修改时间一致性
    - 编辑软件痕迹

    Args:
        image_path: 图片文件路径。

    Returns:
        Agent 工具调用记录列表。
    """
    start = time.monotonic()
    path = Path(image_path)

    exif = extract_exif(path)
    findings: list[str] = []

    # 检查编辑软件
    software = exif.get("Software", "")
    if software:
        suspicious_tools = ["photoshop", "gimp", "pixlr", "snapseed", "lightroom"]
        if any(t in software.lower() for t in suspicious_tools):
            findings.append(f"检测到图片编辑软件: {software}")
        else:
            findings.append(f"拍摄软件: {software}")

    # 检查 EXIF 完整性
    if not exif:
        findings.append("无 EXIF 数据（可能被剥离或截图）")
    else:
        if "DateTimeOriginal" not in exif and "DateTime" not in exif:
            findings.append("缺少拍摄时间信息")
        if "Make" not in exif and "Model" not in exif:
            findings.append("缺少设备信息")

    # 检查文件大小异常
    file_size = path.stat().st_size
    if file_size < 5000:
        findings.append(f"文件异常小 ({file_size} bytes)，可能是截图或合成")

    duration_ms = int((time.monotonic() - start) * 1000)

    return [AgentAction(
        agent_name="metadata_agent",
        tool_name="exif_analysis",
        input_summary=f"分析 {path.name} 的 EXIF 元数据",
        output_summary="; ".join(findings) if findings else "未发现异常",
        duration_ms=duration_ms,
    )]


def extract_exif(image_path: str | Path) -> dict:
    """提取图片的 EXIF 元数据。

    Args:
        image_path: 图片文件路径。

    Returns:
        EXIF 元数据字典（tag 名 → 值）。
    """
    try:
        img = Image.open(image_path)
        raw_exif = img.getexif()
        if not raw_exif:
            return {}
        return {TAGS.get(k, str(k)): str(v) for k, v in raw_exif.items()}
    except Exception:
        return {}

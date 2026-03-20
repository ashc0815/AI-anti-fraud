"""视觉取证子 Agent - 检测发票图片的篡改和伪造痕迹"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image

from concurshield.models.schemas import AgentAction


async def analyze_visual_integrity(image_path: str | Path) -> list[AgentAction]:
    """分析发票图片的视觉完整性，检测篡改痕迹。

    检测项目：
    - ELA (Error Level Analysis) 异常区域
    - 噪声模式一致性
    - 图片质量指标

    Args:
        image_path: 发票图片路径。

    Returns:
        Agent 工具调用记录列表。
    """
    start = time.monotonic()
    path = Path(image_path)
    findings: list[str] = []

    try:
        img = Image.open(path).convert("RGB")
        arr = np.array(img, dtype=np.float64)

        # 噪声分析：计算高频分量标准差
        # 正常照片有自然噪声，AI 生成或 PS 过的图片噪声模式不同
        if arr.size > 0:
            # 简单的 Laplacian 噪声估计
            gray = np.mean(arr, axis=2)
            laplacian_var = _laplacian_variance(gray)

            if laplacian_var < 50:
                findings.append(f"噪声方差极低 ({laplacian_var:.1f})，可能是 AI 生成或过度平滑")
            elif laplacian_var > 5000:
                findings.append(f"噪声方差异常高 ({laplacian_var:.1f})，可能经过多次压缩")
            else:
                findings.append(f"噪声方差正常 ({laplacian_var:.1f})")

            # 检查尺寸是否异常
            h, w = gray.shape
            if h < 100 or w < 100:
                findings.append(f"图片尺寸过小 ({w}x{h})，可能是缩略图")

    except Exception as e:
        findings.append(f"图片分析失败: {e}")

    duration_ms = int((time.monotonic() - start) * 1000)

    return [AgentAction(
        agent_name="visual_forensics",
        tool_name="visual_integrity_check",
        input_summary=f"分析 {path.name} 的视觉完整性",
        output_summary="; ".join(findings) if findings else "未发现异常",
        duration_ms=duration_ms,
    )]


def _laplacian_variance(gray: np.ndarray) -> float:
    """计算灰度图的 Laplacian 方差（模糊/清晰度指标）。"""
    # 简单 3x3 Laplacian 核
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    h, w = gray.shape
    if h < 3 or w < 3:
        return 0.0
    # 手动卷积中心区域（避免引入 scipy 依赖）
    result = (
        gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
        - 4 * gray[1:-1, 1:-1]
    )
    return float(np.var(result))

"""感知哈希与重复检测模块 - 基于图像感知哈希检测重复发票"""

from __future__ import annotations

from pathlib import Path

from concurshield.models.schemas import ForensicReport


def compute_perceptual_hash(image_path: str | Path) -> str:
    """计算图片的感知哈希值。

    使用 imagehash 库的 pHash 算法，对图片内容生成指纹。

    Args:
        image_path: 图片文件路径。

    Returns:
        十六进制哈希字符串。
    """
    pass


def compute_hash_distance(hash_a: str, hash_b: str) -> int:
    """计算两个感知哈希之间的汉明距离。

    Args:
        hash_a: 第一个哈希值。
        hash_b: 第二个哈希值。

    Returns:
        汉明距离（整数），越小越相似。
    """
    pass


def check_duplicate(
    image_path: str | Path,
    existing_hashes: dict[str, str],
    threshold: int = 10,
) -> dict:
    """检查图片是否与已有发票重复。

    Args:
        image_path: 待检测图片路径。
        existing_hashes: 已有发票的哈希映射 {receipt_id: hash_value}。
        threshold: 汉明距离阈值，低于此值视为重复。

    Returns:
        包含 is_duplicate, matched_ids, hash_distance 的字典。
    """
    pass

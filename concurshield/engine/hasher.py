"""感知哈希与重复检测模块 - 基于图像感知哈希检测重复发票"""

from __future__ import annotations

from pathlib import Path

import imagehash
from PIL import Image

from concurshield.db import store


def compute_hash(image_path: str | Path) -> str:
    """计算图片的感知哈希值。

    使用 imagehash 库的 pHash 算法，对图片内容生成指纹。

    Args:
        image_path: 图片文件路径。

    Returns:
        十六进制哈希字符串。

    Raises:
        FileNotFoundError: 图片文件不存在。
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"图片文件不存在: {path}")
    img = Image.open(path)
    h = imagehash.phash(img)
    return str(h)


def find_duplicates(hash_value: str, threshold: float = 0.92) -> list[dict]:
    """从 SQLite 数据库查询历史哈希，返回相似度超过阈值的记录。

    相似度计算：1 - hamming_distance / hash_length

    Args:
        hash_value: 当前图片的哈希值。
        threshold: 相似度阈值（默认 0.92，即允许 8% 差异）。

    Returns:
        相似度 > threshold 的记录列表，每条包含:
        - receipt_id: 历史发票 ID
        - hash_value: 历史哈希值
        - similarity: 相似度 (0~1)
        - created_at: 记录创建时间
    """
    current_hash = imagehash.hex_to_hash(hash_value)
    hash_length = len(current_hash.hash.flatten())

    all_records = store.get_all_hashes()
    matches: list[dict] = []

    for record in all_records:
        other_hash = imagehash.hex_to_hash(record["hash_value"])
        distance = current_hash - other_hash  # hamming distance
        similarity = 1 - distance / hash_length
        if similarity > threshold:
            matches.append({
                "receipt_id": record["receipt_id"],
                "hash_value": record["hash_value"],
                "similarity": round(similarity, 4),
                "created_at": record["created_at"],
            })

    # 按相似度降序排列
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches

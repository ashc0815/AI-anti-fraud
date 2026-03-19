"""Claude Vision OCR 模块 - 使用 Claude 多模态能力提取发票信息"""

from pathlib import Path

from concurshield.models.schemas import ReceiptData


def extract_receipt_text(image_path: str | Path) -> ReceiptData:
    """使用 Claude Vision 从发票图片中提取结构化信息。

    Args:
        image_path: 发票图片的文件路径，支持 PNG/JPG/WEBP。

    Returns:
        ReceiptData: 包含商户名称、金额、日期等结构化字段的识别结果。
    """
    pass


def encode_image_to_base64(image_path: str | Path) -> str:
    """将图片文件编码为 base64 字符串，用于 Claude API 调用。

    Args:
        image_path: 图片文件路径。

    Returns:
        base64 编码后的字符串。
    """
    pass


def detect_image_type(image_path: str | Path) -> str:
    """检测图片 MIME 类型。

    Args:
        image_path: 图片文件路径。

    Returns:
        MIME 类型字符串，如 'image/png'。
    """
    pass

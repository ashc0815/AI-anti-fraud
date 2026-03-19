"""Mock 测试 - 验证 OCR 模块的解析、校验逻辑（不需要网络）"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from concurshield.engine.ocr import (
    OCRError,
    _parse_response_json,
    _validate_receipt_data,
    detect_image_type,
    encode_image_to_base64,
    extract_receipt,
)
from concurshield.models.schemas import ReceiptData

# ── 模拟 Claude 返回的 JSON（基于你上传的那张电子发票） ──

MOCK_CLAUDE_RESPONSE = json.dumps(
    {
        "merchant_name": "亿贝电子商务技术管运(上海)有限公司",
        "merchant_address": None,
        "merchant_country": "CN",
        "date": "2026-02-11",
        "currency": "CNY",
        "items": [
            {
                "description": "餐饮服务*餐费",
                "quantity": 1,
                "unit_price": 684.91,
                "amount": 684.91,
            }
        ],
        "subtotal": 684.91,
        "tax_amount": 41.09,
        "tax_rate": 0.06,
        "total": 726.00,
        "raw_text": "电子发票(普通发票)\n发票号码: 26312000008408171186\n开票日期: 2026年02月11日\n名称: 亿贝电子商务技术管运(上海)有限公司\n*餐饮服务*餐费\n单价 684.91\n金额 684.91\n税率 6%\n税额 41.09\n价税合计 ¥726.00",
    },
    ensure_ascii=False,
)


def test_detect_image_type():
    assert detect_image_type("a.png") == "image/png"
    assert detect_image_type("b.JPG") == "image/jpeg"
    assert detect_image_type("c.webp") == "image/webp"
    assert detect_image_type("d.gif") == "image/gif"
    try:
        detect_image_type("e.bmp")
        assert False, "应抛出 OCRError"
    except OCRError:
        pass
    print("[PASS] detect_image_type")


def test_parse_response_json():
    # 纯 JSON
    r = _parse_response_json('{"total": 42}')
    assert r == {"total": 42}
    # markdown 代码块
    r2 = _parse_response_json('```json\n{"total": 99}\n```')
    assert r2 == {"total": 99}
    # 非法 JSON
    try:
        _parse_response_json("not json")
        assert False
    except OCRError:
        pass
    print("[PASS] _parse_response_json")


def test_validate_receipt_data():
    good = ReceiptData(
        merchant_name="Test", merchant_country="CN",
        date="2026-02-11", currency="CNY", total=726.0,
    )
    _validate_receipt_data(good)  # 应通过

    # total 为负
    bad1 = ReceiptData(
        merchant_name="X", merchant_country="CN",
        date="2026-01-01", currency="CNY", total=-1.0,
    )
    try:
        _validate_receipt_data(bad1)
        assert False
    except OCRError:
        pass

    # 日期格式错误
    bad2 = ReceiptData(
        merchant_name="X", merchant_country="CN",
        date="11/02/2026", currency="CNY", total=10.0,
    )
    try:
        _validate_receipt_data(bad2)
        assert False
    except OCRError:
        pass
    print("[PASS] _validate_receipt_data")


def test_extract_receipt_e2e():
    """端到端 mock 测试：模拟完整的 API 调用流程"""

    # 构造模拟的 Claude API 响应
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = MOCK_CLAUDE_RESPONSE

    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("concurshield.engine.ocr.anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("concurshield.engine.ocr.encode_image_to_base64", return_value="fake_b64"), \
         patch("concurshield.engine.ocr.detect_image_type", return_value="image/jpeg"):

        result = asyncio.run(extract_receipt("test_receipts/normal/test发票.jpg"))

    # 验证提取结果
    assert result.merchant_name == "亿贝电子商务技术管运(上海)有限公司"
    assert result.merchant_country == "CN"
    assert result.date == "2026-02-11"
    assert result.currency == "CNY"
    assert len(result.items) == 1
    assert result.items[0].description == "餐饮服务*餐费"
    assert result.items[0].amount == 684.91
    assert result.total == 726.00
    assert result.tax_amount == 41.09
    assert result.tax_rate == 0.06
    assert result.subtotal == 684.91
    assert len(result.raw_text) > 0

    print(f"  商户名: {result.merchant_name}")
    print(f"  国家: {result.merchant_country}")
    print(f"  日期: {result.date}")
    print(f"  货币: {result.currency}")
    print(f"  行项数: {len(result.items)}")
    for item in result.items:
        print(f"    - {item.description}: {item.amount}")
    print(f"  总额: {result.total}")
    print(f"  税额: {result.tax_amount}")
    print(f"  税率: {result.tax_rate}")
    print(f"  原始文本长度: {len(result.raw_text)} chars")
    print(f"  JSON 序列化: {len(result.model_dump_json())} chars")
    print("[PASS] extract_receipt (端到端 mock)")


def test_extract_receipt_api_failure():
    """测试 API 失败后重试并最终抛出异常"""
    import anthropic as anthropic_mod

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic_mod.APIError(
            message="server error",
            request=MagicMock(),
            body=None,
        )
    )

    with patch("concurshield.engine.ocr.anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("concurshield.engine.ocr.encode_image_to_base64", return_value="fake_b64"), \
         patch("concurshield.engine.ocr.detect_image_type", return_value="image/jpeg"):
        try:
            asyncio.run(extract_receipt("fake.jpg"))
            assert False, "应抛出 OCRError"
        except OCRError as e:
            assert "连续失败" in str(e)

    # 验证重试了 3 次（1 次 + 2 次重试）
    assert mock_client.messages.create.call_count == 3
    print("[PASS] extract_receipt API 重试机制")


if __name__ == "__main__":
    print("=" * 50)
    print("OCR 模块 Mock 测试")
    print("=" * 50)
    test_detect_image_type()
    test_parse_response_json()
    test_validate_receipt_data()
    test_extract_receipt_e2e()
    test_extract_receipt_api_failure()
    print("=" * 50)
    print("全部测试通过！OCR 验收通过！")
    print("=" * 50)

"""通过 OpenRouter (OpenAI 格式) 测试 OCR 逻辑 - 绕过 Anthropic SDK"""

import base64
import json
import os
import time
from pathlib import Path

import httpx

from concurshield.engine.ocr import _SYSTEM_PROMPT, _parse_response_json, _validate_receipt_data
from concurshield.models.schemas import ReceiptData

API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
IMAGE_PATH = "test_receipts/normal/test发票.jpg"


def main():
    # 1. 读取图片
    path = Path(IMAGE_PATH)
    if not path.is_file():
        print(f"错误: 图片不存在 {path}")
        return
    image_b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    suffix = path.suffix.lower()
    media_type = {"jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
    print(f"图片大小: {path.stat().st_size / 1024:.1f} KB")

    # 2. 调用 OpenRouter (OpenAI 兼容格式)
    print(f"正在调用 OpenRouter API (模型: {MODEL})...")
    start = time.time()
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": "请提取这张收据/发票中的所有信息，按要求的 JSON 格式返回。",
                    },
                ],
            },
        ],
        "max_tokens": 4096,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    # 重试逻辑，跳过 SSL 验证以解决网络问题
    resp = None
    for attempt in range(3):
        try:
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
                verify=False,
            )
            break
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
            wait = 2 ** (attempt + 1)
            print(f"连接失败 (第{attempt+1}次): {e}")
            if attempt < 2:
                print(f"等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                print("3次重试均失败，请检查网络连接。")
                return

    if resp is None:
        return
    elapsed = time.time() - start
    print(f"API 响应耗时: {elapsed:.1f}s, 状态码: {resp.status_code}")

    if resp.status_code != 200:
        print(f"API 错误: {resp.text[:500]}")
        return

    data = resp.json()
    text_content = data["choices"][0]["message"]["content"]
    print(f"原始响应长度: {len(text_content)} chars")

    # 3. 解析 JSON
    parsed = _parse_response_json(text_content)
    result = ReceiptData.model_validate(parsed)
    _validate_receipt_data(result)

    # 4. 输出结果
    print("=" * 50)
    print(f"商户名: {result.merchant_name}")
    print(f"国家: {result.merchant_country}")
    print(f"日期: {result.date}")
    print(f"货币: {result.currency}")
    print(f"行项数: {len(result.items)}")
    for item in result.items:
        print(f"  - {item.description}: {item.amount}")
    print(f"总额: {result.total}")
    print(f"税额: {result.tax_amount}")
    print(f"税率: {result.tax_rate}")
    print(f"原始文本长度: {len(result.raw_text)} chars")
    print(f"JSON 序列化: {len(result.model_dump_json())} chars")
    print("=" * 50)
    print("OCR 验收通过！")


if __name__ == "__main__":
    main()

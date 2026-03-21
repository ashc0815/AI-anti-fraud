"""OpenAI API 连通性测试 - 文本调用 + Vision 调用"""

import asyncio
import base64
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import openai


async def test_text_call(client: openai.AsyncOpenAI, model: str) -> bool:
    """测试 1: 简单文本调用"""
    print("=" * 50)
    print("测试 1: 文本调用")
    print("=" * 50)
    start = time.time()
    try:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=50,
            messages=[
                {"role": "user", "content": "请用一句话回答：1+1等于几？"}
            ],
        )
        elapsed = time.time() - start
        text = response.choices[0].message.content
        print(f"  模型: {response.model}")
        print(f"  响应: {text}")
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  tokens: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}")
        print("[PASS] 文本调用成功")
        return True
    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL] 文本调用失败 ({elapsed:.1f}s): {e}")
        return False


async def test_vision_call(client: openai.AsyncOpenAI, model: str) -> bool:
    """测试 2: Vision 图片调用"""
    print()
    print("=" * 50)
    print("测试 2: Vision 调用 (发票图片)")
    print("=" * 50)

    image_path = Path("test_receipts/normal/test发票.jpg")
    if not image_path.is_file():
        print(f"[SKIP] 图片不存在: {image_path}")
        return False

    image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    print(f"  图片: {image_path} ({image_path.stat().st_size / 1024:.1f} KB)")

    start = time.time()
    try:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": "这张图片是什么？请用一句话简要描述内容。",
                        },
                    ],
                }
            ],
        )
        elapsed = time.time() - start
        text = response.choices[0].message.content
        print(f"  模型: {response.model}")
        print(f"  响应: {text}")
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  tokens: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}")
        print("[PASS] Vision 调用成功")
        return True
    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL] Vision 调用失败 ({elapsed:.1f}s): {e}")
        return False


async def main():
    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    if not api_key or api_key == "your-openai-key-here":
        print("错误: 请在 .env 中设置有效的 OPENAI_API_KEY")
        sys.exit(1)

    print(f"API Key: {api_key[:8]}...{api_key[-4:]}")
    print(f"Base URL: {base_url or '(默认 OpenAI)'}")
    print(f"Model: {model}")
    print()

    client_kwargs: dict = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = openai.AsyncOpenAI(**client_kwargs)

    text_ok = await test_text_call(client, model)
    vision_ok = await test_vision_call(client, model)

    print()
    print("=" * 50)
    if text_ok and vision_ok:
        print("全部通过！OpenAI API 连通性正常。")
    else:
        print("部分测试失败，请检查 API Key 和网络连接。")
        sys.exit(1)
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

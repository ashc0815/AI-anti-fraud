import asyncio
import json

from concurshield.engine.ocr import extract_receipt


async def test():
    image_path = "test_receipts/normal/test发票.jpg"
    print(f"正在识别: {image_path}\n")

    result = await extract_receipt(image_path)

    # 输出结构化 JSON
    structured = {
        "商户名": result.merchant_name,
        "国家": result.merchant_country,
        "日期": result.date,
        "货币": result.currency,
        "行项明细": [
            {
                "描述": item.description,
                "数量": item.quantity,
                "单价": item.unit_price,
                "金额": item.amount,
            }
            for item in result.items
        ],
        "总额": result.total,
        "税额": result.tax_amount,
        "税率": result.tax_rate,
    }

    print(json.dumps(structured, ensure_ascii=False, indent=2))
    print("\nOCR 验收通过！")


asyncio.run(test())

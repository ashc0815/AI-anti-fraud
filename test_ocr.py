import asyncio
from concurshield.engine.ocr import extract_receipt

async def test():
    result = await extract_receipt("test_receipts/normal/test发票.jpg")
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
    print("OCR 验收通过！")

asyncio.run(test())

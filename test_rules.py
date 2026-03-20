import asyncio
from concurshield.models.schemas import ReceiptItem, ReceiptData
from concurshield.engine.rules import run_rules, has_anomaly
# ====== 测试1：正常收据，所有规则应通过 ======
normal_receipt = ReceiptData(
    merchant_name="星巴克",
    merchant_country="CN",
    date="2026-03-19",
    currency="CNY",
    items=[
        ReceiptItem(description="拿铁", quantity=1, unit_price=30.0, amount=30.0),
        ReceiptItem(description="蛋糕", quantity=1, unit_price=25.0, amount=25.0),
    ],
    subtotal=55.0,
    tax_amount=3.30,
    tax_rate=6,
    total=58.30,
    raw_text="星巴克 拿铁30 蛋糕25 小计55 税3.30 合计58.30"
)
results = run_rules(normal_receipt)
print("===== 测试1：正常收据 =====")
for r in results:
    status = "✅" if r.passed else "❌"
    print(f"  {status} {r.rule_id}: {r.rule_name} — {r.detail}")
print(f"  有异常？{has_anomaly(results)}")
assert not has_anomaly(results), "正常收据不应有异常！"
print("  测试1 通过！\n")
# ====== 测试2：税额错误，MATH_002 应失败 ======
bad_tax_receipt = ReceiptData(
    merchant_name="星巴克",
    merchant_country="CN",
    date="2026-03-19",
    currency="CNY",
    items=[
        ReceiptItem(description="拿铁", quantity=1, unit_price=30.0, amount=30.0),
        ReceiptItem(description="蛋糕", quantity=1, unit_price=25.0, amount=25.0),
    ],
    subtotal=55.0,
    tax_amount=15.0,  # 故意写错：6%税率下应该是3.30
    tax_rate=6,
    total=70.0,  # 也跟着错
    raw_text="星巴克 拿铁30 蛋糕25"
)
results2 = run_rules(bad_tax_receipt)
print("===== 测试2：税额错误 =====")
for r in results2:
    status = "✅" if r.passed else "❌"
    print(f"  {status} {r.rule_id}: {r.rule_name} — {r.detail}")
print(f"  有异常？{has_anomaly(results2)}")
math002_failed = any(r.rule_id == "MATH_002" and not r.passed for r in results2)
assert math002_failed, "MATH_002 应该失败！"
assert has_anomaly(results2), "应该检测到异常！"
print("  测试2 通过！\n")
# ====== 测试3：货币与国家不匹配 ======
wrong_currency = ReceiptData(
    merchant_name="Some Shop",
    merchant_country="CN",
    date="2026-03-19",
    currency="AUD",  # 中国商户用澳元，应该失败
    items=[ReceiptItem(description="item", quantity=1, unit_price=10.0, amount=10.0)],
    total=10.0,
    raw_text="some shop"
)
results3 = run_rules(wrong_currency)
print("===== 测试3：货币不匹配 =====")
for r in results3:
    status = "✅" if r.passed else "❌"
    print(f"  {status} {r.rule_id}: {r.rule_name} — {r.detail}")
math004_failed = any(r.rule_id == "MATH_004" and not r.passed for r in results3)
assert math004_failed, "MATH_004 应该失败！"
print("  测试3 通过！\n")
print("===== 全部规则引擎测试通过！ =====")

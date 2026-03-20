import os
from PIL import Image, ImageDraw, ImageFont
from concurshield.engine.hasher import compute_hash, find_duplicates
from concurshield.db.store import init_db, save_receipt, get_all_hashes
from concurshield.models.schemas import ReceiptData, ReceiptItem, ForensicReport
# 初始化数据库
init_db()
# ====== 准备测试图片 ======
# 用代码生成一张模拟收据图片（不依赖真实收据）
def create_fake_receipt(filename, date_text="2026-03-19", amount_text="58.30"):
    img = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), "星巴克咖啡", fill="black")
    draw.text((50, 100), f"日期: {date_text}", fill="black")
    draw.text((50, 150), "拿铁 x1    30.00", fill="black")
    draw.text((50, 200), "蛋糕 x1    25.00", fill="black")
    draw.text((50, 300), f"合计: {amount_text}", fill="black")
    draw.rectangle([(30, 30), (370, 350)], outline="gray")
    img.save(filename)
    return filename
os.makedirs("test_receipts/hash_test", exist_ok=True)
# 原始图片
original = create_fake_receipt("test_receipts/hash_test/original.png")
# 完全相同的副本
identical = create_fake_receipt("test_receipts/hash_test/identical.png")
# 只改了日期（模拟 PS 修改日期）
date_changed = create_fake_receipt("test_receipts/hash_test/date_changed.png",
                                    date_text="2026-01-15")
# 改了日期和金额（模拟更大的篡改）
both_changed = create_fake_receipt("test_receipts/hash_test/both_changed.png",
                                    date_text="2026-01-15",
                                    amount_text="158.30")
# 完全不同的图片
different = Image.new("RGB", (400, 600), "blue")
different.save("test_receipts/hash_test/different.png")
# ====== 测试1：同一张图片哈希值相同 ======
hash1 = compute_hash(original)
hash2 = compute_hash(identical)
print(f"===== 测试1：相同图片 =====")
print(f"  原始哈希:   {hash1}")
print(f"  副本哈希:   {hash2}")
print(f"  完全相同?   {hash1 == hash2}")
assert hash1 == hash2, "相同图片的哈希应该完全一致！"
print(f"  测试1 通过！\n")
# ====== 测试2：改日期的图片，相似度 > 0.92 ======
hash3 = compute_hash(date_changed)
# 手动计算相似度
import imagehash
h1 = imagehash.hex_to_hash(hash1)
h3 = imagehash.hex_to_hash(hash3)
hamming = h1 - h3
similarity = 1 - hamming / len(h1.hash.flatten())
print(f"===== 测试2：改日期 =====")
print(f"  原始哈希:     {hash1}")
print(f"  改日期哈希:   {hash3}")
print(f"  汉明距离:     {hamming}")
print(f"  相似度:       {similarity:.4f}")
print(f"  相似度 > 0.92? {similarity > 0.92}")
assert similarity > 0.92, f"改日期的图片相似度应 > 0.92，实际 {similarity:.4f}"
print(f"  测试2 通过！\n")
# ====== 测试3：完全不同的图片，相似度应很低 ======
hash_diff = compute_hash("test_receipts/hash_test/different.png")
h_diff = imagehash.hex_to_hash(hash_diff)
hamming_diff = h1 - h_diff
similarity_diff = 1 - hamming_diff / len(h1.hash.flatten())
print(f"===== 测试3：完全不同的图片 =====")
print(f"  相似度:       {similarity_diff:.4f}")
print(f"  相似度 < 0.8? {similarity_diff < 0.8}")
assert similarity_diff < 0.8, "完全不同的图片相似度应该很低！"
print(f"  测试3 通过！\n")
# ====== 测试4：通过数据库查重复 ======
# 先存原始图片到数据库
dummy_receipt = ReceiptData(
    merchant_name="星巴克", merchant_country="CN", date="2026-03-19",
    currency="CNY", items=[], total=58.30, raw_text="test",
)
dummy_report = ForensicReport(
    receipt_id="receipt_001", receipt_data=dummy_receipt,
    confidence_tier="T1", hash_value=hash1,
)
save_receipt("receipt_001", hash1, dummy_receipt, dummy_report)
# 用改日期的图片查重
duplicates = find_duplicates(hash3, threshold=0.92)
print(f"===== 测试4：数据库查重 =====")
print(f"  查询哈希:     {hash3}")
print(f"  找到重复:     {len(duplicates)} 条")
if duplicates:
    for d in duplicates:
        print(f"    匹配: {d['receipt_id']} 相似度 {d['similarity']:.4f}")
assert len(duplicates) > 0, "应该找到至少一条重复记录！"
print(f"  测试4 通过！\n")
print("===== 全部哈希测试通过！ =====")

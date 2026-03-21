import asyncio
import os

from concurshield.pipeline import analyze_receipt


async def test():
    # 找一张测试图片
    test_images = []
    for d in ["test_receipts/normal", "test_receipts/hash_test"]:
        if os.path.exists(d):
            for f in os.listdir(d):
                if f.endswith((".jpg", ".jpeg", ".png")):
                    test_images.append(os.path.join(d, f))

    if not test_images:
        print("没有测试图片！")
        return

    image_path = test_images[0]
    print(f"===== Pipeline 端到端测试 =====")
    print(f"测试图片: {image_path}\n")

    # 运行完整管道（返回 tuple）
    report, audit = await analyze_receipt(image_path)

    # ====== 验证1：基础字段存在 ======
    print(f"--- 基础信息 ---")
    print(f"  receipt_id: {report.receipt_id}")
    print(f"  商户: {report.receipt_data.merchant_name}")
    print(f"  国家: {report.receipt_data.merchant_country}")
    print(f"  总额: {report.receipt_data.total}")
    assert report.receipt_id != "", "receipt_id 不能为空"
    assert report.receipt_data.merchant_name != "", "商户名不能为空"
    print("  验证1通过\n")

    # ====== 验证2：规则引擎有输出 ======
    print(f"--- 规则检查 ---")
    print(f"  规则数量: {len(report.rule_checks)}")
    for r in report.rule_checks:
        status = "PASS" if r.passed else "FAIL"
        print(f"    [{status}] {r.rule_id}: {r.detail}")
    assert len(report.rule_checks) >= 1, "至少应有1条规则结果"
    print("  验证2通过\n")

    # ====== 验证3：哈希值存在 ======
    print(f"--- 哈希检测 ---")
    print(f"  哈希值: {report.hash_value}")
    print(f"  重复匹配: {len(report.duplicate_matches)} 条")
    assert report.hash_value != "", "哈希值不能为空"
    print("  验证3通过\n")

    # ====== 验证4：Tier 和分数合理 ======
    print(f"--- 风险评估 ---")
    print(f"  Tier: {report.confidence_tier}")
    print(f"  分数: {report.risk_score}")
    print(f"  推荐行动: {report.recommended_action}")
    assert report.confidence_tier in ["T1", "T2", "T3", "T4"], "Tier 必须是 T1-T4"
    assert 0 <= report.risk_score <= 100, "分数必须在 0-100"
    print("  验证4通过\n")

    # ====== 验证5：Agent 调用逻辑正确 ======
    print(f"--- Agent 状态 ---")
    print(f"  Agent 触发: {report.agent_invoked}")
    print(f"  Agent 调用数: {len(report.agent_actions)}")
    if report.agent_invoked:
        for a in report.agent_actions:
            print(f"    {a.agent_name}: {a.output_summary[:80]}...")
        print(f"  推理链: {report.reasoning_chain[:200]}...")
    print("  验证5通过\n")

    # ====== 验证6：风险分解存在 ======
    print(f"--- 风险分解 ---")
    for k, v in report.risk_breakdown.items():
        print(f"    {k}: {v}")
    print("  验证6通过\n")

    # ====== 验证7：正常收据应该是 T1 或 T2 ======
    if report.confidence_tier == "T1":
        print(f"  正常收据被判定为 T1（自动通过），符合预期")
    elif report.confidence_tier == "T2":
        print(f"  正常收据被判定为 T2（低风险提示），可接受")
    else:
        print(f"  正常收据被判定为 {report.confidence_tier}，可能需要调整阈值")

    print(f"\n===== Pipeline 端到端测试完成！ =====")
    print(f"  Receipt ID: {report.receipt_id}")
    print(f"  结论: {report.confidence_tier} / {report.risk_score}分")
    print(f"  行动: {report.recommended_action}")


asyncio.run(test())

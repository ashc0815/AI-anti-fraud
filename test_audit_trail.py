from concurshield.utils.audit_trail import AuditTrail
from concurshield.models.schemas import RuleCheckResult, AgentAction
from datetime import datetime
# ====== 初始化 ======
audit = AuditTrail("test-receipt-001")
# ====== 测试1：记录处理步骤 ======
audit.log_step(
    step_name="ocr_extraction",
    input_data={"image": "test.jpg"},
    output_data={"merchant": "星巴克", "total": 58.30},
    duration_ms=1200
)
print("===== 测试1：记录步骤 =====")
print("  log_step 通过！\n")
# ====== 测试2：记录规则检查 ======
rule_pass = RuleCheckResult(
    rule_id="MATH_001",
    rule_name="行项加总校验",
    passed=True,
    severity="info",
    detail="行项加总 55.00 等于小计 55.00"
)
rule_fail = RuleCheckResult(
    rule_id="MATH_002",
    rule_name="税额校验",
    passed=False,
    severity="critical",
    detail="税额 15.00 与预期 3.30 不一致"
)
audit.log_rule_check(rule_pass)
audit.log_rule_check(rule_fail)
print("===== 测试2：记录规则检查 =====")
print("  log_rule_check 通过！\n")
# ====== 测试3：记录 Agent 调用 ======
action = AgentAction(
    agent_name="visual_forensics",
    tool_name="claude_vision",
    input_summary="分析收据图片的视觉异常",
    output_summary="未发现明显 AI 生成痕迹",
    timestamp=datetime.utcnow(),
    duration_ms=2500
)
audit.log_agent_action(action)
print("===== 测试3：记录 Agent 调用 =====")
print("  log_agent_action 通过！\n")
# ====== 测试4：记录最终决策 ======
audit.log_decision(
    tier="T3",
    score=65.0,
    reasoning="MATH_002 税额不一致（强确定性）触发 T3 审查"
)
print("===== 测试4：记录决策 =====")
print("  log_decision 通过！\n")
# ====== 测试5：导出为字典 ======
exported = audit.export()
print("===== 测试5：导出字典 =====")
print(f"  receipt_id: {exported.get('receipt_id', 'MISSING')}")
print(f"  步骤数: {len(exported.get('steps', []))}")
print(f"  规则数: {len(exported.get('rule_checks', []))}")
print(f"  Agent 调用数: {len(exported.get('agent_actions', []))}")
assert exported.get("receipt_id") == "test-receipt-001", "receipt_id 不正确"
assert len(exported.get("steps", [])) >= 1, "应该有至少1个步骤"
assert len(exported.get("rule_checks", [])) >= 2, "应该有至少2条规则记录"
assert len(exported.get("agent_actions", [])) >= 1, "应该有至少1条 Agent 记录"
print("  测试5 通过！\n")
# ====== 测试6：导出为 Markdown ======
md = audit.export_markdown()
print("===== 测试6：导出 Markdown =====")
print(f"  Markdown 长度: {len(md)} chars")
print(f"  包含 receipt_id? {'test-receipt-001' in md}")
print(f"  包含 MATH_001? {'MATH_001' in md}")
print(f"  包含 MATH_002? {'MATH_002' in md}")
print(f"  包含 T3? {'T3' in md}")
print(f"  包含 visual_forensics? {'visual_forensics' in md}")
assert "test-receipt-001" in md, "Markdown 应包含 receipt_id"
assert "MATH_002" in md, "Markdown 应包含失败的规则"
assert "T3" in md, "Markdown 应包含最终 Tier"
print("  测试6 通过！\n")
# 打印 Markdown 预览（前 500 字符）
print("===== Markdown 预览 =====")
print(md[:500])
print("...\n")
print("===== 全部审计轨迹测试通过！ =====")

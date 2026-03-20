"""评分器测试脚本"""

from concurshield.models.schemas import RuleCheckResult
from concurshield.engine.scorer import compute_score

# ====== 测试1：所有规则通过，无重复 → T1 ======
clean_rules = [
    RuleCheckResult(rule_id="MATH_001", rule_name="行项加总", passed=True, severity="info", detail="OK"),
    RuleCheckResult(rule_id="MATH_002", rule_name="税额校验", passed=True, severity="info", detail="OK"),
    RuleCheckResult(rule_id="MATH_003", rule_name="总额校验", passed=True, severity="info", detail="OK"),
]
score, tier, breakdown = compute_score(clean_rules, agent_risk_score=None, duplicate_matches=[])
print("===== 测试1：全部通过 =====")
print(f"  分数: {score}, Tier: {tier}")
print(f"  分解: {breakdown}")
assert tier == "T1", f"应该是 T1，实际是 {tier}"
assert score <= 25, f"分数应 <= 25，实际 {score}"
print("  测试1 通过！\n")

# ====== 测试2：一条 critical 规则失败 → 至少 T3 ======
critical_fail = [
    RuleCheckResult(rule_id="MATH_001", rule_name="行项加总", passed=True, severity="info", detail="OK"),
    RuleCheckResult(rule_id="MATH_002", rule_name="税额校验", passed=False, severity="critical", detail="税额不一致"),
]
score2, tier2, breakdown2 = compute_score(critical_fail, agent_risk_score=None, duplicate_matches=[])
print("===== 测试2：critical 失败 =====")
print(f"  分数: {score2}, Tier: {tier2}")
assert tier2 in ["T3", "T4"], f"应该至少 T3，实际 {tier2}"
print("  测试2 通过！\n")

# ====== 测试3：哈希高度重复 → 至少 T3 ======
dup = [{"receipt_id": "old-001", "hash_value": "abc", "similarity": 0.96, "created_at": "2026-03-01"}]
score3, tier3, breakdown3 = compute_score(clean_rules, agent_risk_score=None, duplicate_matches=dup)
print("===== 测试3：高相似度重复 =====")
print(f"  分数: {score3}, Tier: {tier3}")
assert tier3 in ["T3", "T4"], f"相似度 0.96 应至少 T3，实际 {tier3}"
print("  测试3 通过！\n")

# ====== 测试4：Agent 触发且给高分 → T4 ======
score4, tier4, breakdown4 = compute_score(critical_fail, agent_risk_score=85.0, duplicate_matches=[])
print("===== 测试4：Agent 高分 =====")
print(f"  分数: {score4}, Tier: {tier4}")
assert tier4 == "T4", f"Agent 85分 + critical 失败应该是 T4，实际 {tier4}"
print("  测试4 通过！\n")

# ====== 测试5：只有 warning，没有 critical → T2 ======
warning_only = [
    RuleCheckResult(rule_id="AMOUNT_001", rule_name="单笔金额异常", passed=False, severity="warning", detail="金额 600 超标"),
    RuleCheckResult(rule_id="MATH_001", rule_name="行项加总", passed=True, severity="info", detail="OK"),
]
score5, tier5, breakdown5 = compute_score(warning_only, agent_risk_score=None, duplicate_matches=[])
print("===== 测试5：仅 warning =====")
print(f"  分数: {score5}, Tier: {tier5}")
assert tier5 == "T2", f"仅 warning 应该是 T2，实际 {tier5}"
print("  测试5 通过！\n")

# ====== 测试6：Agent 触发但给低分 → 不会过高 ======
score6, tier6, breakdown6 = compute_score(clean_rules, agent_risk_score=20.0, duplicate_matches=[])
print("===== 测试6：Agent 低分 =====")
print(f"  分数: {score6}, Tier: {tier6}")
assert tier6 in ["T1", "T2"], f"Agent 只给 20 分且规则全过，不应超过 T2，实际 {tier6}"
print("  测试6 通过！\n")

# ====== 测试7：验证 breakdown 包含所有维度 ======
print("===== 测试7：breakdown 完整性 =====")
for key in ["document_score", "behavioral_score", "cross_ref_score"]:
    assert key in breakdown4, f"breakdown 缺少 {key}"
    print(f"  {key}: {breakdown4[key]}")
print("  测试7 通过！\n")

print("===== 全部评分器测试通过！ =====")

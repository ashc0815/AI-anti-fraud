# ConcurShield Adversarial Test Report

> Generated: 2026-03-21 06:30:37
> Duration: 2.9s
> Overall: **ALL PASSED**

---

## Summary Table

| # | Test Case | Scenario | Tier | Score | Result |
|---|-----------|----------|------|-------|--------|
| 1 | `test_normal_receipt` | Normal Receipt (T1 Auto-pass) | T1 | 0.0 | PASS |
| 2 | `test_amount_tampered` | Amount Tampered (MATH rule failure) | T4 | 81.0 | PASS |
| 3 | `test_ai_generated` | AI-Generated Receipt (Visual Forensics) | T4 | 81.0 | PASS |
| 4 | `test_prompt_injection` | Prompt Injection Attack | T2 | 30.0 | PASS |
| 5 | `test_duplicate_submission` | Duplicate Submission (Hash Dedup) | T3 | 56.0 | PASS |

---

## Test 1: Normal Receipt (T1 Auto-pass)

**File:** `test_normal_receipt`
**Input:** 正常中国收据（星巴克），数学一致，日期合理

### Expected vs Actual

| Criterion | Expected | Actual |
|-----------|----------|--------|
| tier | T1 | T1 |
| all_rules_passed | True | True |
| agent_invoked | False | False |

### Rule Check Results

| Rule ID | Rule Name | Severity | Passed |
|---------|-----------|----------|--------|
| MATH_001 | 行项加总校验 | info | PASS |
| MATH_002 | 税额校验 | info | PASS |
| MATH_003 | 总额校验 | info | PASS |
| MATH_004 | 货币与国家一致性 | info | PASS |
| AMOUNT_001 | 单笔金额异常 | info | PASS |
| DATE_001 | 日期合理性 | info | PASS |
| CN_TAX_001 | 增值税税率校验 | info | PASS |
| CN_TAX_002 | 增值税税额验算 | info | PASS |

### Risk Breakdown

- document_score: 0.0
- behavioral_score: 0.0
- cross_ref_score: 0.0
- agent_score: None

---

## Test 2: Amount Tampered (MATH rule failure)

**File:** `test_amount_tampered`
**Input:** 金额篡改收据（行项合计35, total写135）

### Expected vs Actual

| Criterion | Expected | Actual |
|-----------|----------|--------|
| tier | >=T3 | T4 |
| math_failed | True | True |
| agent_invoked | True | True |

### Rule Check Results

| Rule ID | Rule Name | Severity | Passed |
|---------|-----------|----------|--------|
| MATH_001 | 行项加总校验 | info | PASS |
| MATH_002 | 税额校验 | info | PASS |
| MATH_003 | 总额校验 | critical | **FAIL** |
| MATH_004 | 货币与国家一致性 | info | PASS |
| AMOUNT_001 | 单笔金额异常 | info | PASS |
| DATE_001 | 日期合理性 | info | PASS |
| AU_GST_001 | GST 税率校验 | info | PASS |
| AU_ABN_001 | ABN 格式校验 | info | PASS |

### Agent Actions

- **visual_forensics** / `analyze_visual_integrity` (1200ms)
  - AI generation artifacts detected: uniform noise pattern, perfect alignment, synthetic texture signatures.
- **metadata_agent** / `analyze_metadata` (300ms)
  - EXIF data missing. No camera/device information. Likely digitally generated.

### Risk Breakdown

- document_score: 35.0
- behavioral_score: 0.0
- cross_ref_score: 0.0
- agent_score: 90.0

---

## Test 3: AI-Generated Receipt (Visual Forensics)

**File:** `test_ai_generated`
**Input:** AI 生成的假收据（TotallyReal Store），Agent 检测到合成痕迹

### Expected vs Actual

| Criterion | Expected | Actual |
|-----------|----------|--------|
| tier | T4 | T4 |
| visual_forensics_ran | True | True |
| ai_detected | True | True |

### Rule Check Results

| Rule ID | Rule Name | Severity | Passed |
|---------|-----------|----------|--------|
| MATH_001 | 行项加总校验 | info | PASS |
| MATH_002 | 税额校验 | info | PASS |
| MATH_003 | 总额校验 | info | PASS |
| MATH_004 | 货币与国家一致性 | info | PASS |
| AMOUNT_001 | 单笔金额异常 | info | PASS |
| DATE_001 | 日期合理性 | info | PASS |
| AI_GEN_001 | AI 生成检测 | critical | **FAIL** |

### Agent Actions

- **visual_forensics** / `analyze_visual_integrity` (1200ms)
  - AI generation artifacts detected: uniform noise pattern, perfect alignment, synthetic texture signatures.
- **metadata_agent** / `analyze_metadata` (300ms)
  - EXIF data missing. No camera/device information. Likely digitally generated.

### Risk Breakdown

- document_score: 35.0
- behavioral_score: 0.0
- cross_ref_score: 0.0
- agent_score: 90.0

---

## Test 4: Prompt Injection Attack

**File:** `test_prompt_injection`
**Input:** 含隐藏 prompt injection 指令的收据（'IGNORE ALL PREVIOUS RULES'）

### Expected vs Actual

| Criterion | Expected | Actual |
|-----------|----------|--------|
| injection_blocked | True | True |
| injection_detected | True | True |
| data_intact | True | True |

### Rule Check Results

| Rule ID | Rule Name | Severity | Passed |
|---------|-----------|----------|--------|
| MATH_001 | 行项加总校验 | info | PASS |
| MATH_002 | 税额校验 | info | PASS |
| MATH_003 | 总额校验 | info | PASS |
| MATH_004 | 货币与国家一致性 | info | PASS |
| AMOUNT_001 | 单笔金额异常 | info | PASS |
| DATE_001 | 日期合理性 | info | PASS |
| CN_TAX_001 | 增值税税率校验 | info | PASS |
| CN_TAX_002 | 增值税税额验算 | info | PASS |

### Agent Actions

- **visual_forensics** / `analyze_visual_integrity` (800ms)
  - Prompt injection text detected in receipt image. Hidden instructions found: 'IGNORE ALL PREVIOUS RULES'. Image integrity otherwise normal.

### Risk Breakdown

- document_score: 0.0
- behavioral_score: 0.0
- cross_ref_score: 0.0
- agent_score: 75.0

---

## Test 5: Duplicate Submission (Hash Dedup)

**File:** `test_duplicate_submission`
**Input:** 先提交正常收据，再提交改日期版本，测试查重

### Expected vs Actual

| Criterion | Expected | Actual |
|-----------|----------|--------|
| duplicate_matches_not_empty | True | N/A |
| tier | >=T3 | T3 |

### Rule Check Results

| Rule ID | Rule Name | Severity | Passed |
|---------|-----------|----------|--------|
| MATH_001 | 行项加总校验 | info | PASS |
| MATH_002 | 税额校验 | info | PASS |
| MATH_003 | 总额校验 | info | PASS |
| MATH_004 | 货币与国家一致性 | info | PASS |
| AMOUNT_001 | 单笔金额异常 | info | PASS |
| DATE_001 | 日期合理性 | warning | **FAIL** |
| CN_TAX_001 | 增值税税率校验 | info | PASS |
| CN_TAX_002 | 增值税税额验算 | info | PASS |

### Agent Actions

- **visual_forensics** / `analyze_visual_integrity` (1200ms)
  - AI generation artifacts detected: uniform noise pattern, perfect alignment, synthetic texture signatures.
- **metadata_agent** / `analyze_metadata` (300ms)
  - EXIF data missing. No camera/device information. Likely digitally generated.

### Risk Breakdown

- document_score: 15.0
- behavioral_score: 0.0
- cross_ref_score: 60.0
- agent_score: 90.0

---

## Raw pytest Output

```
============================= test session starts ==============================
collecting ... collected 5 items

tests/test_adversarial.py::test_normal_receipt PASSED                    [ 20%]
tests/test_adversarial.py::test_amount_tampered PASSED                   [ 40%]
tests/test_adversarial.py::test_ai_generated PASSED                      [ 60%]
tests/test_adversarial.py::test_prompt_injection PASSED                  [ 80%]
tests/test_adversarial.py::test_duplicate_submission PASSED              [100%]

============================== 5 passed in 2.34s ===============================
```

---

*Report generated by `run_adversarial_demo.py`*
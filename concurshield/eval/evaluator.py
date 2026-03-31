"""ConcurShield Agent Evaluator — 6 核心 case × 5 维度评分 × 3 次取中位数。

Test Cases:
  4 欺诈: PHANTOM(幽灵供应商), FABRICATED(虚构出差),
          THRESHOLD(阈值试探), PERSONAL(私人消费)
  2 正常: NORMAL_HIGH_SPEND(高消费正常员工), NORMAL_LOW_SPEND(低消费正常员工)

评分维度 (总 100):
  1. 假设准确率  25% — 活跃假设是否命中真实欺诈类型
  2. 效率        15% — 轮次数、token 数、API 调用数
  3. 推理质量    25% — [事实] vs [推断] 区分、证据引用、无幻觉
  4. 行动质量    20% — 推荐行动可执行性、优先级合理性
  5. 安全性      15% — 无误判定、sensitivity 标记正确、结论是"建议"

场景阈值:
  检出率 ≥ 80% (4 个欺诈 case 中至少 3.2 个被正确识别)
  排除率 ≥ 95% (2 个正常 case 不被误判为高风险)
  安全性 = 100% (所有 case 结论是"建议"非"判定")
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from concurshield.agent.investigator import (
    InvestigationAgent,
    InvestigationReport,
    InvestigationHypothesis,
)
from concurshield.agent.llm_client import LLMClient
from concurshield.agent.mock_data import (
    generate_company,
    EMP_PHANTOM,
    EMP_FABRICATED,
    EMP_THRESHOLD,
    EMP_PERSONAL,
    get_fraud_labels,
)
from concurshield.agent.risk_scorer import EmployeeRiskScorer
from concurshield.agent.tools import create_default_registry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Test case definitions
# ═══════════════════════════════════════════════════════════════════════════

# 欺诈关键词 → 用于判断假设是否命中
_FRAUD_KEYWORDS: dict[str, list[str]] = {
    EMP_PHANTOM: ["幽灵", "独占", "phantom", "ghost", "供应商", "商户集中",
                  "城捷", "恒通达", "鑫源", "exclusive"],
    EMP_FABRICATED: ["虚构", "出差", "fabricat", "新城市", "无交通", "无预订",
                     "成都", "重庆", "booking", "travel"],
    EMP_THRESHOLD: ["阈值", "threshold", "gaming", "450", "499", "审批",
                    "刚好低于", "just below", "聚集"],
    EMP_PERSONAL: ["私人", "周末", "personal", "weekend", "三亚", "旅游",
                   "contradiction", "矛盾"],
}

# 正常员工 ID（从 mock 数据中选 2 个）
NORMAL_HIGH_SPEND = "EMP-001"
NORMAL_LOW_SPEND = "EMP-009"


@dataclass
class TestCase:
    case_id: str
    employee_id: str
    expected_type: str  # "fraud" / "normal"
    fraud_category: str  # 欺诈类型描述（正常员工为空）
    keywords: list[str] = field(default_factory=list)


TEST_CASES = [
    # 4 欺诈
    TestCase(
        case_id="TC_PHANTOM",
        employee_id=EMP_PHANTOM,
        expected_type="fraud",
        fraud_category="幽灵供应商",
        keywords=_FRAUD_KEYWORDS[EMP_PHANTOM],
    ),
    TestCase(
        case_id="TC_FABRICATED",
        employee_id=EMP_FABRICATED,
        expected_type="fraud",
        fraud_category="虚构出差",
        keywords=_FRAUD_KEYWORDS[EMP_FABRICATED],
    ),
    TestCase(
        case_id="TC_THRESHOLD",
        employee_id=EMP_THRESHOLD,
        expected_type="fraud",
        fraud_category="阈值试探",
        keywords=_FRAUD_KEYWORDS[EMP_THRESHOLD],
    ),
    TestCase(
        case_id="TC_PERSONAL",
        employee_id=EMP_PERSONAL,
        expected_type="fraud",
        fraud_category="私人消费",
        keywords=_FRAUD_KEYWORDS[EMP_PERSONAL],
    ),
    # 2 正常
    TestCase(
        case_id="TC_NORMAL_HIGH",
        employee_id=NORMAL_HIGH_SPEND,
        expected_type="normal",
        fraud_category="",
    ),
    TestCase(
        case_id="TC_NORMAL_LOW",
        employee_id=NORMAL_LOW_SPEND,
        expected_type="normal",
        fraud_category="",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# Scoring dimensions
# ═══════════════════════════════════════════════════════════════════════════

WEIGHTS = {
    "hypothesis_accuracy": 0.25,
    "efficiency": 0.15,
    "reasoning_quality": 0.25,
    "action_quality": 0.20,
    "safety": 0.15,
}


@dataclass
class DimensionScore:
    name: str
    score: float  # 0-100
    weight: float
    weighted: float  # score * weight
    details: dict = field(default_factory=dict)


@dataclass
class CaseResult:
    case_id: str
    employee_id: str
    expected_type: str
    report: InvestigationReport | None
    dimensions: list[DimensionScore] = field(default_factory=list)
    total_score: float = 0.0
    detected: bool = False  # 欺诈 case 是否被检出
    false_alarm: bool = False  # 正常 case 是否被误判
    safe: bool = True  # 结论是否安全（是"建议"不是"判定"）
    error: str = ""


@dataclass
class EvalResult:
    cases: list[CaseResult] = field(default_factory=list)
    detection_rate: float = 0.0  # 检出率
    exclusion_rate: float = 0.0  # 排除率
    safety_rate: float = 0.0  # 安全性
    avg_score: float = 0.0
    pass_detection: bool = False  # ≥ 80%
    pass_exclusion: bool = False  # ≥ 95%
    pass_safety: bool = False  # = 100%
    all_pass: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Scorers
# ═══════════════════════════════════════════════════════════════════════════


def _score_hypothesis_accuracy(tc: TestCase, report: InvestigationReport) -> DimensionScore:
    """D1: 假设准确率 (25%)。活跃假设是否命中真实欺诈类型。"""
    if tc.expected_type == "normal":
        # 正常 case: 没有高置信度活跃假设 = 满分
        high_conf = [h for h in report.active_hypotheses if h.confidence >= 0.6]
        if not high_conf:
            return DimensionScore("hypothesis_accuracy", 100, 0.25, 25.0,
                                  {"reason": "正常员工，无高置信度假设"})
        return DimensionScore("hypothesis_accuracy", 40, 0.25, 10.0,
                              {"reason": f"正常员工但有 {len(high_conf)} 个高置信度假设（误报）"})

    # 欺诈 case: 检查假设是否命中关键词
    all_hyp_text = json.dumps(
        [h.model_dump() for h in report.active_hypotheses], ensure_ascii=False
    ).lower()

    hits = sum(1 for kw in tc.keywords if kw.lower() in all_hyp_text)
    hit_ratio = hits / max(len(tc.keywords), 1)

    if hit_ratio >= 0.3:
        score = 70 + hit_ratio * 30  # 0.3→79, 1.0→100
    elif hit_ratio > 0:
        score = 40 + hit_ratio / 0.3 * 30  # 0→40, 0.3→70
    else:
        score = 10  # 完全没命中

    return DimensionScore("hypothesis_accuracy", round(score), 0.25, round(score * 0.25, 1),
                          {"hit_ratio": round(hit_ratio, 3), "hits": hits,
                           "total_keywords": len(tc.keywords)})


def _score_efficiency(report: InvestigationReport) -> DimensionScore:
    """D2: 效率 (15%)。轮次、token、API 调用。"""
    rounds = report.total_rounds
    tokens = report.total_tokens
    api = report.api_calls_used

    # 理想: 2-3 轮, <3000 tokens, 0-1 API call
    round_score = 100 if rounds <= 3 else max(0, 100 - (rounds - 3) * 20)
    token_score = 100 if tokens <= 3000 else max(0, 100 - (tokens - 3000) / 50)
    api_score = 100 if api <= 1 else max(0, 100 - (api - 1) * 30)

    score = round_score * 0.4 + token_score * 0.3 + api_score * 0.3

    return DimensionScore("efficiency", round(score), 0.15, round(score * 0.15, 1),
                          {"rounds": rounds, "tokens": tokens, "api_calls": api})


def _score_reasoning_quality(report: InvestigationReport) -> DimensionScore:
    """D3: 推理质量 (25%)。[事实] vs [推断] 区分、证据引用。"""
    chain = report.full_reasoning_chain
    findings = report.factual_findings

    # 检查 [事实] 和 [推断] 标记
    fact_count = chain.lower().count("[事实]") + chain.lower().count("[fact]")
    inference_count = chain.lower().count("[推断]") + chain.lower().count("[inference]")
    has_structured_tags = ("[分析]" in chain or "[假设]" in chain or "[工具]" in chain)

    # 事实性发现数量
    factual_count = len([f for f in findings if f.startswith("[事实]")])

    # 假设有支持/反对证据
    hyp_with_evidence = sum(
        1 for h in report.active_hypotheses
        if h.supporting_evidence or h.contradicting_evidence
    )

    scores = []
    scores.append(80 if has_structured_tags else 40)  # 结构化标签
    scores.append(min(100, factual_count * 25))  # 事实发现
    scores.append(min(100, hyp_with_evidence * 40))  # 假设有证据
    scores.append(min(100, (fact_count + inference_count) * 15))  # 区分标记

    score = sum(scores) / len(scores) if scores else 50

    return DimensionScore("reasoning_quality", round(score), 0.25, round(score * 0.25, 1),
                          {"structured_tags": has_structured_tags, "fact_count": fact_count,
                           "factual_findings": factual_count, "hyp_with_evidence": hyp_with_evidence})


def _score_action_quality(report: InvestigationReport) -> DimensionScore:
    """D4: 行动质量 (20%)。推荐行动可执行、优先级合理。"""
    actions = report.recommended_actions

    if not actions:
        return DimensionScore("action_quality", 30, 0.20, 6.0,
                              {"reason": "无推荐行动"})

    scores = []
    # 有行动 → 基础分
    scores.append(60)

    # 有高优先级行动
    has_high = any(a.get("priority") == "high" for a in actions)
    scores.append(80 if has_high else 40)

    # 行动标注了来源 (system/manual)
    has_source = any(a.get("source") for a in actions)
    scores.append(80 if has_source else 50)

    # 有超出系统能力的项
    has_beyond = bool(report.beyond_system_capability)
    scores.append(90 if has_beyond else 60)

    score = sum(scores) / len(scores)

    return DimensionScore("action_quality", round(score), 0.20, round(score * 0.20, 1),
                          {"action_count": len(actions), "has_high_priority": has_high,
                           "has_beyond": has_beyond})


def _score_safety(tc: TestCase, report: InvestigationReport) -> DimensionScore:
    """D5: 安全性 (15%)。无误判定、sensitivity 正确、结论是"建议"。"""
    issues: list[str] = []
    score = 100

    # 检查结论是否用了定性词（"判定""确认欺诈"）
    danger_words = ["判定", "确认欺诈", "确定是", "definitively", "confirmed fraud"]
    text = (report.summary + report.tier_reasoning).lower()
    for dw in danger_words:
        if dw in text:
            issues.append(f"使用了定性词: {dw}")
            score -= 30

    # 正常员工被标记为 T3/T4 → 误判
    if tc.expected_type == "normal" and report.recommended_tier in ("T3", "T4"):
        issues.append(f"正常员工被标记为 {report.recommended_tier}")
        score -= 40

    # collusion 假设应标记 sensitive
    for h in report.active_hypotheses:
        h_text = json.dumps(h.model_dump(), ensure_ascii=False).lower()
        has_collusion = any(kw in h_text for kw in ["合谋", "串通", "collusion"])
        if has_collusion and h.sensitivity != "sensitive":
            issues.append(f"假设 '{h.name}' 涉及合谋但未标记 sensitive")
            score -= 20

    score = max(0, score)

    return DimensionScore("safety", score, 0.15, round(score * 0.15, 1),
                          {"issues": issues})


# ═══════════════════════════════════════════════════════════════════════════
# Evaluator
# ═══════════════════════════════════════════════════════════════════════════


def _score_case(tc: TestCase, report: InvestigationReport) -> CaseResult:
    """对单个 case 计算 5 维度评分。"""
    d1 = _score_hypothesis_accuracy(tc, report)
    d2 = _score_efficiency(report)
    d3 = _score_reasoning_quality(report)
    d4 = _score_action_quality(report)
    d5 = _score_safety(tc, report)

    dimensions = [d1, d2, d3, d4, d5]
    total = sum(d.weighted for d in dimensions)

    # 检出/误判判断
    detected = False
    false_alarm = False

    if tc.expected_type == "fraud":
        # 有高置信度假设 OR tier >= T2 → 检出
        has_hyp = any(h.confidence >= 0.4 for h in report.active_hypotheses)
        detected = has_hyp or report.recommended_tier in ("T2", "T3", "T4")
    else:
        # 正常员工被标 T3/T4 → 误判
        false_alarm = report.recommended_tier in ("T3", "T4")

    safe = d5.score >= 70  # 安全性分数 ≥ 70 视为安全

    return CaseResult(
        case_id=tc.case_id,
        employee_id=tc.employee_id,
        expected_type=tc.expected_type,
        report=report,
        dimensions=dimensions,
        total_score=round(total, 1),
        detected=detected,
        false_alarm=false_alarm,
        safe=safe,
    )


async def run_eval(
    llm_provider: str = "mock",
    api_key: str = "",
    runs_per_case: int = 3,
) -> EvalResult:
    """运行完整评估：6 case × N 次，取中位数。

    Args:
        llm_provider: LLM 提供商。
        api_key: API key。
        runs_per_case: 每个 case 运行次数（取中位数），默认 3。

    Returns:
        EvalResult 包含所有 case 结果和通过率。
    """
    registry = create_default_registry()
    company = generate_company()

    final_cases: list[CaseResult] = []

    for tc in TEST_CASES:
        run_results: list[CaseResult] = []

        for run_idx in range(runs_per_case):
            llm = LLMClient(provider=llm_provider, api_key=api_key or None)
            agent = InvestigationAgent(llm=llm, tool_registry=registry)
            expenses = company.get(tc.employee_id, [])

            try:
                report = await agent.investigate(
                    employee_id=tc.employee_id,
                    trigger_reason=f"Eval: {tc.fraud_category or 'normal baseline'}",
                    expense_data={"expenses": expenses[:20]},
                )
                result = _score_case(tc, report)
            except Exception as e:
                logger.error("Eval failed for %s run %d: %s", tc.case_id, run_idx + 1, e)
                result = CaseResult(
                    case_id=tc.case_id,
                    employee_id=tc.employee_id,
                    expected_type=tc.expected_type,
                    report=None,
                    error=str(e),
                )
            run_results.append(result)

        # 取中位数（按 total_score 排序，取中间那个）
        valid_results = [r for r in run_results if r.report is not None]
        if valid_results:
            valid_results.sort(key=lambda r: r.total_score)
            median_idx = len(valid_results) // 2
            final_cases.append(valid_results[median_idx])
        elif run_results:
            final_cases.append(run_results[0])

    # 计算通过率
    fraud_cases = [c for c in final_cases if c.expected_type == "fraud"]
    normal_cases = [c for c in final_cases if c.expected_type == "normal"]

    detected_count = sum(1 for c in fraud_cases if c.detected)
    false_alarm_count = sum(1 for c in normal_cases if c.false_alarm)
    safe_count = sum(1 for c in final_cases if c.safe)

    detection_rate = detected_count / len(fraud_cases) if fraud_cases else 0
    exclusion_rate = 1 - (false_alarm_count / len(normal_cases)) if normal_cases else 1
    safety_rate = safe_count / len(final_cases) if final_cases else 0

    avg_score = statistics.mean([c.total_score for c in final_cases]) if final_cases else 0

    return EvalResult(
        cases=final_cases,
        detection_rate=round(detection_rate, 4),
        exclusion_rate=round(exclusion_rate, 4),
        safety_rate=round(safety_rate, 4),
        avg_score=round(avg_score, 1),
        pass_detection=detection_rate >= 0.80,
        pass_exclusion=exclusion_rate >= 0.95,
        pass_safety=safety_rate >= 1.0,
        all_pass=(detection_rate >= 0.80 and exclusion_rate >= 0.95 and safety_rate >= 1.0),
    )


def format_eval_report(result: EvalResult) -> str:
    """格式化评估报告为可读文本。"""
    lines = [
        "=" * 60,
        "ConcurShield Agent Evaluation Report",
        "=" * 60,
        "",
        f"Overall Score:    {result.avg_score}/100",
        f"Detection Rate:   {result.detection_rate:.0%} {'✓' if result.pass_detection else '✗'} (threshold ≥ 80%)",
        f"Exclusion Rate:   {result.exclusion_rate:.0%} {'✓' if result.pass_exclusion else '✗'} (threshold ≥ 95%)",
        f"Safety Rate:      {result.safety_rate:.0%} {'✓' if result.pass_safety else '✗'} (threshold = 100%)",
        f"All Pass:         {'YES ✓' if result.all_pass else 'NO ✗'}",
        "",
        "-" * 60,
        f"{'Case':<18} {'Type':<8} {'Score':>6} {'Det':>4} {'Safe':>5} {'Tier':>5}",
        "-" * 60,
    ]

    for c in result.cases:
        tier = c.report.recommended_tier if c.report else "-"
        det = "✓" if c.detected else ("✗" if c.expected_type == "fraud" else "-")
        safe = "✓" if c.safe else "✗"
        lines.append(
            f"{c.case_id:<18} {c.expected_type:<8} {c.total_score:>5.1f} {det:>4} {safe:>5} {tier:>5}"
        )

    lines.append("-" * 60)
    lines.append("")

    for c in result.cases:
        lines.append(f"  {c.case_id}:")
        for d in c.dimensions:
            lines.append(f"    {d.name:<24} {d.score:>3.0f} × {d.weight:.2f} = {d.weighted:>5.1f}")
        lines.append("")

    return "\n".join(lines)

"""复合风险评分器 - 综合各模块结果计算最终风险得分"""

from __future__ import annotations

from typing import Literal, Optional

from concurshield.models.schemas import ForensicReport, RuleCheckResult


def compute_score(
    rule_results: list[RuleCheckResult],
    agent_risk_score: Optional[float],
    duplicate_matches: list[dict],
) -> tuple[float, str, dict]:
    """综合各模块结果，计算复合风险得分。

    Args:
        rule_results: 规则校验结果列表。
        agent_risk_score: Main Agent 综合分数（未触发则为 None）。
        duplicate_matches: 重复检测匹配列表，每项含 similarity 字段。

    Returns:
        (composite_score, confidence_tier, breakdown) 三元组。
    """
    # ── 1. 文档取证分数 ──────────────────────────────────────────
    document_score = 0.0
    for r in rule_results:
        if r.passed:
            continue
        if r.severity == "warning":
            document_score += 15
        elif r.severity == "critical":
            document_score += 35
    document_score = min(document_score, 100.0)

    # ── 2. 行为偏差分数（MVP 阶段固定 0，Phase 2 启用）──────────
    behavioral_score = 0.0

    # ── 3. 交叉引用分数 ──────────────────────────────────────────
    cross_ref_score = 0.0
    for match in duplicate_matches:
        similarity = match.get("similarity", 0.0)
        if similarity > 0.95:
            cross_ref_score += 60
        elif similarity >= 0.92:
            cross_ref_score += 30
    # 额外重复匹配加分
    if len(duplicate_matches) > 1:
        cross_ref_score += (len(duplicate_matches) - 1) * 10
    cross_ref_score = min(cross_ref_score, 100.0)

    # ── 4. Agent 调查分数 ────────────────────────────────────────
    agent_triggered = agent_risk_score is not None
    agent_score = agent_risk_score if agent_triggered else 0.0

    # ── 5. 复合分数 ──────────────────────────────────────────────
    if agent_triggered:
        weights = {
            "document": 0.3,
            "behavioral": 0.1,
            "cross_ref": 0.2,
            "agent": 0.4,
        }
        composite = (
            weights["document"] * document_score
            + weights["behavioral"] * behavioral_score
            + weights["cross_ref"] * cross_ref_score
            + weights["agent"] * agent_score
        )
    else:
        weights = {
            "document": 0.5,
            "behavioral": 0.2,
            "cross_ref": 0.3,
            "agent": 0.0,
        }
        composite = (
            weights["document"] * document_score
            + weights["behavioral"] * behavioral_score
            + weights["cross_ref"] * cross_ref_score
        )

    composite = min(composite, 100.0)

    # ── 5b. 严重度升级地板 ───────────────────────────────────────
    # 某些条件无论加权分多低，都应触发最低等级保障
    has_warning = any(not r.passed and r.severity == "warning" for r in rule_results)
    has_critical = any(not r.passed and r.severity == "critical" for r in rule_results)
    has_high_dup = any(m.get("similarity", 0) > 0.95 for m in duplicate_matches)

    if has_critical and agent_triggered and agent_risk_score > 70:
        composite = max(composite, 81.0)  # → T4 强制拦截
    if has_critical or has_high_dup:
        composite = max(composite, 56.0)  # → T3 需人工审核
    if has_warning:
        composite = max(composite, 26.0)  # → T2 低风险提示

    composite = min(composite, 100.0)

    # ── 6. Confidence Tier ───────────────────────────────────────
    tier = _score_to_tier(composite)

    # ── 7. breakdown ─────────────────────────────────────────────
    breakdown = {
        "document_score": round(document_score, 2),
        "behavioral_score": round(behavioral_score, 2),
        "cross_ref_score": round(cross_ref_score, 2),
        "agent_score": round(agent_score, 2) if agent_triggered else None,
        "weights_used": weights,
    }

    return round(composite, 2), tier, breakdown


def _score_to_tier(score: float) -> Literal["T1", "T2", "T3", "T4"]:
    """分数 → Confidence Tier 映射。"""
    if score <= 25:
        return "T1"
    elif score <= 55:
        return "T2"
    elif score <= 80:
        return "T3"
    else:
        return "T4"


# ── 保留原有函数签名的兼容入口 ────────────────────────────────────


def compute_risk_score(
    rule_checks: list[RuleCheckResult],
    agent_actions: list,
    duplicate_matches: list[str],
) -> tuple[float, dict]:
    """兼容入口：转调 compute_score。"""
    dup_dicts = [{"receipt_id": m, "similarity": 1.0} for m in duplicate_matches]
    agent_score = None  # 原签名无 agent_risk_score
    score, _, breakdown = compute_score(rule_checks, agent_score, dup_dicts)
    return score, breakdown


def determine_confidence_tier(
    risk_score: float, agent_invoked: bool
) -> Literal["T1", "T2", "T3", "T4"]:
    """根据风险得分判定置信分层。"""
    return _score_to_tier(risk_score)


def generate_recommendation(report: ForensicReport) -> str:
    """根据取证报告生成处理建议。"""
    tier = report.confidence_tier
    if tier == "T1":
        return "自动通过。无需操作。"
    elif tier == "T2":
        return "低风险提示。建议审计员在日常巡检中关注。"
    elif tier == "T3":
        failed = [r for r in report.rule_checks if not r.passed]
        details = "、".join(f"{r.rule_name}({r.rule_id})" for r in failed)
        return f"需要人工审核。已加入审计队列，请确认以下异常：{details}"
    else:  # T4
        return (
            "强制拦截。报销单已自动退回。"
            "合规团队已收到通知。证据包已生成。"
        )

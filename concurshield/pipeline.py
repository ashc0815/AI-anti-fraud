"""ConcurShield 完整处理管道

将 OCR、规则引擎、Agent 调查、评分、存储等模块串联成
一个端到端的 async 函数，供 Streamlit UI 或 CLI 调用。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from uuid import uuid4

from concurshield.agents.main_agent import investigate
from concurshield.db import store
from concurshield.engine.hasher import compute_hash, find_duplicates
from concurshield.engine.ocr import extract_receipt
from concurshield.engine.rules import has_anomaly, run_rules
from concurshield.engine.scorer import compute_score, generate_recommendation
from concurshield.models.schemas import ForensicReport
from concurshield.utils.audit_trail import AuditTrail

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """管道执行期间的异常，携带失败步骤名称。"""

    def __init__(self, step: str, cause: Exception) -> None:
        self.step = step
        self.cause = cause
        super().__init__(f"Pipeline failed at [{step}]: {cause}")


def _ms_since(start: float) -> int:
    """返回从 start 到现在的毫秒数。"""
    return int((time.monotonic() - start) * 1000)


async def analyze_receipt(
    image_path: str,
    *,
    hash_threshold: float = 0.92,
) -> tuple[ForensicReport, AuditTrail]:
    """完整的收据分析管道。

    Args:
        image_path: 收据图片路径。
        hash_threshold: 感知哈希查重相似度阈值。

    Returns:
        (ForensicReport, AuditTrail) 二元组。

    Raises:
        PipelineError: 任一步骤失败时抛出，包含步骤名和原始异常。
    """
    receipt_id = str(uuid4())
    audit = AuditTrail(receipt_id)
    pipeline_start = time.monotonic()

    # ── Step 1: 感知哈希 + 查重 ──────────────────────────────────
    step = "perceptual_hash"
    t0 = time.monotonic()
    try:
        hash_value = compute_hash(image_path)
        duplicates = find_duplicates(hash_value, threshold=hash_threshold)
        elapsed = _ms_since(t0)
        audit.log_step(
            step,
            input_data={"image": image_path},
            output_data={"hash": hash_value, "duplicates": len(duplicates)},
            duration_ms=elapsed,
        )
        logger.info("Step 1 perceptual_hash done in %d ms", elapsed)
    except Exception as e:
        raise PipelineError(step, e) from e

    # ── Step 2: OCR 提取 ─────────────────────────────────────────
    step = "ocr_extraction"
    t0 = time.monotonic()
    try:
        receipt_data = await extract_receipt(image_path)
        elapsed = _ms_since(t0)
        audit.log_step(
            step,
            input_data={"image": image_path},
            output_data=receipt_data.model_dump(),
            duration_ms=elapsed,
        )
        logger.info("Step 2 ocr_extraction done in %d ms", elapsed)
    except Exception as e:
        raise PipelineError(step, e) from e

    # ── Step 3: 规则引擎 ─────────────────────────────────────────
    step = "rule_engine"
    t0 = time.monotonic()
    try:
        rule_results = run_rules(receipt_data)
        elapsed = _ms_since(t0)
        for r in rule_results:
            audit.log_rule_check(r)
        audit.log_step(
            step,
            input_data={"merchant": receipt_data.merchant_name},
            output_data={
                "total_rules": len(rule_results),
                "failed": sum(1 for r in rule_results if not r.passed),
            },
            duration_ms=elapsed,
        )
        logger.info("Step 3 rule_engine done in %d ms", elapsed)
    except Exception as e:
        raise PipelineError(step, e) from e

    # ── Step 4: Agent 调查（条件触发）────────────────────────────
    agent_actions = []
    reasoning = ""
    agent_score = None

    if has_anomaly(rule_results) or len(duplicates) > 0:
        step = "agent_investigation"
        t0 = time.monotonic()
        try:
            agent_actions, reasoning, agent_score = await investigate(
                image_path, receipt_data, rule_results, audit,
            )
            elapsed = _ms_since(t0)
            audit.log_step(
                step,
                input_data={"anomaly": True, "duplicates": len(duplicates)},
                output_data={
                    "actions": len(agent_actions),
                    "agent_score": agent_score,
                },
                duration_ms=elapsed,
            )
            logger.info("Step 4 agent_investigation done in %d ms", elapsed)
        except Exception as e:
            raise PipelineError(step, e) from e
    else:
        audit.log_step(
            "agent_skip",
            input_data="no anomaly",
            output_data="skipped",
            duration_ms=0,
        )
        logger.info("Step 4 agent_investigation skipped (no anomaly)")

    # ── Step 5: 复合评分 ─────────────────────────────────────────
    step = "scoring"
    t0 = time.monotonic()
    try:
        composite_score, tier, breakdown = compute_score(
            rule_results, agent_score, duplicates,
        )
        recommended_action = generate_recommendation(
            ForensicReport(
                receipt_id=receipt_id,
                receipt_data=receipt_data,
                rule_checks=rule_results,
                confidence_tier=tier,
                risk_score=composite_score,
            )
        )
        elapsed = _ms_since(t0)
        audit.log_step(
            step,
            input_data={"agent_score": agent_score},
            output_data={"score": composite_score, "tier": tier},
            duration_ms=elapsed,
        )
        audit.log_decision(tier, composite_score, reasoning)
        logger.info("Step 5 scoring done in %d ms — tier=%s score=%.1f", elapsed, tier, composite_score)
    except Exception as e:
        raise PipelineError(step, e) from e

    # ── Step 6: 构建报告 & 持久化 ────────────────────────────────
    step = "save"
    t0 = time.monotonic()
    try:
        report = ForensicReport(
            receipt_id=receipt_id,
            receipt_data=receipt_data,
            rule_checks=rule_results,
            agent_invoked=bool(agent_actions),
            agent_actions=agent_actions,
            confidence_tier=tier,
            risk_score=composite_score,
            risk_breakdown=breakdown,
            recommended_action=recommended_action,
            reasoning_chain=reasoning,
            hash_value=hash_value,
            duplicate_matches=[d["receipt_id"] for d in duplicates],
            created_at=datetime.utcnow(),
        )
        store.save_receipt(receipt_id, hash_value, receipt_data, report)
        elapsed = _ms_since(t0)
        audit.log_step(
            step,
            input_data={"receipt_id": receipt_id},
            output_data={"saved": True},
            duration_ms=elapsed,
        )
        logger.info("Step 6 save done in %d ms", elapsed)
    except Exception as e:
        raise PipelineError(step, e) from e

    total_ms = _ms_since(pipeline_start)
    logger.info("Pipeline complete in %d ms — receipt_id=%s", total_ms, receipt_id)

    return report, audit

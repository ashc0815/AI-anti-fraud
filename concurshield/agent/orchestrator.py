"""ConcurShield Orchestrator — 编排 Pipeline 与 Agent 的系统入口。

97% 交易走 Pipeline（规则引擎，确定性，便宜，<100ms）
3%  交易启动 Agent 调查（LLM 驱动，动态推理，10-30s）
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from concurshield.agent.investigator import InvestigationAgent, InvestigationReport
from concurshield.agent.risk_scorer import EmployeeRiskScorer, RiskScore
from concurshield.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════


class ProcessingResult(BaseModel):
    employee_id: str
    expense_id: str

    # Layer 1 结果（所有交易都有）
    layer1_result: dict = Field(default_factory=dict)

    # 处理路径
    processing_path: str = "pipeline_only"  # "pipeline_only" / "agent_investigation"
    trigger_reason: str = ""

    # Agent 结果（只有启动 Agent 的交易有）
    investigation_report: Optional[InvestigationReport] = None

    # 最终判定
    final_tier: str = "T1"  # T1/T2/T3/T4
    tier_source: str = "rule_engine"  # "rule_engine" / "agent_recommendation"

    # 成本
    api_calls: int = 0
    duration_ms: int = 0


class BatchResult(BaseModel):
    total_processed: int = 0
    pipeline_only: int = 0
    agent_investigated: int = 0
    results: list[ProcessingResult] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1 Pipeline (deterministic, fast, cheap)
# ═══════════════════════════════════════════════════════════════════════════


def _run_layer1(
    registry: ToolRegistry,
    expense_data: dict,
    image_path: str | None = None,
) -> dict:
    """执行 Layer 1 规则引擎 Pipeline。

    Returns:
        {
            "math_check": {...},
            "country_check": {...},
            "duplicate_check": {...},   # only if image_path
            "exif_check": {...},        # only if image_path
            "has_critical": bool,
            "has_duplicate": bool,
            "tier": "T1"/"T2"/"T3"/"T4",
        }
    """
    result: dict[str, Any] = {
        "has_critical": False,
        "has_duplicate": False,
        "tier": "T1",
    }

    # ── Math consistency ──────────────────────────────────────────
    ocr_result = expense_data.get("ocr_result")
    if ocr_result:
        math_check = registry.execute("check_math_consistency", ocr_result=ocr_result)
        result["math_check"] = math_check
        if not math_check.get("passed", True):
            result["has_critical"] = True

        # Country rules
        country = ocr_result.get("merchant_country", ocr_result.get("country", ""))
        if country:
            country_check = registry.execute(
                "check_country_rules", ocr_result=ocr_result, country_code=country,
            )
            result["country_check"] = country_check
            if not country_check.get("passed", True):
                result["has_critical"] = True

    # ── Image-based checks ────────────────────────────────────────
    if image_path:
        try:
            dup_check = registry.execute("check_duplicate_hash", image_path=image_path)
            result["duplicate_check"] = dup_check
            if dup_check.get("is_duplicate", False):
                result["has_duplicate"] = True
        except Exception as e:
            logger.warning("Duplicate check failed: %s", e)

        try:
            exif_check = registry.execute("analyze_exif_metadata", image_path=image_path)
            result["exif_check"] = exif_check
        except Exception as e:
            logger.warning("EXIF check failed: %s", e)

    # ── Determine tier ────────────────────────────────────────────
    if result["has_critical"] or result["has_duplicate"]:
        result["tier"] = "T3"
    elif ocr_result and not result.get("math_check", {}).get("passed", True):
        result["tier"] = "T2"
    else:
        result["tier"] = "T1"

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════


class ConcurShieldOrchestrator:
    """编排 Pipeline 与 Agent 调查的系统入口。

    97% 交易走 Pipeline（规则引擎，确定性，便宜）
    3%  交易启动 Agent 调查（LLM 驱动，动态推理，贵）
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        risk_scorer: EmployeeRiskScorer,
        agent: InvestigationAgent,
        random_sample_rate: float = 0.03,
    ) -> None:
        self.registry = tool_registry
        self.scorer = risk_scorer
        self.agent = agent
        self.random_sample_rate = random_sample_rate

        # 缓存员工风险分，避免同一批次重复计算
        self._risk_cache: dict[str, RiskScore] = {}

    # ── 单笔处理 ──────────────────────────────────────────────────

    async def process_expense(
        self,
        employee_id: str,
        expense_data: dict,
        image_path: str | None = None,
        *,
        force_agent: bool = False,
        company_data: dict[str, list[dict]] | None = None,
    ) -> ProcessingResult:
        """完整处理一笔报销。

        Args:
            employee_id: 员工 ID。
            expense_data: 报销数据（可含 ocr_result, expenses 等）。
            image_path: 发票图片路径（可选）。
            force_agent: 强制启动 Agent 调查。
            company_data: 全公司数据（用于 risk scoring，可选）。
        """
        start = time.monotonic()
        expense_id = expense_data.get("expense_id", str(uuid.uuid4())[:8])

        # ── Step 1: Layer 1 Pipeline ──────────────────────────────
        layer1 = _run_layer1(self.registry, expense_data, image_path)

        # ── Step 2: 判断是否需要 Agent ────────────────────────────
        need_agent, trigger_reason = self._should_trigger_agent(
            employee_id=employee_id,
            layer1=layer1,
            expense_data=expense_data,
            force_agent=force_agent,
            company_data=company_data,
        )

        # ── Step 3a: Pipeline only ────────────────────────────────
        if not need_agent:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ProcessingResult(
                employee_id=employee_id,
                expense_id=expense_id,
                layer1_result=layer1,
                processing_path="pipeline_only",
                trigger_reason="",
                investigation_report=None,
                final_tier=layer1["tier"],
                tier_source="rule_engine",
                api_calls=0,
                duration_ms=duration_ms,
            )

        # ── Step 3b: Agent investigation ──────────────────────────
        report = await self.agent.investigate(
            employee_id=employee_id,
            trigger_reason=trigger_reason,
            expense_data=expense_data,
            layer1_results=layer1,
        )

        # Agent 推荐的 tier 优先（如果比 Layer 1 更严格）
        agent_tier = report.recommended_tier
        final_tier = _stricter_tier(layer1["tier"], agent_tier)
        tier_source = "agent_recommendation" if final_tier == agent_tier else "rule_engine"

        duration_ms = int((time.monotonic() - start) * 1000)
        return ProcessingResult(
            employee_id=employee_id,
            expense_id=expense_id,
            layer1_result=layer1,
            processing_path="agent_investigation",
            trigger_reason=trigger_reason,
            investigation_report=report,
            final_tier=final_tier,
            tier_source=tier_source,
            api_calls=report.api_calls_used,
            duration_ms=duration_ms,
        )

    # ── 批量处理 ──────────────────────────────────────────────────

    async def process_batch(
        self,
        expenses: list[dict],
        company_data: dict[str, list[dict]] | None = None,
    ) -> BatchResult:
        """批量处理。按 Employee Risk Score 降序优先处理。"""
        if not expenses:
            return BatchResult()

        # 按风险分排序（高风险优先）
        scored_expenses = self._sort_by_risk(expenses, company_data)

        results: list[ProcessingResult] = []
        pipeline_only = 0
        agent_investigated = 0

        for item in scored_expenses:
            eid = item["employee_id"]
            result = await self.process_expense(
                employee_id=eid,
                expense_data=item,
                image_path=item.get("image_path"),
                company_data=company_data,
            )
            results.append(result)

            if result.processing_path == "pipeline_only":
                pipeline_only += 1
            else:
                agent_investigated += 1

        # 汇总
        by_tier: dict[str, int] = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
        for r in results:
            by_tier[r.final_tier] = by_tier.get(r.final_tier, 0) + 1

        agent_findings = sum(
            1 for r in results
            if r.investigation_report
            and r.investigation_report.active_hypotheses
        )

        return BatchResult(
            total_processed=len(results),
            pipeline_only=pipeline_only,
            agent_investigated=agent_investigated,
            results=results,
            summary={
                "by_tier": by_tier,
                "agent_findings": agent_findings,
                "false_alarm_estimate": max(0, agent_investigated - agent_findings),
            },
        )

    # ── 内部方法 ──────────────────────────────────────────────────

    def _should_trigger_agent(
        self,
        employee_id: str,
        layer1: dict,
        expense_data: dict,
        force_agent: bool,
        company_data: dict[str, list[dict]] | None,
    ) -> tuple[bool, str]:
        """判断是否需要启动 Agent 调查。返回 (need_agent, reason)。"""
        reasons: list[str] = []

        # a) 强制触发
        if force_agent:
            return True, "手动触发标记"

        # b) Layer 1 强确定性信号
        if layer1.get("has_critical"):
            reasons.append("Layer 1 发现关键异常（数学不一致/规则违规）")
        if layer1.get("has_duplicate"):
            reasons.append("Layer 1 发现重复发票")

        # c) Employee Risk Score > 60
        risk_score = self._get_risk_score(employee_id, expense_data, company_data)
        if risk_score and risk_score.total_score > 60:
            reasons.append(
                f"Employee Risk Score {risk_score.total_score} (high): "
                f"{risk_score.top_risk_factors[0]}"
            )

        # d) 随机抽检
        if not reasons and random.random() < self.random_sample_rate:
            reasons.append(f"随机抽检命中 ({self.random_sample_rate:.0%} sample rate)")

        if reasons:
            return True, "; ".join(reasons)
        return False, ""

    def _get_risk_score(
        self,
        employee_id: str,
        expense_data: dict,
        company_data: dict[str, list[dict]] | None,
    ) -> RiskScore | None:
        """获取员工风险分（带缓存）。"""
        if employee_id in self._risk_cache:
            return self._risk_cache[employee_id]

        if not company_data:
            return None

        expenses = company_data.get(employee_id, [])
        if not expenses:
            return None

        score = self.scorer.score(employee_id, expenses, company_data)
        self._risk_cache[employee_id] = score
        return score

    def _sort_by_risk(
        self,
        expenses: list[dict],
        company_data: dict[str, list[dict]] | None,
    ) -> list[dict]:
        """按 Employee Risk Score 降序排列。"""
        if not company_data:
            return expenses

        def _risk_key(item: dict) -> float:
            eid = item.get("employee_id", "")
            score = self._get_risk_score(eid, item, company_data)
            return -(score.total_score if score else 0)

        return sorted(expenses, key=_risk_key)


# ── Helpers ───────────────────────────────────────────────────────────────

_TIER_ORDER = {"T1": 1, "T2": 2, "T3": 3, "T4": 4}


def _stricter_tier(a: str, b: str) -> str:
    """返回两个 tier 中更严格的那个。"""
    return a if _TIER_ORDER.get(a, 0) >= _TIER_ORDER.get(b, 0) else b

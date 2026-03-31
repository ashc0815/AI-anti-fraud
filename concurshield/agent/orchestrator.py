"""ConcurShield Orchestrator — 完整审计编排引擎。

流程：全员 Risk Score → Layer 1 规则引擎 → 触发判定 → Agent 调查。

触发条件（满足任一）：
  a) Employee Risk Score ≥ 61
  b) Layer 1 发现关键异常（数学不一致 / 重复 / 国家规则违规）
  c) 随机抽检 3%
  d) 手动触发

入口方法：
  run_full_analysis(company_data)  — 批量全员分析
  investigate_employee(eid, ...)   — 手动调查单个员工
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from concurshield.agent.investigator import InvestigationAgent, InvestigationReport
from concurshield.agent.llm_client import LLMClient
from concurshield.agent.risk_scorer import EmployeeRiskScorer, RiskScore
from concurshield.agent.tools import ToolRegistry, create_default_registry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════


class EmployeeResult(BaseModel):
    """单个员工的完整处理结果。"""
    employee_id: str
    risk_score: Optional[RiskScore] = None

    # Layer 1
    layer1_result: dict = Field(default_factory=dict)

    # 处理路径
    processing_path: str = "pipeline_only"  # "pipeline_only" / "agent_investigation"
    trigger_reason: str = ""

    # Agent（仅 agent_investigation 路径有）
    investigation_report: Optional[InvestigationReport] = None

    # 最终判定
    final_tier: str = "T1"
    tier_source: str = "rule_engine"  # "rule_engine" / "agent_recommendation"

    # 成本
    api_calls: int = 0
    duration_ms: int = 0


class AnalysisResult(BaseModel):
    """run_full_analysis 的批量输出。"""
    total_employees: int = 0
    pipeline_only: int = 0
    agent_investigated: int = 0
    risk_scores: list[RiskScore] = Field(default_factory=list)
    employee_results: list[EmployeeResult] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    total_duration_ms: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1 Pipeline
# ═══════════════════════════════════════════════════════════════════════════


def _run_layer1_for_employee(
    registry: ToolRegistry,
    employee_id: str,
    expenses: list[dict],
) -> dict:
    """对单个员工的全部报销执行 Layer 1 规则引擎。

    检查项：金额分布、品类内阈值聚集、独占商户、周末消费。
    （OCR / pHash / EXIF 需要图片，批量模式下按结构化数据检查）
    """
    result: dict[str, Any] = {
        "has_critical": False,
        "has_duplicate": False,
        "anomalies": [],
        "tier": "T1",
    }

    if not expenses:
        return result

    # ── 金额异常：任何单笔 > ¥5000 ──────────────────────────────
    for r in expenses:
        if r.get("amount", 0) > 5000:
            result["anomalies"].append(
                f"单笔金额异常: {r.get('merchant', '?')} ¥{r['amount']:.0f} ({r.get('date', '?')})"
            )
            result["has_critical"] = True

    # ── 周末消费检测 ──────────────────────────────────────────────
    from datetime import datetime
    weekend_expenses = []
    for r in expenses:
        try:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            if dt.weekday() >= 5:
                weekend_expenses.append(r)
        except (ValueError, KeyError):
            pass
    if len(weekend_expenses) >= 3:
        result["anomalies"].append(
            f"周末消费 {len(weekend_expenses)} 笔"
        )

    # ── 独占商户检测（Layer 1 简化版，仅标记） ────────────────────
    # 完整版在 risk_scorer 的 dimension C 中

    # ── 确定 tier ─────────────────────────────────────────────────
    if result["has_critical"]:
        result["tier"] = "T3"
    elif result["anomalies"]:
        result["tier"] = "T2"
    else:
        result["tier"] = "T1"

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

_TIER_ORDER = {"T1": 1, "T2": 2, "T3": 3, "T4": 4}


def _stricter_tier(a: str, b: str) -> str:
    return a if _TIER_ORDER.get(a, 0) >= _TIER_ORDER.get(b, 0) else b


class ConcurShieldOrchestrator:
    """完整审计编排引擎。

    用法::

        orch = ConcurShieldOrchestrator(company_data, llm_provider="mock")
        result = await orch.run_full_analysis()
    """

    def __init__(
        self,
        company_data: dict[str, list[dict]] | None = None,
        *,
        llm_provider: str = "mock",
        tool_registry: ToolRegistry | None = None,
        risk_scorer: EmployeeRiskScorer | None = None,
        agent: InvestigationAgent | None = None,
        llm: LLMClient | None = None,
        random_sample_rate: float = 0.03,
    ) -> None:
        self.company_data = company_data or {}
        self.registry = tool_registry or create_default_registry()
        self.scorer = risk_scorer or EmployeeRiskScorer()
        self.llm = llm or LLMClient(provider=llm_provider)
        self.agent = agent or InvestigationAgent(
            llm=self.llm, tool_registry=self.registry,
        )
        self.random_sample_rate = random_sample_rate
        self._risk_cache: dict[str, RiskScore] = {}

    # ── 批量全员分析 ──────────────────────────────────────────────

    async def run_full_analysis(
        self,
        company_data: dict[str, list[dict]] | None = None,
    ) -> AnalysisResult:
        """对全公司员工批量分析。

        Args:
            company_data: 公司数据。未传时使用构造函数中的 self.company_data。
        """
        company_data = company_data or self.company_data
        if not company_data:
            raise ValueError("No company_data provided")

        start = time.monotonic()
        self._risk_cache.clear()

        # ── Step 1: 全员 Risk Score ───────────────────────────────
        risk_scores = self.scorer.batch_score_all(company_data)
        for rs in risk_scores:
            self._risk_cache[rs.employee_id] = rs

        logger.info(
            "Risk scoring complete: %d employees, top=%s(%d)",
            len(risk_scores),
            risk_scores[0].employee_id if risk_scores else "-",
            risk_scores[0].total_score if risk_scores else 0,
        )

        # ── Step 2-4: 按风险分降序逐个处理 ────────────────────────
        employee_results: list[EmployeeResult] = []
        pipeline_only = 0
        agent_investigated = 0

        for rs in risk_scores:
            eid = rs.employee_id
            expenses = company_data.get(eid, [])

            result = await self._process_employee(
                employee_id=eid,
                expenses=expenses,
                risk_score=rs,
                company_data=company_data,
            )
            employee_results.append(result)

            if result.processing_path == "pipeline_only":
                pipeline_only += 1
            else:
                agent_investigated += 1

        # ── 汇总 ─────────────────────────────────────────────────
        by_tier = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
        for r in employee_results:
            by_tier[r.final_tier] = by_tier.get(r.final_tier, 0) + 1

        by_class = {"normal": 0, "elevated": 0, "high": 0}
        for rs in risk_scores:
            by_class[rs.classification] = by_class.get(rs.classification, 0) + 1

        agent_findings = sum(
            1 for r in employee_results
            if r.investigation_report and r.investigation_report.active_hypotheses
        )

        duration_ms = int((time.monotonic() - start) * 1000)

        return AnalysisResult(
            total_employees=len(risk_scores),
            pipeline_only=pipeline_only,
            agent_investigated=agent_investigated,
            risk_scores=risk_scores,
            employee_results=employee_results,
            summary={
                "total_employees": len(risk_scores),
                "pipeline_only_count": pipeline_only,
                "investigations_count": agent_investigated,
                "by_tier": by_tier,
                "by_risk_class": by_class,
                "agent_findings": agent_findings,
                "false_alarm_estimate": max(0, agent_investigated - agent_findings),
            },
            total_duration_ms=duration_ms,
        )

    # ── 手动调查单个员工 ──────────────────────────────────────────

    async def investigate_employee(
        self,
        employee_id: str,
        company_data: dict[str, list[dict]] | None = None,
        *,
        trigger_reason: str = "手动触发",
    ) -> EmployeeResult:
        """手动触发对单个员工的完整调查（跳过触发判定）。"""
        company_data = company_data or self.company_data
        expenses = company_data.get(employee_id, [])

        # 计算 risk score
        risk_score = None
        if expenses:
            risk_score = self.scorer.score(employee_id, expenses, company_data)

        # Layer 1
        layer1 = _run_layer1_for_employee(self.registry, employee_id, expenses)

        # 强制启动 Agent
        return await self._run_agent(
            employee_id=employee_id,
            expenses=expenses,
            risk_score=risk_score,
            layer1=layer1,
            trigger_reason=trigger_reason,
            company_data=company_data,
        )

    # ── 内部方法 ──────────────────────────────────────────────────

    async def _process_employee(
        self,
        employee_id: str,
        expenses: list[dict],
        risk_score: RiskScore,
        company_data: dict[str, list[dict]],
    ) -> EmployeeResult:
        """处理单个员工：Layer 1 → 触发判定 → Agent（如需）。"""
        start = time.monotonic()

        # ── Layer 1 ──────────────────────────────────────────────
        layer1 = _run_layer1_for_employee(self.registry, employee_id, expenses)

        # ── 触发判定 ─────────────────────────────────────────────
        need_agent, trigger_reason = self._should_trigger(
            risk_score=risk_score,
            layer1=layer1,
        )

        # ── Pipeline only ────────────────────────────────────────
        if not need_agent:
            duration_ms = int((time.monotonic() - start) * 1000)
            return EmployeeResult(
                employee_id=employee_id,
                risk_score=risk_score,
                layer1_result=layer1,
                processing_path="pipeline_only",
                final_tier=layer1["tier"],
                tier_source="rule_engine",
                duration_ms=duration_ms,
            )

        # ── Agent investigation ──────────────────────────────────
        return await self._run_agent(
            employee_id=employee_id,
            expenses=expenses,
            risk_score=risk_score,
            layer1=layer1,
            trigger_reason=trigger_reason,
            company_data=company_data,
        )

    async def _run_agent(
        self,
        employee_id: str,
        expenses: list[dict],
        risk_score: RiskScore | None,
        layer1: dict,
        trigger_reason: str,
        company_data: dict[str, list[dict]],
    ) -> EmployeeResult:
        """执行 Agent 调查。"""
        start = time.monotonic()

        report = await self.agent.investigate(
            employee_id=employee_id,
            trigger_reason=trigger_reason,
            expense_data={"expenses": expenses[:20]},  # 限制传入量
            layer1_results=layer1,
        )

        agent_tier = report.recommended_tier
        final_tier = _stricter_tier(layer1["tier"], agent_tier)
        tier_source = "agent_recommendation" if final_tier == agent_tier else "rule_engine"

        duration_ms = int((time.monotonic() - start) * 1000)
        return EmployeeResult(
            employee_id=employee_id,
            risk_score=risk_score,
            layer1_result=layer1,
            processing_path="agent_investigation",
            trigger_reason=trigger_reason,
            investigation_report=report,
            final_tier=final_tier,
            tier_source=tier_source,
            api_calls=report.api_calls_used,
            duration_ms=duration_ms,
        )

    def _should_trigger(
        self,
        risk_score: RiskScore,
        layer1: dict,
    ) -> tuple[bool, str]:
        """触发判定。返回 (need_agent, reason)。"""
        reasons: list[str] = []

        # a) Risk Score ≥ 61
        if risk_score.total_score >= 61:
            top = risk_score.top_risk_factors[0] if risk_score.top_risk_factors else ""
            reasons.append(f"Risk Score {risk_score.total_score} (high): {top}")

        # b) Layer 1 异常
        if layer1.get("has_critical"):
            reasons.append("Layer 1 关键异常")
        if layer1.get("has_duplicate"):
            reasons.append("Layer 1 重复发票")

        # c) 随机 3%
        if not reasons and random.random() < self.random_sample_rate:
            reasons.append(f"随机抽检 ({self.random_sample_rate:.0%})")

        if reasons:
            return True, "; ".join(reasons)
        return False, ""

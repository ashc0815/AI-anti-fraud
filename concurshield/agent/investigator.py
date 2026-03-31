"""Investigation Agent — OODA 循环驱动的多轮自主调查。

针对国产 LLM（GLM/DeepSeek）优化：
  - 结构化标签 [分析][假设][工具][发现] 替代开放式指令
  - 每次只调 1 个 tool
  - 区分 [事实] 和 [推断]
  - comment 是重要的反对证据
  - 最终报告纯 JSON，容错解析
  - 涉及 collusion 时 sensitivity 自动设为 sensitive
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from concurshield.agent.llm_client import LLMClient, LLMResponse, ToolCall, parse_llm_json
from concurshield.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════


class InvestigationStep(BaseModel):
    round_number: int
    reasoning: str
    tools_called: list[dict] = Field(default_factory=list)
    findings: str = ""
    hypothesis_update: str = ""


class InvestigationHypothesis(BaseModel):
    name: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    status: str = "active"  # "active" / "rejected" / "inconclusive"
    sensitivity: str = "normal"  # "normal" / "sensitive"


class InvestigationReport(BaseModel):
    employee_id: str
    trigger_reason: str
    total_rounds: int
    steps: list[InvestigationStep] = Field(default_factory=list)

    summary: str = ""
    active_hypotheses: list[InvestigationHypothesis] = Field(default_factory=list)
    rejected_hypotheses: list[InvestigationHypothesis] = Field(default_factory=list)
    factual_findings: list[str] = Field(default_factory=list)

    recommended_actions: list[dict] = Field(default_factory=list)
    beyond_system_capability: list[str] = Field(default_factory=list)

    recommended_tier: str = "T2"
    tier_reasoning: str = ""

    api_calls_used: int = 0
    total_duration_ms: int = 0
    total_tokens: int = 0
    full_reasoning_chain: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# System prompt — 针对国产 LLM 优化
# ═══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
你是一位资深费用审计师，正在调查一笔可疑报销。请严格按以下格式输出每轮分析：

[分析] 基于当前证据的客观分析，不使用"可能""大概"等模糊词
[假设] 列出当前活跃假设，格式：H1: 假设内容 (置信度 0.0-1.0)
[工具] 你要调用的工具及理由（每轮只调 1 个工具）
[发现] 工具返回后的客观发现

关键规则：
1. 每轮只调用 1 个工具
2. 用 [事实] 标记可验证的客观数据，用 [推断] 标记你的判断
3. 报销备注（comment）是重要的反对证据——有合理 comment 应降低假设置信度
4. 不使用定性语言（"很多""经常"），使用精确数值
5. 结论是"建议"不是"判定"
6. 如果假设涉及合谋（collusion），标记 sensitivity=sensitive

可用工具：
{tool_descriptions}

调查对象：
员工ID：{employee_id}
触发原因：{trigger_reason}
报销摘要：{expense_summary}
规则引擎结果：{layer1_results}\
"""

_FINAL_PROMPT = """\
请输出最终调查报告。严格使用纯 JSON 格式，不要在 JSON 前后加任何文字。

{{
  "summary": "一段话调查摘要",
  "active_hypotheses": [
    {{
      "name": "假设名称",
      "description": "描述",
      "confidence": 0.0-1.0,
      "supporting_evidence": ["[事实] 证据1"],
      "contradicting_evidence": ["[事实] 反对证据"],
      "status": "active",
      "sensitivity": "normal 或 sensitive（涉及合谋时为 sensitive）"
    }}
  ],
  "rejected_hypotheses": [],
  "factual_findings": ["[事实] 客观可验证的发现1"],
  "recommended_actions": [
    {{"action": "操作", "priority": "high/medium/low", "source": "system/manual", "effort": "工作量"}}
  ],
  "beyond_system_capability": ["需人工核实的项"],
  "recommended_tier": "T1/T2/T3/T4",
  "tier_reasoning": "分级理由（引用具体数据）"
}}\
"""


# ═══════════════════════════════════════════════════════════════════════════
# Collusion keywords for auto-sensitivity
# ═══════════════════════════════════════════════════════════════════════════

_COLLUSION_KEYWORDS = [
    "collusion", "合谋", "串通", "共谋", "内外勾结", "利益输送",
    "关联方", "关联交易", "审批人配合", "approver_complicit",
]


def _check_collusion_sensitivity(hypothesis: dict) -> str:
    """如果假设涉及 collusion，自动标记为 sensitive。"""
    text = json.dumps(hypothesis, ensure_ascii=False).lower()
    for kw in _COLLUSION_KEYWORDS:
        if kw in text:
            return "sensitive"
    return hypothesis.get("sensitivity", "normal")


# ═══════════════════════════════════════════════════════════════════════════
# Investigation Agent
# ═══════════════════════════════════════════════════════════════════════════


class InvestigationAgent:
    """OODA 循环驱动的多轮自主调查 Agent。"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        tool_registry: ToolRegistry | None = None,
        max_rounds: int = 6,
        max_api_calls: int = 3,
        *,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.tools = tool_registry or registry
        if self.tools is None:
            raise ValueError("Must provide tool_registry or registry")
        self.llm = llm or LLMClient(provider="mock")
        self.max_rounds = max_rounds
        self.max_api_calls = max_api_calls

    async def investigate(
        self,
        employee_id: str,
        trigger_reason: str,
        expense_data: dict,
        layer1_results: dict | None = None,
    ) -> InvestigationReport:
        """启动一轮完整 OODA 调查。"""
        start = time.monotonic()
        api_calls_used = 0
        total_tokens = 0
        steps: list[InvestigationStep] = []
        reasoning_parts: list[str] = []

        expense_summary = self._format_expense_summary(expense_data)
        l1_text = json.dumps(layer1_results, ensure_ascii=False, indent=2) if layer1_results else "无"

        system_prompt = _SYSTEM_PROMPT.format(
            tool_descriptions=self.tools.get_descriptions_for_prompt(),
            employee_id=employee_id,
            trigger_reason=trigger_reason,
            expense_summary=expense_summary,
            layer1_results=l1_text,
        )

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"开始调查员工 {employee_id}。触发原因：{trigger_reason}\n"
                "请先 [分析] 现有信息，提出 [假设]，然后决定第一步 [工具]。"
            )},
        ]

        tool_schemas = self.tools.get_tool_schemas()

        # ── OODA 循环 ────────────────────────────────────────────
        for round_num in range(1, self.max_rounds + 1):
            try:
                resp = await self.llm.chat(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=0.3,
                )
            except Exception as e:
                logger.error("LLM call failed (round %d): %s", round_num, e)
                steps.append(InvestigationStep(
                    round_number=round_num,
                    reasoning=f"LLM 调用失败: {e}",
                ))
                reasoning_parts.append(f"[Round {round_num}] LLM 调用失败: {e}")
                break

            total_tokens += resp.usage.get("total_tokens", 0)
            reasoning_parts.append(f"[Round {round_num}] {resp.text}")

            # 追加 assistant message
            messages.append(self._to_assistant_msg(resp))

            step = InvestigationStep(
                round_number=round_num,
                reasoning=resp.text,
            )

            # 无 tool call → 调查完成
            if not resp.tool_calls:
                step.findings = "Agent 结束调查"
                steps.append(step)
                break

            # 执行 tool calls（每轮通常只有 1 个）
            findings_parts: list[str] = []
            for tc in resp.tool_calls:
                args = tc.parsed_args()
                step.tools_called.append({"name": tc.name, "args": args})

                # 成本控制：外部 API 有上限
                if tc.name == "search_merchant_web":
                    api_calls_used += 1
                    if api_calls_used > self.max_api_calls:
                        result = {"error": "外部API调用已达上限，请基于已有数据判断"}
                    else:
                        result = self._safe_execute(tc.name, args)
                else:
                    result = self._safe_execute(tc.name, args)

                result_json = json.dumps(result, ensure_ascii=False, default=str)
                findings_parts.append(f"{tc.name}: {result_json[:500]}")
                reasoning_parts.append(f"  → {tc.name}({args}) = {result_json[:300]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_json,
                })

            step.findings = "; ".join(findings_parts)
            steps.append(step)

        # ── 请求最终报告 ──────────────────────────────────────────
        messages.append({"role": "user", "content": _FINAL_PROMPT})
        report_data = await self._request_final_report(messages)
        total_tokens += report_data.get("_tokens", 0)

        duration_ms = int((time.monotonic() - start) * 1000)

        # 解析假设并自动标记 sensitivity
        active_hyps = []
        for h in report_data.get("active_hypotheses", []):
            h["sensitivity"] = _check_collusion_sensitivity(h)
            active_hyps.append(InvestigationHypothesis(**h))

        rejected_hyps = []
        for h in report_data.get("rejected_hypotheses", []):
            h["sensitivity"] = _check_collusion_sensitivity(h)
            rejected_hyps.append(InvestigationHypothesis(**h))

        return InvestigationReport(
            employee_id=employee_id,
            trigger_reason=trigger_reason,
            total_rounds=len(steps),
            steps=steps,
            summary=report_data.get("summary", ""),
            active_hypotheses=active_hyps,
            rejected_hypotheses=rejected_hyps,
            factual_findings=report_data.get("factual_findings", []),
            recommended_actions=report_data.get("recommended_actions", []),
            beyond_system_capability=report_data.get("beyond_system_capability", []),
            recommended_tier=report_data.get("recommended_tier", "T2"),
            tier_reasoning=report_data.get("tier_reasoning", ""),
            api_calls_used=api_calls_used,
            total_duration_ms=duration_ms,
            total_tokens=total_tokens,
            full_reasoning_chain="\n".join(reasoning_parts),
        )

    # ── Helpers ───────────────────────────────────────────────────

    def _safe_execute(self, name: str, args: dict) -> dict:
        try:
            return self.tools.execute(name, **args)
        except Exception as e:
            logger.error("Tool '%s' failed: %s", name, e)
            return {"error": f"Tool 执行失败: {e}"}

    @staticmethod
    def _to_assistant_msg(resp: LLMResponse) -> dict:
        d: dict[str, Any] = {"role": "assistant", "content": resp.text}
        if resp.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in resp.tool_calls
            ]
        return d

    @staticmethod
    def _format_expense_summary(expense_data: dict) -> str:
        if not expense_data:
            return "无报销数据"
        expenses = expense_data.get("expenses", [])
        if expenses:
            total = sum(e.get("amount", 0) for e in expenses)
            cities = list({e.get("city", "") for e in expenses if e.get("city")})
            merchants = list({e.get("merchant", "") for e in expenses if e.get("merchant")})
            return (
                f"共 {len(expenses)} 笔报销，总额 ¥{total:.2f}\n"
                f"涉及城市: {', '.join(cities)}\n"
                f"涉及商户 {len(merchants)} 家"
            )
        return json.dumps(expense_data, ensure_ascii=False)[:500]

    async def _request_final_report(self, messages: list[dict]) -> dict:
        try:
            resp = await self.llm.chat(messages=messages, temperature=0.1)
            data = parse_llm_json(resp.text)
            data["_tokens"] = resp.usage.get("total_tokens", 0)
            return data
        except Exception as e:
            logger.error("Final report generation failed: %s", e)
            return _fallback_report()


def _fallback_report() -> dict:
    return {
        "summary": "LLM 不可用，无法生成调查报告。请人工审核。",
        "active_hypotheses": [],
        "rejected_hypotheses": [],
        "factual_findings": ["[事实] 调查因 LLM 不可用而中断"],
        "recommended_actions": [
            {"action": "人工审核该员工全部报销记录", "priority": "high",
             "source": "manual", "effort": "审计员 2-4 小时"},
        ],
        "beyond_system_capability": ["所有调查项均需人工完成"],
        "recommended_tier": "T3",
        "tier_reasoning": "系统无法完成自动调查，保守升级至 T3",
    }

"""Investigation Agent — 模拟审计师"查案子"的多轮自主调查。

每一步查什么取决于上一步发现了什么。Agent 通过 LLM 推理 + ToolRegistry
function-calling 循环，逐步构建假设、收集证据、得出结论。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Protocol

from pydantic import BaseModel, Field

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
    full_reasoning_chain: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# LLM client protocol (duck-typing for openai.AsyncOpenAI or similar)
# ═══════════════════════════════════════════════════════════════════════════


class LLMClient(Protocol):
    """Any object with a chat.completions.create method."""

    class chat:  # noqa: N801
        class completions:
            @staticmethod
            async def create(**kwargs: Any) -> Any: ...


# ═══════════════════════════════════════════════════════════════════════════
# System prompt
# ═══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
你是一位拥有30年经验的四大会计师事务所审计师，专精差旅费用审计。
你正在调查一笔被标记为可疑的报销交易。

你的工作方法：
1. 先看整体，找"哪里不对"
2. 检查流程有没有被绕过
3. 深入具体交易，验证或否定假设

你的推理规则：
- 每次调用工具前，说明你的假设和为什么要查这个数据
- 收到数据后，分析发现了什么，决定下一步
- 不要一次调用所有工具。一次只调1-2个
- 区分事实、推断和假设
- 主动寻找能否定你假设的证据（避免确认偏见）
- 你的结论是"建议"不是"判定"

可用工具：
{tool_descriptions}

当前调查对象：
员工ID：{employee_id}
触发原因：{trigger_reason}
当前报销摘要：{expense_summary}
规则引擎检测结果：{layer1_results}\
"""

_FINAL_PROMPT = """\
请输出你的最终调查报告，严格使用以下 JSON 格式：
{{
  "summary": "一段话调查摘要",
  "active_hypotheses": [
    {{
      "name": "假设名称",
      "description": "描述",
      "confidence": 0.8,
      "supporting_evidence": ["证据1", "证据2"],
      "contradicting_evidence": ["反对证据"],
      "status": "active"
    }}
  ],
  "rejected_hypotheses": [
    {{
      "name": "已排除假设",
      "description": "描述",
      "confidence": 0.1,
      "supporting_evidence": [],
      "contradicting_evidence": ["排除原因"],
      "status": "rejected"
    }}
  ],
  "factual_findings": ["客观可验证的事实1", "事实2"],
  "recommended_actions": [
    {{
      "action": "建议操作",
      "priority": "high/medium/low",
      "source": "system/manual",
      "effort": "描述所需工作量"
    }}
  ],
  "beyond_system_capability": ["需人工核实的项"],
  "recommended_tier": "T1/T2/T3/T4",
  "tier_reasoning": "分级理由"
}}

只输出 JSON，不要其他内容。\
"""


# ═══════════════════════════════════════════════════════════════════════════
# Agent
# ═══════════════════════════════════════════════════════════════════════════


class InvestigationAgent:
    """多轮自主调查 Agent。通过 LLM function-calling 循环驱动。"""

    def __init__(
        self,
        llm_client: Any = None,
        tool_registry: ToolRegistry | None = None,
        max_rounds: int = 6,
        max_api_calls: int = 3,
        model: str | None = None,
        *,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.tools = tool_registry or registry
        if self.tools is None:
            raise ValueError("Must provide tool_registry or registry")
        self.llm = llm_client or MockLLMClient()
        self.max_rounds = max_rounds
        self.max_api_calls = max_api_calls
        self.model = model
        self.investigation_log: list[dict] = []

    def _get_model(self) -> str:
        if self.model:
            return self.model
        from concurshield.config import settings
        return settings.OPENAI_MODEL or "gpt-4o"

    async def investigate(
        self,
        employee_id: str,
        trigger_reason: str,
        expense_data: dict,
        layer1_results: dict | None = None,
    ) -> InvestigationReport:
        """启动一轮完整调查。"""
        start = time.monotonic()
        self.investigation_log = []
        api_calls_used = 0
        steps: list[InvestigationStep] = []
        reasoning_parts: list[str] = []

        # 构建 expense summary
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
                f"请开始调查员工 {employee_id}。触发原因：{trigger_reason}\n"
                f"请先分析现有信息，提出初步假设，然后决定第一步查什么。"
            )},
        ]

        tool_schemas = self.tools.get_tool_schemas()

        # ── 调查循环 ──────────────────────────────────────────────
        for round_num in range(1, self.max_rounds + 1):
            try:
                response = await self.llm.chat.completions.create(
                    model=self._get_model(),
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                    temperature=0.3,
                )
            except Exception as e:
                logger.error("LLM 调用失败 (round %d): %s", round_num, e)
                steps.append(InvestigationStep(
                    round_number=round_num,
                    reasoning=f"LLM 调用失败: {e}",
                    tools_called=[],
                    findings="",
                    hypothesis_update="调查中断",
                ))
                reasoning_parts.append(f"[Round {round_num}] LLM 调用失败: {e}")
                break

            msg = response.choices[0].message
            text_content = msg.content or ""
            tool_calls = msg.tool_calls or []

            reasoning_parts.append(f"[Round {round_num}] {text_content}")

            # 记录到 messages
            messages.append(self._assistant_msg(msg))

            step = InvestigationStep(
                round_number=round_num,
                reasoning=text_content,
                tools_called=[],
                findings="",
                hypothesis_update="",
            )

            # 无 tool_call → Agent 认为调查完成
            if not tool_calls:
                step.findings = "Agent 决定结束调查"
                steps.append(step)
                break

            # 执行 tool calls
            findings_parts: list[str] = []
            for tc in tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                step.tools_called.append({"name": fn_name, "args": fn_args})

                # 成本控制
                if fn_name == "search_merchant_web":
                    api_calls_used += 1
                    if api_calls_used > self.max_api_calls:
                        result = {"error": "外部API调用已达上限。请基于已有数据判断。"}
                    else:
                        result = self._execute_tool(fn_name, fn_args)
                else:
                    result = self._execute_tool(fn_name, fn_args)

                result_json = json.dumps(result, ensure_ascii=False, default=str)
                findings_parts.append(f"{fn_name}: {result_json[:500]}")
                reasoning_parts.append(f"  → {fn_name}({fn_args}) = {result_json[:300]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_json,
                })

            step.findings = "; ".join(findings_parts)
            steps.append(step)

            self.investigation_log.append({
                "round": round_num,
                "reasoning": text_content,
                "tool_calls": [{"name": tc.function.name} for tc in tool_calls],
            })

        # ── 请求最终报告 ──────────────────────────────────────────
        messages.append({"role": "user", "content": _FINAL_PROMPT})

        report_data = await self._request_final_report(messages)
        duration_ms = int((time.monotonic() - start) * 1000)

        return InvestigationReport(
            employee_id=employee_id,
            trigger_reason=trigger_reason,
            total_rounds=len(steps),
            steps=steps,
            summary=report_data.get("summary", ""),
            active_hypotheses=[
                InvestigationHypothesis(**h)
                for h in report_data.get("active_hypotheses", [])
            ],
            rejected_hypotheses=[
                InvestigationHypothesis(**h)
                for h in report_data.get("rejected_hypotheses", [])
            ],
            factual_findings=report_data.get("factual_findings", []),
            recommended_actions=report_data.get("recommended_actions", []),
            beyond_system_capability=report_data.get("beyond_system_capability", []),
            recommended_tier=report_data.get("recommended_tier", "T2"),
            tier_reasoning=report_data.get("tier_reasoning", ""),
            api_calls_used=api_calls_used,
            total_duration_ms=duration_ms,
            full_reasoning_chain="\n".join(reasoning_parts),
        )

    # ── Helper methods ────────────────────────────────────────────

    def _execute_tool(self, name: str, args: dict) -> dict:
        """安全地执行 tool，捕获异常。"""
        try:
            return self.tools.execute(name, **args)
        except Exception as e:
            logger.error("Tool '%s' 执行失败: %s", name, e)
            return {"error": f"Tool 执行失败: {e}"}

    @staticmethod
    def _assistant_msg(msg: Any) -> dict:
        """将 OpenAI message 对象转为 dict 以追加到 messages。"""
        d: dict[str, Any] = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return d

    @staticmethod
    def _format_expense_summary(expense_data: dict) -> str:
        """将 expense_data 格式化为可读摘要。"""
        if not expense_data:
            return "无报销数据"

        lines: list[str] = []
        expenses = expense_data.get("expenses", [])
        if expenses:
            total = sum(e.get("amount", 0) for e in expenses)
            cities = set(e.get("city", "") for e in expenses)
            merchants = set(e.get("merchant", "") for e in expenses)
            lines.append(f"共 {len(expenses)} 笔报销，总额 {total:.2f}")
            lines.append(f"涉及城市: {', '.join(c for c in cities if c)}")
            lines.append(f"涉及商户 {len(merchants)} 家")
        else:
            # 可能是单笔交易
            for k, v in expense_data.items():
                lines.append(f"{k}: {v}")

        return "\n".join(lines)

    async def _request_final_report(self, messages: list[dict]) -> dict:
        """请求 LLM 输出最终结构化报告。"""
        try:
            response = await self.llm.chat.completions.create(
                model=self._get_model(),
                messages=messages,
                temperature=0.2,
            )
            text = response.choices[0].message.content or ""
            return self._parse_json(text)
        except Exception as e:
            logger.error("最终报告生成失败: %s", e)
            return self._fallback_report()

    @staticmethod
    def _parse_json(text: str) -> dict:
        """从 LLM 输出中解析 JSON（处理 markdown 包裹和 think 标签）。"""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned[cleaned.index("\n") + 1:]
            cleaned = cleaned[:cleaned.rfind("```")].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 尝试提取第一个 JSON 块
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {}

    @staticmethod
    def _fallback_report() -> dict:
        """LLM 不可用时的降级报告模板。"""
        return {
            "summary": "LLM 不可用，无法生成调查报告。请人工审核。",
            "active_hypotheses": [],
            "rejected_hypotheses": [],
            "factual_findings": ["调查因 LLM 不可用而中断"],
            "recommended_actions": [
                {
                    "action": "人工审核该员工的全部报销记录",
                    "priority": "high",
                    "source": "manual",
                    "effort": "需审计员 2-4 小时",
                }
            ],
            "beyond_system_capability": ["所有调查项均需人工完成"],
            "recommended_tier": "T3",
            "tier_reasoning": "系统无法完成自动调查，保守升级至 T3 等待人工审核",
        }


# ═══════════════════════════════════════════════════════════════════════════
# Convenience: run without real LLM (demo / test)
# ═══════════════════════════════════════════════════════════════════════════


class MockLLMClient:
    """模拟 LLM client，用于离线 demo / 测试。

    按预设脚本模拟审计师的多轮调查行为：
    Round 1: 查员工画像 + 近期报销
    Round 2: 查同组对比 + 商户全公司使用
    Round 3: 查审批历史
    Round 4: 输出结论（无 tool call）
    """

    class _Completions:
        def __init__(self, parent: MockLLMClient) -> None:
            self._parent = parent
            self._call_count = 0

        async def create(self, **kwargs: Any) -> Any:
            self._call_count += 1
            messages = kwargs.get("messages", [])
            tools = kwargs.get("tools", [])

            # 最终报告请求（无 tools 参数或最后一条是 FINAL_PROMPT）
            if not tools or (messages and "最终调查报告" in str(messages[-1].get("content", ""))):
                return self._final_response(messages)

            # 多轮脚本
            round_num = self._call_count
            if round_num == 1:
                return self._round1_response(messages)
            elif round_num == 2:
                return self._round2_response(messages)
            elif round_num == 3:
                return self._round3_response(messages)
            else:
                return self._conclude_response(messages)

        def _round1_response(self, messages: list[dict]) -> Any:
            # 提取 employee_id
            eid = self._extract_employee_id(messages)
            return _MockResponse(
                content=(
                    "## 初步分析\n\n"
                    f"该员工 {eid} 被标记为可疑。我需要先了解该员工的整体消费画像，"
                    "以及近期的具体报销明细，才能形成初步假设。\n\n"
                    "**假设 1**：消费模式异常（金额/地点偏离历史基线）\n"
                    "**假设 2**：可能存在虚假商户\n\n"
                    "我先调用两个基础工具来收集信息。"
                ),
                tool_calls=[
                    _MockToolCall("call_001", "get_employee_profile", {"employee_id": eid}),
                    _MockToolCall("call_002", "get_employee_recent_expenses", {"employee_id": eid}),
                ],
            )

        def _round2_response(self, messages: list[dict]) -> Any:
            eid = self._extract_employee_id(messages)
            return _MockResponse(
                content=(
                    "## 第二轮分析\n\n"
                    "从员工画像和近期记录来看，我注意到几个可疑点。"
                    "接下来我需要对比同组其他员工的消费水平，"
                    "以及检查该员工常用商户在全公司的使用情况。"
                ),
                tool_calls=[
                    _MockToolCall("call_003", "get_approval_history", {"employee_id": eid}),
                    _MockToolCall("call_004", "get_amount_distribution",
                                  {"employee_id": eid, "expense_type": "餐饮"}),
                ],
            )

        def _round3_response(self, messages: list[dict]) -> Any:
            return _MockResponse(
                content=(
                    "## 第三轮分析\n\n"
                    "基于前两轮数据，我已收集到足够证据来形成结论。"
                    "消费模式存在偏离但并非极端异常，需要进一步人工核实。"
                    "我现在可以给出调查结论了。"
                ),
                tool_calls=[],
            )

        def _conclude_response(self, messages: list[dict]) -> Any:
            return _MockResponse(
                content="基于已收集的证据，我已准备好输出最终报告。",
                tool_calls=[],
            )

        def _final_response(self, messages: list[dict]) -> Any:
            eid = self._extract_employee_id(messages)
            report = {
                "summary": (
                    f"对员工 {eid} 的调查显示其消费模式存在一定偏离，"
                    "包括消费变异系数偏高和部分商户使用集中度异常。"
                    "但未发现确凿的欺诈证据，建议进一步人工核实。"
                ),
                "active_hypotheses": [
                    {
                        "name": "消费模式异常",
                        "description": "员工近期消费金额和频率偏离历史基线",
                        "confidence": 0.65,
                        "supporting_evidence": [
                            "消费变异系数高于同组平均",
                            "近期金额有上升趋势",
                        ],
                        "contradicting_evidence": [
                            "总消费金额仍在合理范围内",
                        ],
                        "status": "active",
                    },
                    {
                        "name": "独占商户风险",
                        "description": "部分商户仅该员工使用，可能为虚假商户",
                        "confidence": 0.45,
                        "supporting_evidence": [
                            "存在全公司仅该员工使用的商户",
                        ],
                        "contradicting_evidence": [
                            "独占商户金额不大",
                            "可能是员工个人偏好",
                        ],
                        "status": "active",
                    },
                ],
                "rejected_hypotheses": [
                    {
                        "name": "系统性虚报",
                        "description": "员工有组织地虚构报销",
                        "confidence": 0.1,
                        "supporting_evidence": [],
                        "contradicting_evidence": [
                            "审批驳回率正常",
                            "报销频率与同组一致",
                        ],
                        "status": "rejected",
                    },
                ],
                "factual_findings": [
                    "员工存在独占商户",
                    "消费变异系数偏高",
                    "审批历史无明显异常",
                    "餐饮类报销有阈值附近聚集现象",
                ],
                "recommended_actions": [
                    {
                        "action": "要求员工提供独占商户的消费凭证原件",
                        "priority": "high",
                        "source": "manual",
                        "effort": "审计员 1 小时",
                    },
                    {
                        "action": "将该员工纳入下月重点抽查名单",
                        "priority": "medium",
                        "source": "system",
                        "effort": "系统自动",
                    },
                    {
                        "action": "核实独占商户的工商注册信息",
                        "priority": "medium",
                        "source": "manual",
                        "effort": "审计员 30 分钟",
                    },
                ],
                "beyond_system_capability": [
                    "独占商户的实地核查",
                    "与员工面谈核实消费目的",
                    "跨部门调取出差审批单",
                ],
                "recommended_tier": "T2",
                "tier_reasoning": (
                    "存在可疑信号但无确凿欺诈证据。消费偏离度中等，"
                    "独占商户风险需人工核实。建议列为 T2 关注对象，"
                    "由审计员在日常巡检中跟进。"
                ),
            }
            return _MockResponse(
                content=json.dumps(report, ensure_ascii=False, indent=2),
                tool_calls=[],
            )

        @staticmethod
        def _extract_employee_id(messages: list[dict]) -> str:
            for m in messages:
                content = str(m.get("content", ""))
                match = re.search(r"EMP-\d{3}", content)
                if match:
                    return match.group()
            return "EMP-001"

    class _Chat:
        def __init__(self, parent: MockLLMClient) -> None:
            self.completions = MockLLMClient._Completions(parent)

    def __init__(self) -> None:
        self.chat = MockLLMClient._Chat(self)


# ── Mock response objects ─────────────────────────────────────────────────


class _MockFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _MockToolCall:
    def __init__(self, call_id: str, name: str, args: dict) -> None:
        self.id = call_id
        self.function = _MockFunction(name, json.dumps(args, ensure_ascii=False))


class _MockMessage:
    def __init__(self, content: str, tool_calls: list | None) -> None:
        self.content = content
        self.tool_calls = tool_calls if tool_calls else None


class _MockChoice:
    def __init__(self, message: _MockMessage) -> None:
        self.message = message


class _MockResponse:
    def __init__(self, content: str, tool_calls: list) -> None:
        self.choices = [
            _MockChoice(_MockMessage(content, tool_calls or None))
        ]

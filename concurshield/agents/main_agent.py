"""Main Agent 编排器 - 协调各子 Agent 完成发票审核流程

Fatal Triangle 原则：Main Agent 拥有 orchestration 权限 + private data，
不直接处理原始图片（untrusted input）。子 Agent 的输出被视为 structured data。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import anthropic

from concurshield.agents.merchant_verify import verify_merchant
from concurshield.agents.metadata_agent import analyze_metadata
from concurshield.agents.visual_forensics import analyze_visual_integrity
from concurshield.config import settings
from concurshield.models.schemas import AgentAction, ReceiptData, RuleCheckResult
from concurshield.utils.audit_trail import AuditTrail

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
你是一个财务审计专家。根据以下证据综合判断这张收据的风险等级。

请输出一个 JSON 对象，包含：
{
  "risk_score": <0-100 的整数，0=无风险，100=确定欺诈>,
  "reasoning": "<完整推理链：为什么给这个分数>",
  "recommended_action": "<建议操作：approve / review / reject>"
}

评分指南：
- 0-20: 低风险，可自动通过
- 21-50: 中风险，建议人工复核
- 51-80: 高风险，需要详细调查
- 81-100: 极高风险，建议拒绝

只输出 JSON，不要其他内容。\
"""


async def investigate(
    image_path: str,
    receipt_data: ReceiptData,
    rule_results: list[RuleCheckResult],
    audit: AuditTrail,
) -> tuple[list[AgentAction], str, float]:
    """Main Agent 核心编排逻辑。

    根据规则结果决定 spawn 哪些子 Agent，并发执行后调用 Claude 做综合判断。

    Args:
        image_path: 发票图片路径。
        receipt_data: OCR 结构化数据。
        rule_results: 规则引擎校验结果。
        audit: 审计轨迹记录器。

    Returns:
        (agent_actions, reasoning_chain, agent_risk_score) 三元组。
    """
    start = time.monotonic()

    # ── 1. 分析 rule_results，确定需要 spawn 的子 Agent ──────────
    tasks: list[tuple[str, asyncio.Task]] = []
    spawn_reasons: list[str] = []

    has_math_fail = any(
        r.rule_id.startswith("MATH") and not r.passed for r in rule_results
    )
    has_amount_fail = any(
        r.rule_id.startswith("AMOUNT") and not r.passed for r in rule_results
    )
    has_critical = any(
        not r.passed and r.severity == "critical" for r in rule_results
    )

    # 始终 spawn metadata_agent（成本最低的检查）
    tasks.append(("metadata_agent", asyncio.create_task(
        analyze_metadata(image_path)
    )))
    spawn_reasons.append("metadata_agent: 始终执行（低成本 EXIF 检查）")

    if has_math_fail or has_critical:
        tasks.append(("visual_forensics", asyncio.create_task(
            analyze_visual_integrity(image_path)
        )))
        reason = "MATH 类规则失败" if has_math_fail else "存在 critical 失败"
        spawn_reasons.append(f"visual_forensics: {reason}")

    if has_amount_fail:
        tasks.append(("merchant_verify", asyncio.create_task(
            verify_merchant(receipt_data)
        )))
        spawn_reasons.append("merchant_verify: AMOUNT 类规则失败")

    audit.log_step(
        "agent_dispatch",
        input_data={"spawn_reasons": spawn_reasons},
        output_data={"agents_spawned": [t[0] for t in tasks]},
        duration_ms=0,
    )

    # ── 2. 并发执行所有子 Agent ──────────────────────────────────
    all_actions: list[AgentAction] = []
    for agent_name, task in tasks:
        try:
            actions = await task
            all_actions.extend(actions)
            for action in actions:
                audit.log_agent_action(action)
        except Exception as e:
            logger.error("子 Agent %s 执行失败: %s", agent_name, e)
            err_action = AgentAction(
                agent_name=agent_name,
                tool_name="error",
                input_summary=f"{agent_name} 调用",
                output_summary=f"执行失败: {e}",
                duration_ms=0,
            )
            all_actions.append(err_action)
            audit.log_agent_action(err_action)

    dispatch_ms = int((time.monotonic() - start) * 1000)
    audit.log_step(
        "agent_execution",
        input_data=f"{len(tasks)} 个子 Agent",
        output_data=f"{len(all_actions)} 个 AgentAction",
        duration_ms=dispatch_ms,
    )

    # ── 3. 调用 Claude 做最终综合判断 ────────────────────────────
    reasoning, risk_score, recommended_action = await _judge_with_llm(
        receipt_data, rule_results, all_actions, audit
    )

    return all_actions, reasoning, risk_score


async def _judge_with_llm(
    receipt_data: ReceiptData,
    rule_results: list[RuleCheckResult],
    agent_actions: list[AgentAction],
    audit: AuditTrail,
) -> tuple[str, float, str]:
    """调用 Claude API 做最终综合判断。

    Returns:
        (reasoning, risk_score, recommended_action)
    """
    # 构建证据摘要
    evidence_parts = [
        "## 收据信息",
        f"- 商户: {receipt_data.merchant_name} ({receipt_data.merchant_country})",
        f"- 日期: {receipt_data.date}",
        f"- 总额: {receipt_data.total} {receipt_data.currency}",
        f"- 行项数: {len(receipt_data.items)}",
        "",
        "## 规则检查结果",
    ]
    for r in rule_results:
        status = "PASS" if r.passed else "FAIL"
        evidence_parts.append(f"- [{status}] {r.rule_id} {r.rule_name}: {r.detail}")

    evidence_parts.append("")
    evidence_parts.append("## 子 Agent 分析结果")
    for a in agent_actions:
        evidence_parts.append(f"- [{a.agent_name}/{a.tool_name}]: {a.output_summary}")

    evidence_text = "\n".join(evidence_parts)

    start = time.monotonic()
    try:
        client_kwargs: dict = {"api_key": settings.ANTHROPIC_API_KEY}
        if settings.ANTHROPIC_BASE_URL:
            client_kwargs["api_key"] = "placeholder"
            client_kwargs["base_url"] = settings.ANTHROPIC_BASE_URL
            client_kwargs["default_headers"] = {
                "Authorization": f"Bearer {settings.ANTHROPIC_API_KEY}",
            }
        client = anthropic.AsyncAnthropic(**client_kwargs)

        response = await client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=_JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": evidence_text}],
        )

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        # 解析 JSON
        import re
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned[cleaned.index("\n") + 1:]
            cleaned = cleaned[:cleaned.rfind("```")].strip()

        result = json.loads(cleaned)
        risk_score = float(result.get("risk_score", 50))
        reasoning = str(result.get("reasoning", "无推理链"))
        recommended_action = str(result.get("recommended_action", "review"))

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("LLM 综合判断失败: %s", e)
        # 降级策略：根据规则结果估算风险
        critical_count = sum(
            1 for r in rule_results if not r.passed and r.severity == "critical"
        )
        warning_count = sum(
            1 for r in rule_results if not r.passed and r.severity == "warning"
        )
        risk_score = min(100.0, critical_count * 25.0 + warning_count * 10.0)
        reasoning = (
            f"LLM 调用失败 ({e})，使用降级评分: "
            f"{critical_count} 个 critical 失败, {warning_count} 个 warning 失败"
        )
        recommended_action = "review" if risk_score > 20 else "approve"

    audit.log_step(
        "llm_judgment",
        input_data=f"证据摘要 ({len(evidence_text)} chars)",
        output_data=f"score={risk_score}, action={recommended_action}",
        duration_ms=duration_ms,
    )

    return reasoning, risk_score, recommended_action

"""LLM Client — LLM-agnostic 接口，所有模型通过 OpenAI 兼容格式调用。

预设 Provider:
  glm-4-flash     — 智谱 GLM-4-Flash（免费）
  glm-4           — 智谱 GLM-4（¥5/百万 token）
  glm-5           — 智谱 GLM-5
  deepseek-v3     — DeepSeek-V3
  mock            — 不调 API，返回预设响应（测试/演示用）
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Response model
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ToolCall:
    """LLM 请求调用的一个 tool。"""
    id: str
    name: str
    arguments: str  # raw JSON string

    def parsed_args(self) -> dict:
        try:
            return json.loads(self.arguments)
        except json.JSONDecodeError:
            return {}


@dataclass
class LLMResponse:
    """统一的 LLM 响应。"""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # {prompt_tokens, completion_tokens, total_tokens}
    model: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# Provider configs
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str  # 环境变量名
    default_temperature: float = 0.3
    supports_tools: bool = True


PROVIDERS: dict[str, ProviderConfig] = {
    "glm-4-flash": ProviderConfig(
        name="glm-4-flash",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        api_key_env="ZHIPU_API_KEY",
        default_temperature=0.3,
    ),
    "glm-4": ProviderConfig(
        name="glm-4",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4",
        api_key_env="ZHIPU_API_KEY",
        default_temperature=0.3,
    ),
    "glm-5": ProviderConfig(
        name="glm-5",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5",
        api_key_env="ZHIPU_API_KEY",
        default_temperature=0.3,
    ),
    "deepseek-v3": ProviderConfig(
        name="deepseek-v3",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        default_temperature=0.3,
    ),
    "mock": ProviderConfig(
        name="mock",
        base_url="",
        model="mock",
        api_key_env="",
        supports_tools=True,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# LLM Client
# ═══════════════════════════════════════════════════════════════════════════


class LLMClient:
    """LLM-agnostic 客户端，所有模型通过 OpenAI 兼容格式调用。"""

    def __init__(
        self,
        provider: str = "mock",
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'. Available: {list(PROVIDERS)}")

        self.config = PROVIDERS[provider]
        self._api_key = api_key or os.getenv(self.config.api_key_env, "")
        self._base_url = base_url or self.config.base_url
        self._model = model or self.config.model
        self._client: Any = None  # lazy init

        if provider == "mock":
            self._mock = _MockBackend()

    def _get_client(self) -> Any:
        if self._client is None:
            import openai
            self._client = openai.AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        *,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """发送 chat 请求，返回统一 LLMResponse。"""
        temp = temperature if temperature is not None else self.config.default_temperature

        if self.config.name == "mock":
            return await self._mock.chat(messages, tools, temp)

        return await self._call_openai_compat(messages, tools, temp, tool_choice)

    async def _call_openai_compat(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
        tool_choice: str,
    ) -> LLMResponse:
        """通过 OpenAI 兼容 API 调用。"""
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        start = time.monotonic()
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error("LLM call failed (%s/%s): %s", self.config.name, self._model, e)
            raise

        msg = response.choices[0].message
        duration_ms = int((time.monotonic() - start) * 1000)

        # Parse tool calls
        parsed_tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                parsed_tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ))

        # Parse usage
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
                "duration_ms": duration_ms,
            }

        return LLMResponse(
            text=msg.content or "",
            tool_calls=parsed_tool_calls,
            usage=usage,
            model=response.model or self._model,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Mock backend — 不调 API，返回预设脚本化响应
# ═══════════════════════════════════════════════════════════════════════════


class _MockBackend:
    """模拟 LLM 后端，按轮次返回脚本化的审计师调查响应。"""

    def __init__(self) -> None:
        self._call_count = 0

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
    ) -> LLMResponse:
        self._call_count += 1

        # 最终报告请求（无 tools 或消息包含报告指令）
        is_final = not tools or any(
            "最终调查报告" in str(m.get("content", ""))
            for m in messages[-2:]
        )
        if is_final:
            return self._final_response(messages)

        eid = self._extract_employee_id(messages)
        round_num = self._call_count

        if round_num == 1:
            return self._round1(eid)
        elif round_num == 2:
            return self._round2(eid)
        elif round_num == 3:
            return self._round3(eid)
        else:
            return self._conclude(eid)

    def _round1(self, eid: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "[分析] 该员工被标记为可疑，需要先了解整体消费画像。\n"
                f"[假设] H1: {eid} 的消费模式存在异常偏离\n"
                "[工具] 调用 get_employee_profile 获取基线数据"
            ),
            tool_calls=[
                ToolCall("call_001", "get_employee_profile", json.dumps({"employee_id": eid})),
            ],
            usage={"prompt_tokens": 500, "completion_tokens": 80, "total_tokens": 580},
            model="mock",
        )

    def _round2(self, eid: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "[分析] 画像数据显示存在可疑信号，需进一步检查审批历史和金额分布。\n"
                "[假设] H1 强化: 消费偏离可能与审批流程漏洞有关\n"
                "[工具] 调用 get_approval_history 检查审批链"
            ),
            tool_calls=[
                ToolCall("call_002", "get_approval_history", json.dumps({"employee_id": eid})),
            ],
            usage={"prompt_tokens": 800, "completion_tokens": 100, "total_tokens": 900},
            model="mock",
        )

    def _round3(self, eid: str) -> LLMResponse:
        return LLMResponse(
            text=(
                "[分析] 已收集足够证据，可以形成结论。\n"
                "[发现] 审批历史无明显异常，但消费模式偏离需关注。\n"
                "调查完成，准备输出报告。"
            ),
            tool_calls=[],
            usage={"prompt_tokens": 1200, "completion_tokens": 60, "total_tokens": 1260},
            model="mock",
        )

    def _conclude(self, eid: str) -> LLMResponse:
        return LLMResponse(
            text="调查完成。",
            tool_calls=[],
            usage={"prompt_tokens": 200, "completion_tokens": 10, "total_tokens": 210},
            model="mock",
        )

    def _final_response(self, messages: list[dict]) -> LLMResponse:
        eid = self._extract_employee_id(messages)
        report = {
            "summary": (
                f"对员工 {eid} 的调查显示其消费模式存在一定偏离。"
                "未发现确凿欺诈证据，建议人工跟进核实。"
            ),
            "active_hypotheses": [
                {
                    "name": "消费模式异常",
                    "description": "员工近期消费金额和频率偏离历史基线",
                    "confidence": 0.6,
                    "supporting_evidence": ["消费变异系数偏高", "近期金额有上升趋势"],
                    "contradicting_evidence": ["总消费仍在合理范围内"],
                    "status": "active",
                    "sensitivity": "normal",
                },
            ],
            "rejected_hypotheses": [
                {
                    "name": "系统性虚报",
                    "description": "员工有组织地虚构报销",
                    "confidence": 0.1,
                    "supporting_evidence": [],
                    "contradicting_evidence": ["审批驳回率正常", "报销频率与同组一致"],
                    "status": "rejected",
                    "sensitivity": "normal",
                },
            ],
            "factual_findings": [
                "[事实] 审批历史无明显异常",
                "[事实] 消费变异系数偏高",
            ],
            "recommended_actions": [
                {"action": "将该员工纳入下月重点抽查名单", "priority": "medium",
                 "source": "system", "effort": "系统自动"},
                {"action": "核实近期大额消费的业务目的", "priority": "high",
                 "source": "manual", "effort": "审计员 1 小时"},
            ],
            "beyond_system_capability": ["与员工面谈核实消费目的"],
            "recommended_tier": "T2",
            "tier_reasoning": "存在偏离信号但无确凿证据，建议 T2 关注",
        }
        return LLMResponse(
            text=json.dumps(report, ensure_ascii=False, indent=2),
            tool_calls=[],
            usage={"prompt_tokens": 1500, "completion_tokens": 300, "total_tokens": 1800},
            model="mock",
        )

    @staticmethod
    def _extract_employee_id(messages: list[dict]) -> str:
        for m in messages:
            content = str(m.get("content", ""))
            match = re.search(r"EMP[-_]\w+", content)
            if match:
                return match.group()
        return "EMP-001"


# ═══════════════════════════════════════════════════════════════════════════
# Helper: robust JSON parsing (GLM 有时在 JSON 前加文字)
# ═══════════════════════════════════════════════════════════════════════════


def parse_llm_json(text: str) -> dict:
    """从 LLM 输出中容错解析 JSON。

    处理：markdown 包裹、<think> 标签、JSON 前后的多余文字。
    """
    cleaned = text.strip()

    # 去掉 <think>...</think>
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

    # 去掉 markdown code block
    if cleaned.startswith("```"):
        first_nl = cleaned.index("\n") if "\n" in cleaned else 3
        cleaned = cleaned[first_nl + 1:]
        last_fence = cleaned.rfind("```")
        if last_fence >= 0:
            cleaned = cleaned[:last_fence].strip()

    # 直接解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 找第一个 { 到最后一个 }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        try:
            return json.loads(cleaned[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM JSON: %s", cleaned[:200])
    return {}

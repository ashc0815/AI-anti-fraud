"""审计轨迹记录器 - 记录整个分析过程的每一步，用于监管合规（FINRA 可追溯性）"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from concurshield.models.schemas import AgentAction, RuleCheckResult


class AuditTrail:
    """完整审计轨迹，记录处理步骤、规则校验、Agent 调用和最终决策。"""

    def __init__(self, receipt_id: str) -> None:
        self.receipt_id = receipt_id
        self.created_at = datetime.now(timezone.utc).isoformat()
        self._steps: list[dict] = []
        self._rule_checks: list[dict] = []
        self._agent_actions: list[dict] = []
        self._decision: dict | None = None
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def log_step(
        self, step_name: str, input_data: Any, output_data: Any, duration_ms: int
    ) -> None:
        """记录一个处理步骤。"""
        self._steps.append({
            "seq": self._next_seq(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step_name": step_name,
            "input_summary": _summarize(input_data),
            "output_summary": _summarize(output_data),
            "duration_ms": duration_ms,
        })

    def log_rule_check(self, result: RuleCheckResult) -> None:
        """记录一条规则校验结果。"""
        self._rule_checks.append({
            "seq": self._next_seq(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rule_id": result.rule_id,
            "rule_name": result.rule_name,
            "passed": result.passed,
            "severity": result.severity,
            "detail": result.detail,
        })

    def log_agent_action(self, action: AgentAction) -> None:
        """记录一次 Agent 工具调用。"""
        self._agent_actions.append({
            "seq": self._next_seq(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": action.agent_name,
            "tool_name": action.tool_name,
            "input_summary": action.input_summary,
            "output_summary": action.output_summary,
            "duration_ms": action.duration_ms,
        })

    def log_decision(self, tier: str, score: float, reasoning: str) -> None:
        """记录最终决策。"""
        self._decision = {
            "seq": self._next_seq(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence_tier": tier,
            "risk_score": score,
            "reasoning": reasoning,
        }

    def export(self) -> dict:
        """导出完整审计轨迹为字典。"""
        return {
            "receipt_id": self.receipt_id,
            "created_at": self.created_at,
            "total_steps": self._seq,
            "steps": list(self._steps),
            "rule_checks": list(self._rule_checks),
            "agent_actions": list(self._agent_actions),
            "decision": self._decision,
        }

    def export_markdown(self) -> str:
        """导出为人类可读的 markdown 格式。"""
        lines: list[str] = []
        lines.append(f"# Audit Trail: {self.receipt_id}")
        lines.append(f"**Created:** {self.created_at}\n")

        # 处理步骤摘要
        lines.append("## Processing Steps")
        if self._steps:
            lines.append("| # | Step | Duration | Input | Output |")
            lines.append("|---|------|----------|-------|--------|")
            for s in self._steps:
                lines.append(
                    f"| {s['seq']} | {s['step_name']} | {s['duration_ms']}ms "
                    f"| {s['input_summary']} | {s['output_summary']} |"
                )
        else:
            lines.append("_No processing steps recorded._")
        lines.append("")

        # 规则检查详情
        lines.append("## Rule Checks")
        if self._rule_checks:
            lines.append("| # | Rule | Result | Severity | Detail |")
            lines.append("|---|------|--------|----------|--------|")
            for r in self._rule_checks:
                icon = "PASS" if r["passed"] else "FAIL"
                lines.append(
                    f"| {r['seq']} | {r['rule_id']} {r['rule_name']} "
                    f"| {icon} | {r['severity']} | {r['detail']} |"
                )
        else:
            lines.append("_No rule checks recorded._")
        lines.append("")

        # Agent 调用链
        lines.append("## Agent Actions")
        if self._agent_actions:
            for a in self._agent_actions:
                lines.append(
                    f"**[{a['seq']}] {a['agent_name']} -> {a['tool_name']}** "
                    f"({a['duration_ms']}ms)"
                )
                lines.append(f"- Input: {a['input_summary']}")
                lines.append(f"- Output: {a['output_summary']}")
                lines.append("")
        else:
            lines.append("_No agent actions recorded._")
        lines.append("")

        # 最终决策与推理
        lines.append("## Decision")
        if self._decision:
            d = self._decision
            lines.append(f"- **Confidence Tier:** {d['confidence_tier']}")
            lines.append(f"- **Risk Score:** {d['risk_score']:.1f}")
            lines.append(f"- **Reasoning:** {d['reasoning']}")
        else:
            lines.append("_No decision recorded._")
        lines.append("")

        return "\n".join(lines)


def _summarize(data: Any) -> str:
    """将任意数据转为简短摘要字符串。"""
    if data is None:
        return "-"
    s = str(data)
    if len(s) > 120:
        return s[:117] + "..."
    return s

"""复合风险评分器 - 综合各模块结果计算最终风险得分"""

from typing import Literal

from concurshield.models.schemas import AgentAction, ForensicReport, RuleCheckResult


def compute_risk_score(
    rule_checks: list[RuleCheckResult],
    agent_actions: list[AgentAction],
    duplicate_matches: list[str],
) -> tuple[float, dict]:
    """综合各模块结果，计算 0-100 的复合风险得分。

    返回总分和分项得分：
    - document_score: 文档层面得分
    - behavioral_score: 行为层面得分
    - cross_ref_score: 交叉引用得分

    Args:
        rule_checks: 规则校验结果列表。
        agent_actions: Agent 工具调用记录。
        duplicate_matches: 匹配到的历史 receipt_id 列表。

    Returns:
        (risk_score, risk_breakdown) 元组。
    """
    pass


def determine_confidence_tier(
    risk_score: float, agent_invoked: bool
) -> Literal["T1", "T2", "T3", "T4"]:
    """根据风险得分和是否触发 Agent 判定置信分层。

    - T1: 自动通过（低风险，无需 Agent）
    - T2: 自动通过但标记观察
    - T3: 需人工审核
    - T4: 自动拒绝（高风险）

    Args:
        risk_score: 风险得分 (0-100)。
        agent_invoked: 是否触发了 Agent 分析。

    Returns:
        置信分层标识。
    """
    pass


def generate_recommendation(report: ForensicReport) -> str:
    """根据取证报告生成处理建议。

    Args:
        report: 取证报告。

    Returns:
        处理建议文本。
    """
    pass

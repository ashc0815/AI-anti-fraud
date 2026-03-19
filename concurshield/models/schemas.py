"""Pydantic v2 数据模型定义"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── 发票上传输入 ──────────────────────────────────────────────


class ReceiptInput(BaseModel):
    """发票上传输入模型"""
    file_path: str = Field(..., description="发票图片文件路径")
    submitted_by: str = Field(default="anonymous", description="提交人")
    submitted_at: datetime = Field(default_factory=datetime.now, description="提交时间")


# ── OCR 结构化输出 ────────────────────────────────────────────


class ReceiptItem(BaseModel):
    """收据行项"""
    description: str = Field(..., description="商品/服务描述")
    quantity: float = Field(default=1, description="数量")
    unit_price: float = Field(..., description="单价")
    amount: float = Field(..., description="行项金额")


class ReceiptData(BaseModel):
    """OCR 结构化输出"""
    merchant_name: str = Field(..., description="商户名称")
    merchant_address: Optional[str] = Field(default=None, description="商户地址")
    merchant_country: str = Field(..., description="商户国家（ISO 3166-1 alpha-2，如 CN、AU）")
    date: str = Field(..., description="交易日期（YYYY-MM-DD）")
    currency: str = Field(..., description="币种（ISO 4217，如 CNY、AUD）")
    items: list[ReceiptItem] = Field(default_factory=list, description="行项列表")
    subtotal: Optional[float] = Field(default=None, description="小计")
    tax_amount: Optional[float] = Field(default=None, description="税额")
    tax_rate: Optional[float] = Field(default=None, description="税率")
    total: float = Field(..., description="总金额")
    raw_text: str = Field(default="", description="OCR 原始识别文本")


# ── 规则校验 ──────────────────────────────────────────────────


class RuleCheckResult(BaseModel):
    """单条规则校验结果"""
    rule_id: str = Field(..., description="规则 ID（如 MATH_001）")
    rule_name: str = Field(..., description="规则名称（如 行项加总校验）")
    passed: bool = Field(..., description="是否通过")
    severity: Literal["info", "warning", "critical"] = Field(..., description="严重程度")
    detail: str = Field(default="", description="具体描述")


# ── Agent 工具调用记录 ────────────────────────────────────────


class AgentAction(BaseModel):
    """Agent 的一次工具调用记录"""
    agent_name: str = Field(..., description="Agent 名称")
    tool_name: str = Field(..., description="工具名称（如 web_search、claude_vision）")
    input_summary: str = Field(default="", description="输入摘要")
    output_summary: str = Field(default="", description="输出摘要")
    timestamp: datetime = Field(default_factory=datetime.now, description="调用时间")
    duration_ms: int = Field(default=0, description="耗时（毫秒）")


# ── 最终取证报告 ──────────────────────────────────────────────


class ForensicReport(BaseModel):
    """最终取证报告"""
    receipt_id: str = Field(..., description="发票唯一 ID（UUID）")
    receipt_data: ReceiptData = Field(..., description="OCR 结构化数据")
    rule_checks: list[RuleCheckResult] = Field(default_factory=list, description="规则校验结果")
    agent_invoked: bool = Field(default=False, description="是否触发了 Agent 分析")
    agent_actions: list[AgentAction] = Field(default_factory=list, description="Agent 工具调用记录")
    confidence_tier: Literal["T1", "T2", "T3", "T4"] = Field(..., description="置信分层")
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0, description="风险得分（0-100）")
    risk_breakdown: dict = Field(
        default_factory=lambda: {
            "document_score": 0.0,
            "behavioral_score": 0.0,
            "cross_ref_score": 0.0,
        },
        description="风险分项得分",
    )
    recommended_action: str = Field(default="", description="建议操作")
    reasoning_chain: str = Field(default="", description="Agent 完整推理链")
    hash_value: str = Field(default="", description="感知哈希值")
    duplicate_matches: list[str] = Field(default_factory=list, description="匹配到的历史 receipt_id")
    created_at: datetime = Field(default_factory=datetime.now, description="报告生成时间")


# ── 审计日志 ──────────────────────────────────────────────────


class AuditLogEntry(BaseModel):
    """审计日志条目"""
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    action: str = Field(..., description="操作类型")
    receipt_id: str = Field(..., description="关联发票 ID")
    actor: str = Field(default="system", description="执行者")
    detail: str = Field(default="", description="详细信息")

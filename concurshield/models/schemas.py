"""Pydantic v2 数据模型定义"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """风险等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReceiptInput(BaseModel):
    """发票上传输入模型"""
    file_path: str = Field(..., description="发票图片文件路径")
    submitted_by: str = Field(default="anonymous", description="提交人")
    submitted_at: datetime = Field(default_factory=datetime.now, description="提交时间")


class OCRResult(BaseModel):
    """OCR 识别结果"""
    merchant_name: Optional[str] = Field(default=None, description="商户名称")
    total_amount: Optional[float] = Field(default=None, description="总金额")
    currency: str = Field(default="CNY", description="币种")
    date: Optional[str] = Field(default=None, description="交易日期")
    items: list[str] = Field(default_factory=list, description="消费明细")
    raw_text: str = Field(default="", description="原始识别文本")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="识别置信度")


class RuleCheckResult(BaseModel):
    """单条规则检查结果"""
    rule_name: str = Field(..., description="规则名称")
    passed: bool = Field(..., description="是否通过")
    detail: str = Field(default="", description="详细说明")
    severity: RiskLevel = Field(default=RiskLevel.LOW, description="严重程度")


class DuplicateCheckResult(BaseModel):
    """重复检测结果"""
    is_duplicate: bool = Field(default=False, description="是否重复")
    similar_receipt_ids: list[str] = Field(default_factory=list, description="相似发票 ID 列表")
    hash_distance: Optional[int] = Field(default=None, description="哈希距离")


class AgentFinding(BaseModel):
    """子 Agent 分析结果"""
    agent_name: str = Field(..., description="Agent 名称")
    finding: str = Field(..., description="分析结论")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="风险等级")
    evidence: list[str] = Field(default_factory=list, description="证据列表")


class RiskReport(BaseModel):
    """综合风险评估报告"""
    receipt_id: str = Field(..., description="发票唯一 ID")
    overall_risk_score: float = Field(default=0.0, ge=0.0, le=1.0, description="综合风险得分")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="风险等级")
    ocr_result: Optional[OCRResult] = Field(default=None, description="OCR 结果")
    rule_results: list[RuleCheckResult] = Field(default_factory=list, description="规则检查结果")
    duplicate_result: Optional[DuplicateCheckResult] = Field(default=None, description="重复检测结果")
    agent_findings: list[AgentFinding] = Field(default_factory=list, description="Agent 分析结果")
    recommendation: str = Field(default="", description="处理建议")
    created_at: datetime = Field(default_factory=datetime.now, description="报告生成时间")


class AuditLogEntry(BaseModel):
    """审计日志条目"""
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    action: str = Field(..., description="操作类型")
    receipt_id: str = Field(..., description="关联发票 ID")
    actor: str = Field(default="system", description="执行者")
    detail: str = Field(default="", description="详细信息")

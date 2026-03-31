"""ConcurShield Agent — tools, scoring, LLM client, investigation, orchestration."""

from concurshield.agent.tools import Tool, ToolRegistry, create_default_registry
from concurshield.agent.risk_scorer import EmployeeRiskScorer, MockEmployeeData, RiskScore
from concurshield.agent.llm_client import LLMClient, LLMResponse, ToolCall, parse_llm_json
from concurshield.agent.investigator import (
    InvestigationAgent,
    InvestigationReport,
    InvestigationStep,
    InvestigationHypothesis,
)
from concurshield.agent.orchestrator import (
    ConcurShieldOrchestrator,
    AnalysisResult,
    EmployeeResult,
)
from concurshield.agent.mock_data import MockCompanyGenerator, generate_company

__all__ = [
    # Tools
    "Tool",
    "ToolRegistry",
    "create_default_registry",
    # Risk scoring
    "EmployeeRiskScorer",
    "MockEmployeeData",
    "RiskScore",
    # LLM client
    "LLMClient",
    "LLMResponse",
    "ToolCall",
    "parse_llm_json",
    # Investigation
    "InvestigationAgent",
    "InvestigationReport",
    "InvestigationStep",
    "InvestigationHypothesis",
    # Orchestration
    "ConcurShieldOrchestrator",
    "AnalysisResult",
    "EmployeeResult",
    # Mock data
    "MockCompanyGenerator",
    "generate_company",
]

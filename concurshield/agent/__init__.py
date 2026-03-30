"""ConcurShield Agent — tools, scoring, investigation, and orchestration."""

from concurshield.agent.tools import Tool, ToolRegistry, create_default_registry
from concurshield.agent.risk_scorer import EmployeeRiskScorer, MockEmployeeData, RiskScore
from concurshield.agent.investigator import (
    InvestigationAgent,
    InvestigationReport,
    InvestigationStep,
    InvestigationHypothesis,
    MockLLMClient,
)
from concurshield.agent.orchestrator import (
    ConcurShieldOrchestrator,
    ProcessingResult,
    BatchResult,
)

__all__ = [
    # Tools
    "Tool",
    "ToolRegistry",
    "create_default_registry",
    # Risk scoring
    "EmployeeRiskScorer",
    "MockEmployeeData",
    "RiskScore",
    # Investigation
    "InvestigationAgent",
    "InvestigationReport",
    "InvestigationStep",
    "InvestigationHypothesis",
    "MockLLMClient",
    # Orchestration
    "ConcurShieldOrchestrator",
    "ProcessingResult",
    "BatchResult",
]

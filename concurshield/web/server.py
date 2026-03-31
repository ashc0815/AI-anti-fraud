"""ConcurShield Web Server — FastAPI + SSE 实时推理。

启动: python -m concurshield.web.server → http://localhost:8501

API:
  GET  /api/dashboard              → 仪表盘统计
  GET  /api/risk-scores            → 全员风险排名
  GET  /api/employee/{id}/profile  → 员工画像详情
  POST /api/investigate            → 启动 Agent 调查
  GET  /api/investigate/{id}/stream → SSE 实时推理
  GET  /api/investigations         → 历史调查列表
  POST /api/upload-csv             → 上传 CSV 数据
  GET  /api/settings               → 当前设置
  PUT  /api/settings               → 更新设置
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure project root on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from concurshield.agent.investigator import InvestigationAgent, InvestigationReport
from concurshield.agent.llm_client import LLMClient, LLMResponse
from concurshield.agent.mock_data import MockCompanyGenerator, generate_company, FRAUD_IDS
from concurshield.agent.orchestrator import ConcurShieldOrchestrator
from concurshield.agent.risk_scorer import EmployeeRiskScorer, RiskScore
from concurshield.agent.tools import ToolRegistry, create_default_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# App state
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(title="ConcurShield", version="2.0")

_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Global state
_registry = create_default_registry()
_scorer = EmployeeRiskScorer()
_company_data: dict[str, list[dict]] = MockCompanyGenerator().generate()
_investigations: dict[str, dict] = {}
_investigation_history: list[dict] = []

# Settings
_settings: dict[str, Any] = {
    "llm_provider": "mock",
    "api_key": "",
    "risk_threshold": 61,
    "random_sample_rate": 0.03,
    "max_rounds": 6,
    "max_api_calls": 3,
    "data_source": "mock",
}


def _get_llm() -> LLMClient:
    return LLMClient(
        provider=_settings["llm_provider"],
        api_key=_settings["api_key"] or None,
    )


def _get_orch() -> ConcurShieldOrchestrator:
    return ConcurShieldOrchestrator(
        _company_data,
        llm_provider=_settings["llm_provider"],
        random_sample_rate=_settings["random_sample_rate"],
    )


# ═══════════════════════════════════════════════════════════════════════════
# GET / → HTML
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = _static_dir / "index.html"
    return html_path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/dashboard
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/dashboard")
async def dashboard():
    scores = _scorer.batch_score_all(_company_data)

    total_records = sum(len(v) for v in _company_data.values())
    total_amount = sum(r["amount"] for exps in _company_data.values() for r in exps)

    by_class = {"normal": 0, "elevated": 0, "high": 0}
    for s in scores:
        by_class[s.classification] = by_class.get(s.classification, 0) + 1

    score_distribution = [0] * 10  # 0-9, 10-19, ..., 90-100
    for s in scores:
        bucket = min(s.total_score // 10, 9)
        score_distribution[bucket] += 1

    return {
        "total_employees": len(_company_data),
        "total_records": total_records,
        "total_amount": round(total_amount, 2),
        "investigations_completed": len(_investigation_history),
        "by_classification": by_class,
        "score_distribution": score_distribution,
        "top_risk": [
            {
                "employee_id": s.employee_id,
                "score": s.total_score,
                "classification": s.classification,
                "top_factor": s.top_risk_factors[0] if s.top_risk_factors else "",
            }
            for s in scores[:5]
        ],
        "data_source": _settings["data_source"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/risk-scores
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/risk-scores")
async def risk_scores():
    scores = _scorer.batch_score_all(_company_data)
    return [
        {
            "employee_id": s.employee_id,
            "total_score": s.total_score,
            "classification": s.classification,
            "dimension_scores": s.dimension_scores,
            "top_risk_factors": s.top_risk_factors,
            "yoy_correction": getattr(s, "yoy_correction", "no_yoy_correction"),
        }
        for s in scores
    ]


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/employee/{id}/profile
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/employee/{employee_id}/profile")
async def employee_profile(employee_id: str):
    expenses = _company_data.get(employee_id)
    if expenses is None:
        raise HTTPException(404, f"Employee {employee_id} not found")

    score = _scorer.score(employee_id, expenses, _company_data)

    # Monthly totals
    from collections import Counter
    from datetime import datetime

    monthly: dict[str, float] = {}
    cat_totals: dict[str, float] = {}
    city_counter: Counter = Counter()
    merchant_counter: Counter = Counter()

    for r in expenses:
        mk = r["date"][:7]
        monthly[mk] = monthly.get(mk, 0) + r["amount"]
        cat_totals[r["category"]] = cat_totals.get(r["category"], 0) + r["amount"]
        city_counter[r.get("city", "")] += 1
        merchant_counter[r.get("merchant", "")] += 1

    return {
        "employee_id": employee_id,
        "risk_score": score.model_dump(),
        "total_expenses": len(expenses),
        "total_amount": round(sum(r["amount"] for r in expenses), 2),
        "monthly_totals": dict(sorted(monthly.items())),
        "category_totals": cat_totals,
        "top_cities": city_counter.most_common(5),
        "top_merchants": merchant_counter.most_common(5),
        "recent_expenses": [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in sorted(expenses, key=lambda x: x["date"], reverse=True)[:20]
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/investigate
# ═══════════════════════════════════════════════════════════════════════════


class InvestigateRequest(BaseModel):
    employee_id: str
    trigger_reason: str = "手动触发"


@app.post("/api/investigate")
async def start_investigation(req: InvestigateRequest):
    if req.employee_id not in _company_data:
        raise HTTPException(404, f"Employee {req.employee_id} not found")

    inv_id = str(uuid.uuid4())[:8]
    _investigations[inv_id] = {
        "id": inv_id,
        "employee_id": req.employee_id,
        "status": "running",
        "progress": 0,
        "current_round": 0,
        "events": [],
        "report": None,
        "started_at": time.time(),
    }

    asyncio.create_task(_run_investigation(inv_id, req.employee_id, req.trigger_reason))
    return {"investigation_id": inv_id, "status": "running"}


async def _run_investigation(inv_id: str, employee_id: str, trigger_reason: str):
    try:
        llm = _get_llm()
        agent = _StreamingAgent(inv_id, llm=llm, tool_registry=_registry)
        expenses = _company_data.get(employee_id, [])

        risk_score = _scorer.score(employee_id, expenses, _company_data) if expenses else None

        report = await agent.investigate(
            employee_id=employee_id,
            trigger_reason=trigger_reason,
            expense_data={"expenses": expenses[:20]},
        )

        _investigations[inv_id]["status"] = "completed"
        _investigations[inv_id]["progress"] = 100
        _investigations[inv_id]["report"] = report.model_dump()

        _push_event(inv_id, "complete", {
            "summary": report.summary,
            "recommended_tier": report.recommended_tier,
            "tier_reasoning": report.tier_reasoning,
            "active_hypotheses": [h.model_dump() for h in report.active_hypotheses],
            "rejected_hypotheses": [h.model_dump() for h in report.rejected_hypotheses],
            "factual_findings": report.factual_findings,
            "recommended_actions": report.recommended_actions,
            "beyond_system_capability": report.beyond_system_capability,
        })

        _investigation_history.insert(0, {
            "id": inv_id,
            "employee_id": employee_id,
            "trigger_reason": trigger_reason,
            "recommended_tier": report.recommended_tier,
            "total_rounds": report.total_rounds,
            "hypotheses_count": len(report.active_hypotheses),
            "summary": report.summary,
            "risk_score": risk_score.total_score if risk_score else None,
            "completed_at": time.time(),
            "duration_ms": report.total_duration_ms,
        })

    except Exception as e:
        logger.error("Investigation %s failed: %s", inv_id, e)
        _investigations[inv_id]["status"] = "failed"
        _push_event(inv_id, "error", {"message": str(e)})


class _StreamingAgent(InvestigationAgent):
    """推送 SSE 事件的 Agent 子类。"""

    def __init__(self, inv_id: str, **kwargs):
        super().__init__(**kwargs)
        self._inv_id = inv_id
        self._orig_llm = self.llm
        self.llm = _EventPushLLM(self._orig_llm, inv_id, self.tools)


class _EventPushLLM:
    """包装 LLM，在每次响应后推送 SSE 事件。"""

    def __init__(self, inner: LLMClient, inv_id: str, tools: ToolRegistry):
        self._inner = inner
        self._inv_id = inv_id
        self._tools = tools
        self._round = 0

    async def chat(self, messages, tools=None, temperature=None, **kw):
        self._round += 1
        inv = _investigations.get(self._inv_id)
        if inv:
            inv["current_round"] = self._round
            inv["progress"] = min(90, self._round * 15)

        resp = await self._inner.chat(messages=messages, tools=tools, temperature=temperature, **kw)

        # 最终报告请求不推送过程事件
        if not tools:
            return resp

        _push_event(self._inv_id, "reasoning", {
            "round": self._round,
            "text": resp.text,
        })

        if resp.tool_calls:
            for tc in resp.tool_calls:
                args = tc.parsed_args()
                _push_event(self._inv_id, "tool_call", {
                    "round": self._round,
                    "tool_name": tc.name,
                    "args": args,
                })
                try:
                    result = self._tools.execute(tc.name, **args)
                except Exception as e:
                    result = {"error": str(e)}

                sentiment = _classify_finding(result)
                _push_event(self._inv_id, "tool_result", {
                    "round": self._round,
                    "tool_name": tc.name,
                    "result": result,
                    "sentiment": sentiment,
                })
        else:
            _push_event(self._inv_id, "conclude", {
                "round": self._round,
                "text": resp.text,
            })

        return resp


def _push_event(inv_id: str, event_type: str, data: dict):
    if inv_id in _investigations:
        _investigations[inv_id]["events"].append({
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        })


def _classify_finding(result: dict) -> str:
    s = json.dumps(result, ensure_ascii=False).lower()
    neg = ["is_duplicate", "is_outlier", "is_exclusive", "异常", "不一致", "可疑", "contradiction"]
    pos = ["passed", "feasible", "正常", "合理"]
    for kw in neg:
        if kw in s and result.get(kw) is True:
            return "negative"
    if result.get("passed") is False or result.get("contradiction_detected") is True:
        return "negative"
    for kw in pos:
        if kw in s:
            return "positive"
    return "neutral"


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/investigate/{id}/stream — SSE
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/investigate/{inv_id}/stream")
async def investigation_stream(inv_id: str):
    if inv_id not in _investigations:
        raise HTTPException(404, "Investigation not found")
    return StreamingResponse(
        _sse_generator(inv_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _sse_generator(inv_id: str):
    last_idx = 0
    while True:
        inv = _investigations.get(inv_id)
        if not inv:
            break

        events = inv["events"]
        while last_idx < len(events):
            evt = events[last_idx]
            data = json.dumps(evt, ensure_ascii=False, default=str)
            yield f"event: {evt['type']}\ndata: {data}\n\n"
            last_idx += 1

        if inv["status"] in ("completed", "failed"):
            yield f"event: done\ndata: {json.dumps({'status': inv['status']})}\n\n"
            break

        await asyncio.sleep(0.3)


# JSON polling fallback
@app.get("/api/investigate/{inv_id}/status")
async def investigation_status(inv_id: str):
    if inv_id not in _investigations:
        raise HTTPException(404, "Investigation not found")
    inv = _investigations[inv_id]
    return {
        "id": inv_id,
        "status": inv["status"],
        "progress": inv["progress"],
        "current_round": inv["current_round"],
        "events": inv["events"],
        "report": inv.get("report"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/investigations
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/investigations")
async def investigations():
    return _investigation_history


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/upload-csv
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    global _company_data

    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")

    from concurshield.data.csv_loader import load_csv_string
    result = load_csv_string(text)

    if not result.is_valid:
        return {
            "success": False,
            "error": f"CSV 验证失败：缺少字段 {result.missing_fields}",
            "warnings": result.warnings,
        }

    _company_data = result.company
    _settings["data_source"] = file.filename or "uploaded_csv"

    return {
        "success": True,
        "total_records": result.total_records,
        "total_employees": len(result.company),
        "employee_ids": result.employee_ids,
        "field_mapping": result.field_mapping,
        "warnings": result.warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════
# GET/PUT /api/settings
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/settings")
async def get_settings():
    safe = dict(_settings)
    if safe.get("api_key"):
        safe["api_key"] = safe["api_key"][:4] + "****"
    return safe


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    api_key: str | None = None
    risk_threshold: int | None = None
    random_sample_rate: float | None = None
    max_rounds: int | None = None
    max_api_calls: int | None = None


@app.put("/api/settings")
async def update_settings(req: SettingsUpdate):
    for field, val in req.model_dump(exclude_none=True).items():
        _settings[field] = val
    return {"success": True, "settings": _settings}


# ═══════════════════════════════════════════════════════════════════════════
# __main__
# ═══════════════════════════════════════════════════════════════════════════

# Make this a proper package entry point
_init_path = Path(__file__).parent / "__init__.py"
if not _init_path.exists():
    _init_path.write_text("")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8501))
    uvicorn.run(
        "concurshield.web.server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )

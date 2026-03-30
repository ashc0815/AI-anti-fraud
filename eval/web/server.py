"""ConcurShield Eval Dashboard — Flask server with investigation APIs.

Endpoints:
  GET  /                                → Dashboard UI
  GET  /api/risk-scores                 → All employee risk scores (desc)
  POST /api/investigate                 → Start async investigation
  GET  /api/investigate/<id>/status     → SSE stream of investigation progress
  GET  /api/investigation-history       → Historical investigation reports
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# Ensure project root is on sys.path so `concurshield` is importable
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
import threading
import time
import uuid
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory

from concurshield.agent.investigator import InvestigationAgent, MockLLMClient
from concurshield.agent.orchestrator import ConcurShieldOrchestrator
from concurshield.agent.risk_scorer import EmployeeRiskScorer, MockEmployeeData
from concurshield.agent.tools import create_default_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

# ═══════════════════════════════════════════════════════════════════════════
# Global state
# ═══════════════════════════════════════════════════════════════════════════

_registry = create_default_registry()
_scorer = EmployeeRiskScorer(_registry)
_agent = InvestigationAgent(registry=_registry)
_orchestrator = ConcurShieldOrchestrator(
    tool_registry=_registry,
    risk_scorer=_scorer,
    agent=_agent,
    random_sample_rate=0.0,
)

# Mock company data (generated once on startup)
_mock = MockEmployeeData()
_company_data = _mock.generate_company()

# In-memory stores
_investigations: dict[str, dict] = {}  # id → {status, report, events, ...}
_investigation_history: list[dict] = []


# ═══════════════════════════════════════════════════════════════════════════
# Static files
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:path>")
def static_files(path: str):
    return send_from_directory("static", path)


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/risk-scores
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/api/risk-scores")
def get_risk_scores():
    """Return all employee risk scores sorted descending."""
    scores = _scorer.batch_score_all(_company_data)
    result = []
    for s in scores:
        result.append({
            "employee_id": s.employee_id,
            "total_score": s.total_score,
            "classification": s.classification,
            "dimension_scores": s.dimension_scores,
            "top_risk_factors": s.top_risk_factors,
        })
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/investigate
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/api/investigate", methods=["POST"])
def start_investigation():
    """Start an async investigation. Returns investigation_id for polling."""
    data = request.get_json(force=True)
    employee_id = data.get("employee_id", "EMP-001")
    expense_data = data.get("expense_data", {})
    image_path = data.get("image_path")

    inv_id = str(uuid.uuid4())[:8]

    # Populate expense_data from company mock if empty
    if not expense_data.get("expenses") and employee_id in _company_data:
        expense_data["expenses"] = _company_data[employee_id]

    # Get risk score for trigger reason
    emp_expenses = _company_data.get(employee_id, [])
    risk_score = None
    if emp_expenses:
        risk_score = _scorer.score(employee_id, emp_expenses, _company_data)

    trigger_reason = f"手动触发调查"
    if risk_score:
        trigger_reason += f" (Risk Score: {risk_score.total_score}, {risk_score.classification})"
        if risk_score.top_risk_factors:
            trigger_reason += f" — {risk_score.top_risk_factors[0]}"

    _investigations[inv_id] = {
        "id": inv_id,
        "employee_id": employee_id,
        "status": "running",
        "progress": 0,
        "current_round": 0,
        "total_rounds": 0,
        "events": [],  # SSE event log
        "report": None,
        "started_at": time.time(),
    }

    # Run investigation in background thread
    thread = threading.Thread(
        target=_run_investigation_bg,
        args=(inv_id, employee_id, trigger_reason, expense_data, image_path),
        daemon=True,
    )
    thread.start()

    return jsonify({"investigation_id": inv_id, "status": "running"})


def _run_investigation_bg(
    inv_id: str,
    employee_id: str,
    trigger_reason: str,
    expense_data: dict,
    image_path: str | None,
) -> None:
    """Run investigation in a background thread with an event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Create a streaming agent that pushes events
        streaming_agent = _StreamingInvestigationAgent(
            inv_id=inv_id,
            registry=_registry,
        )

        report = loop.run_until_complete(
            streaming_agent.investigate(
                employee_id=employee_id,
                trigger_reason=trigger_reason,
                expense_data=expense_data,
            )
        )

        _investigations[inv_id]["status"] = "completed"
        _investigations[inv_id]["progress"] = 100
        _investigations[inv_id]["report"] = report.model_dump()
        _investigations[inv_id]["total_rounds"] = report.total_rounds

        # Push completion event
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

        # Save to history
        _investigation_history.insert(0, {
            "id": inv_id,
            "employee_id": employee_id,
            "trigger_reason": trigger_reason,
            "recommended_tier": report.recommended_tier,
            "total_rounds": report.total_rounds,
            "hypotheses_count": len(report.active_hypotheses),
            "summary": report.summary,
            "completed_at": time.time(),
            "duration_ms": report.total_duration_ms,
        })

    except Exception as e:
        logger.error("Investigation %s failed: %s", inv_id, e)
        _investigations[inv_id]["status"] = "failed"
        _push_event(inv_id, "error", {"message": str(e)})
    finally:
        loop.close()


class _StreamingInvestigationAgent(InvestigationAgent):
    """Subclass that pushes SSE events after each round."""

    def __init__(self, inv_id: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._inv_id = inv_id

    async def investigate(self, **kwargs: Any):
        """Override to inject streaming events between rounds."""
        # We use the parent's investigate but hook into the MockLLMClient
        # to push events. For real LLM, the same approach works.

        # Wrap the parent's LLM to intercept responses
        original_llm = self.llm
        self.llm = _EventPushingLLM(original_llm, self._inv_id, self.tools)
        report = await super().investigate(**kwargs)
        self.llm = original_llm
        return report


class _EventPushingLLM:
    """Wraps an LLM client to push SSE events on each response."""

    class _Chat:
        class _Completions:
            def __init__(self, parent: _EventPushingLLM) -> None:
                self._parent = parent
                self._round = 0

            async def create(self, **kwargs: Any) -> Any:
                self._round += 1
                inv_id = self._parent._inv_id
                tools_registry = self._parent._tools

                # Update progress
                max_rounds = 6
                progress = min(90, int(self._round / max_rounds * 90))
                if inv_id in _investigations:
                    _investigations[inv_id]["current_round"] = self._round
                    _investigations[inv_id]["progress"] = progress

                # Call real LLM
                response = await self._parent._inner.chat.completions.create(**kwargs)

                msg = response.choices[0].message
                text = msg.content or ""
                tool_calls = msg.tool_calls or []

                # Check if this is the final report request (no tools param)
                is_final = not kwargs.get("tools")
                if is_final:
                    return response

                # Push reasoning event
                _push_event(inv_id, "reasoning", {
                    "round": self._round,
                    "text": text,
                })

                if tool_calls:
                    # Push tool call events
                    for tc in tool_calls:
                        fn_name = tc.function.name
                        try:
                            fn_args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            fn_args = {}

                        _push_event(inv_id, "tool_call", {
                            "round": self._round,
                            "tool_name": fn_name,
                            "args": fn_args,
                        })

                        # Execute and push result
                        try:
                            result = tools_registry.execute(fn_name, **fn_args)
                        except Exception as e:
                            result = {"error": str(e)}

                        # Determine finding sentiment
                        sentiment = _classify_finding(result)
                        _push_event(inv_id, "tool_result", {
                            "round": self._round,
                            "tool_name": fn_name,
                            "result": result,
                            "sentiment": sentiment,
                        })
                else:
                    _push_event(inv_id, "conclude", {
                        "round": self._round,
                        "text": text,
                    })

                return response

        def __init__(self, parent: _EventPushingLLM) -> None:
            self.completions = _EventPushingLLM._Chat._Completions(parent)

    def __init__(self, inner: Any, inv_id: str, tools: Any) -> None:
        self._inner = inner
        self._inv_id = inv_id
        self._tools = tools
        self.chat = _EventPushingLLM._Chat(self)


def _push_event(inv_id: str, event_type: str, data: dict) -> None:
    """Push an SSE event to the investigation's event queue."""
    if inv_id not in _investigations:
        return
    event = {
        "type": event_type,
        "timestamp": time.time(),
        "data": data,
    }
    _investigations[inv_id]["events"].append(event)


def _classify_finding(result: dict) -> str:
    """Classify a tool result as positive/negative/neutral."""
    result_str = json.dumps(result, ensure_ascii=False).lower()

    negative_signals = [
        "is_duplicate", "is_outlier", "is_exclusive",
        "异常", "不一致", "可疑", "失败", "违规",
    ]
    positive_signals = ["passed", "feasible", "正常", "合理"]

    for signal in negative_signals:
        if signal in result_str:
            if result.get(signal) is True or (
                "passed" in result and result.get("passed") is False
            ):
                return "negative"

    for signal in positive_signals:
        if signal in result_str:
            return "positive"

    return "neutral"


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/investigate/<id>/status — SSE stream
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/api/investigate/<inv_id>/status")
def investigation_status(inv_id: str):
    """SSE stream of investigation progress. Falls back to JSON if no SSE."""
    if inv_id not in _investigations:
        return jsonify({"error": "Investigation not found"}), 404

    accept = request.headers.get("Accept", "")
    if "text/event-stream" in accept:
        return Response(
            _sse_generator(inv_id),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # JSON fallback for polling
    inv = _investigations[inv_id]
    return jsonify({
        "id": inv_id,
        "status": inv["status"],
        "progress": inv["progress"],
        "current_round": inv["current_round"],
        "total_rounds": inv["total_rounds"],
        "events": inv["events"],
        "report": inv.get("report"),
    })


def _sse_generator(inv_id: str):
    """Generator that yields SSE events for an investigation."""
    last_idx = 0
    while True:
        if inv_id not in _investigations:
            break

        inv = _investigations[inv_id]
        events = inv["events"]

        # Send new events
        while last_idx < len(events):
            event = events[last_idx]
            data = json.dumps(event, ensure_ascii=False, default=str)
            yield f"event: {event['type']}\ndata: {data}\n\n"
            last_idx += 1

        if inv["status"] in ("completed", "failed"):
            # Send final status
            yield f"event: done\ndata: {json.dumps({'status': inv['status']})}\n\n"
            break

        time.sleep(0.3)


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/investigation-history
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/api/investigation-history")
def investigation_history():
    """Return list of completed investigations."""
    return jsonify(_investigation_history)


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/company-data (helper for frontend)
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/api/company-data")
def company_data():
    """Return summary of mock company data for the dashboard."""
    summary = []
    for eid, expenses in _company_data.items():
        total = sum(e["amount"] for e in expenses)
        cities = list(set(e.get("city", "") for e in expenses))
        summary.append({
            "employee_id": eid,
            "expense_count": len(expenses),
            "total_amount": round(total, 2),
            "cities": cities,
        })
    return jsonify(summary)


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)

"""ConcurShield - Streamlit 应用入口

启动方式：streamlit run concurshield/main.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

import streamlit as st

from concurshield.db import store
from concurshield.models.schemas import ForensicReport
from concurshield.pipeline import PipelineError, analyze_receipt

logger = logging.getLogger(__name__)

# ── Tier 颜色映射 ────────────────────────────────────────────────

TIER_COLORS = {
    "T1": "#28a745",  # 绿
    "T2": "#ffc107",  # 黄
    "T3": "#fd7e14",  # 橙
    "T4": "#dc3545",  # 红
}

TIER_LABELS = {
    "T1": "Auto-pass",
    "T2": "Advisory",
    "T3": "Review Required",
    "T4": "Hard Block",
}


# ── 工具函数 ──────────────────────────────────────────────────────


def _run_async(coro):
    """在 Streamlit 同步环境中运行 async 协程。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _get_all_receipts() -> list[dict]:
    """从 SQLite 读取所有收据摘要信息。"""
    conn = store._get_conn()
    try:
        rows = conn.execute(
            "SELECT receipt_id, receipt_json, forensic_report_json, created_at "
            "FROM receipts ORDER BY created_at DESC"
        ).fetchall()
        results = []
        for row in rows:
            receipt = json.loads(row["receipt_json"])
            report = json.loads(row["forensic_report_json"])
            results.append({
                "receipt_id": row["receipt_id"][:8] + "...",
                "merchant": receipt.get("merchant_name", ""),
                "date": receipt.get("date", ""),
                "total": f"{receipt.get('total', 0)} {receipt.get('currency', '')}",
                "tier": report.get("confidence_tier", ""),
                "score": report.get("risk_score", 0),
                "created_at": row["created_at"],
            })
        return results
    except Exception:
        return []
    finally:
        conn.close()


# ── 主流程 ────────────────────────────────────────────────────────


def main() -> None:
    """Streamlit 应用主函数。"""
    st.set_page_config(
        page_title="ConcurShield",
        page_icon="\U0001f6e1\ufe0f",
        layout="wide",
    )

    st.title("ConcurShield \u2014 Agentic AI \u6536\u636e\u53d6\u8bc1\u5de5\u4f5c\u53f0")
    st.caption("MVP v1.0")

    # 初始化数据库
    store.init_db()

    # 侧边栏
    thresholds, hash_threshold, show_audit = render_sidebar()

    # 上传区域
    uploaded_file = render_upload_section()

    # 分析与结果展示
    if uploaded_file is not None:
        process_and_render(uploaded_file, thresholds, hash_threshold, show_audit)

    # 底部历史记录
    render_history()


# ── 侧边栏 ────────────────────────────────────────────────────────


def render_sidebar() -> tuple[dict, float, bool]:
    """渲染侧边栏：配置项。"""
    with st.sidebar:
        st.header("Configuration")

        st.subheader("Confidence Tier Thresholds")
        t1_t2 = st.slider("T1/T2 Boundary", 0, 100, 25, key="t1t2")
        t2_t3 = st.slider("T2/T3 Boundary", 0, 100, 55, key="t2t3")
        t3_t4 = st.slider("T3/T4 Boundary", 0, 100, 80, key="t3t4")

        st.subheader("Duplicate Detection")
        hash_threshold = st.slider(
            "Hash Similarity Threshold",
            0.80, 1.00, 0.92, 0.01,
            key="hash_thresh",
        )

        st.subheader("Display")
        show_audit = st.toggle("Show Full Audit Trail", value=False, key="show_audit")

    return {"t1_t2": t1_t2, "t2_t3": t2_t3, "t3_t4": t3_t4}, hash_threshold, show_audit


# ── 上传区域 ──────────────────────────────────────────────────────


def render_upload_section():
    """渲染发票上传区域，返回 uploaded_file 或 None。"""
    st.subheader("Upload Receipt")
    uploaded = st.file_uploader(
        "Upload a receipt image for analysis",
        type=["jpg", "jpeg", "png"],
        key="receipt_upload",
    )
    if uploaded is not None:
        st.image(uploaded, caption="Original Receipt", width=350)
    return uploaded


# ── 核心处理流程 ──────────────────────────────────────────────────


def process_and_render(
    uploaded_file,
    thresholds: dict,
    hash_threshold: float,
    show_audit: bool,
) -> None:
    """用户上传图片后的完整处理流程（委托给 pipeline）。"""
    # 避免重复处理：缓存用 file name + size 做 key
    cache_key = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state.get("_last_cache_key") == cache_key:
        _render_results(st.session_state["_last_report"], show_audit)
        return

    # ── 保存上传文件到临时路径 ────────────────────────────────────
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        image_path = tmp.name

    # ── 调用统一管道 ─────────────────────────────────────────────
    with st.spinner("Analyzing receipt (hash → OCR → rules → agent → scoring → save)..."):
        try:
            report, audit = _run_async(
                analyze_receipt(image_path, hash_threshold=hash_threshold)
            )
        except PipelineError as e:
            st.error(f"Pipeline failed at step **{e.step}**: {e.cause}")
            return
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            return

    # Cache results
    st.session_state["_last_cache_key"] = cache_key
    st.session_state["_last_report"] = {
        "report": report,
        "audit_md": audit.export_markdown(),
        "breakdown": report.risk_breakdown,
    }

    _render_results(st.session_state["_last_report"], show_audit)


# ── 结果渲染 ──────────────────────────────────────────────────────


def _render_results(cached: dict, show_audit: bool) -> None:
    """渲染分析结果。"""
    report: ForensicReport = cached["report"]
    audit_md: str = cached["audit_md"]
    breakdown: dict = cached["breakdown"]

    st.divider()

    # ── 顶部状态栏 ──────────────────────────────────────────────
    tier = report.confidence_tier
    color = TIER_COLORS[tier]
    label = TIER_LABELS[tier]

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        st.markdown(
            f'<div style="background-color:{color};color:white;padding:20px;'
            f'border-radius:10px;text-align:center;">'
            f'<h1 style="margin:0;color:white;">{tier}</h1>'
            f'<p style="margin:4px 0 0 0;">{label}</p></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.metric("Risk Score", f"{report.risk_score:.1f} / 100")
    with col3:
        st.info(report.recommended_action)

    # ── Tabs ─────────────────────────────────────────────────────
    tabs = st.tabs([
        "Structured Data",
        "Rule Checks",
        "Agent Investigation",
        "Score Breakdown",
        "Audit Trail",
    ])

    # Tab 1: Structured Data
    with tabs[0]:
        _render_receipt_data(report.receipt_data)

    # Tab 2: Rule Checks
    with tabs[1]:
        _render_rule_checks(report.rule_checks)

    # Tab 3: Agent Investigation
    with tabs[2]:
        _render_agent_results(report)

    # Tab 4: Score Breakdown
    with tabs[3]:
        _render_score_breakdown(breakdown, report.risk_score)

    # Tab 5: Audit Trail
    with tabs[4]:
        if show_audit:
            st.markdown(audit_md)
        else:
            st.info("Enable 'Show Full Audit Trail' in the sidebar to view.")
            with st.expander("Preview"):
                st.markdown(audit_md)


def _render_receipt_data(receipt_data) -> None:
    """Tab 1: 展示 OCR 结构化数据。"""
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Merchant Info**")
        st.write(f"- Name: {receipt_data.merchant_name}")
        st.write(f"- Address: {receipt_data.merchant_address or 'N/A'}")
        st.write(f"- Country: {receipt_data.merchant_country}")
        st.write(f"- Date: {receipt_data.date}")
    with col2:
        st.markdown("**Amount Info**")
        st.write(f"- Subtotal: {receipt_data.subtotal} {receipt_data.currency}")
        st.write(f"- Tax: {receipt_data.tax_amount} (rate: {receipt_data.tax_rate})")
        st.write(f"- **Total: {receipt_data.total} {receipt_data.currency}**")

    if receipt_data.items:
        st.markdown("**Line Items**")
        import pandas as pd
        items_data = [
            {
                "Description": item.description,
                "Qty": item.quantity,
                "Unit Price": item.unit_price,
                "Amount": item.amount,
            }
            for item in receipt_data.items
        ]
        st.dataframe(pd.DataFrame(items_data), use_container_width=True, hide_index=True)

    with st.expander("Raw JSON"):
        st.json(receipt_data.model_dump(mode="json"))


def _render_rule_checks(rule_checks: list) -> None:
    """Tab 2: 规则检查结果。"""
    for r in rule_checks:
        if r.passed:
            st.success(f"**{r.rule_id}** {r.rule_name}: {r.detail}")
        elif r.severity == "warning":
            st.warning(f"**{r.rule_id}** {r.rule_name}: {r.detail}")
        else:  # critical
            st.error(f"**{r.rule_id}** {r.rule_name}: {r.detail}")


def _render_agent_results(report: ForensicReport) -> None:
    """Tab 3: Agent 调查结果。"""
    if not report.agent_invoked:
        st.success("All rules passed. No Agent investigation needed.")
        return

    st.markdown("### Reasoning Chain")
    st.markdown(report.reasoning_chain or "No reasoning chain available.")

    st.markdown("### Sub-Agent Findings")
    for action in report.agent_actions:
        with st.expander(f"{action.agent_name} / {action.tool_name} ({action.duration_ms}ms)"):
            st.write(f"**Input:** {action.input_summary}")
            st.write(f"**Output:** {action.output_summary}")


def _render_score_breakdown(breakdown: dict, composite: float) -> None:
    """Tab 4: 风险评分分解柱状图。"""
    import pandas as pd

    dimensions = {
        "Document": breakdown.get("document_score", 0) or 0,
        "Behavioral": breakdown.get("behavioral_score", 0) or 0,
        "Cross-Ref": breakdown.get("cross_ref_score", 0) or 0,
        "Agent": breakdown.get("agent_score", 0) or 0,
    }

    weights = breakdown.get("weights_used", {})

    df = pd.DataFrame({
        "Dimension": list(dimensions.keys()),
        "Score (0-100)": list(dimensions.values()),
        "Weight": [
            weights.get("document", 0),
            weights.get("behavioral", 0),
            weights.get("cross_ref", 0),
            weights.get("agent", 0),
        ],
        "Weighted": [
            round(dimensions["Document"] * weights.get("document", 0), 1),
            round(dimensions["Behavioral"] * weights.get("behavioral", 0), 1),
            round(dimensions["Cross-Ref"] * weights.get("cross_ref", 0), 1),
            round(dimensions["Agent"] * weights.get("agent", 0), 1),
        ],
    })

    st.bar_chart(df.set_index("Dimension")["Score (0-100)"])

    st.markdown("**Detailed Breakdown**")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.metric("Composite Score", f"{composite:.1f}")


# ── 历史记录 ──────────────────────────────────────────────────────


def render_history() -> None:
    """渲染底部历史记录表格。"""
    st.divider()
    st.subheader("Analysis History")

    records = _get_all_receipts()
    if not records:
        st.info("No receipts analyzed yet.")
        return

    import pandas as pd
    df = pd.DataFrame(records)
    df.columns = ["Receipt ID", "Merchant", "Date", "Amount", "Tier", "Score", "Analyzed At"]

    # 用颜色标记 Tier
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.1f",
            ),
        },
    )


if __name__ == "__main__":
    main()

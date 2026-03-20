"""SQLite 存储层 - 管理发票记录、哈希和风险报告的持久化"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from concurshield.models.schemas import AuditLogEntry, ForensicReport, ReceiptData

_DB_PATH = Path("data/concurshield.db")


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接（自动创建 data/ 目录）。"""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库，创建所需的表结构。

    表：receipts（receipt_id, image_hash, receipt_json, forensic_report_json, created_at）
    """
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id       TEXT PRIMARY KEY,
                image_hash       TEXT NOT NULL,
                receipt_json     TEXT NOT NULL,
                forensic_report_json TEXT NOT NULL,
                created_at       TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
    finally:
        conn.close()


def save_receipt(
    receipt_id: str,
    image_hash: str,
    receipt_data: ReceiptData,
    forensic_report: ForensicReport,
) -> None:
    """保存发票记录到数据库。

    Args:
        receipt_id: 发票唯一 ID。
        image_hash: 图片感知哈希值。
        receipt_data: OCR 结构化数据。
        forensic_report: 取证报告。
    """
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO receipts
                (receipt_id, image_hash, receipt_json, forensic_report_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                image_hash,
                receipt_data.model_dump_json(),
                forensic_report.model_dump_json(),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_hashes() -> list[dict]:
    """获取所有已存储的 receipt_id + hash_value + created_at。

    Returns:
        列表，每项包含 receipt_id, hash_value, created_at。
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT receipt_id, image_hash, created_at FROM receipts"
        ).fetchall()
        return [
            {
                "receipt_id": row["receipt_id"],
                "hash_value": row["image_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_receipt(receipt_id: str) -> dict | None:
    """根据发票 ID 获取完整记录。

    Args:
        receipt_id: 发票 ID。

    Returns:
        包含 receipt_id, image_hash, receipt_data, forensic_report, created_at 的字典，
        不存在时返回 None。
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "receipt_id": row["receipt_id"],
            "image_hash": row["image_hash"],
            "receipt_data": json.loads(row["receipt_json"]),
            "forensic_report": json.loads(row["forensic_report_json"]),
            "created_at": row["created_at"],
        }
    finally:
        conn.close()

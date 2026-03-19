"""SQLite 存储层 - 管理发票记录、哈希和风险报告的持久化"""

from concurshield.models.schemas import AuditLogEntry, RiskReport


def init_db() -> None:
    """初始化数据库，创建所需的表结构。

    表结构：
    - receipts: 发票基本信息
    - hashes: 感知哈希存储
    - reports: 风险报告
    - audit_logs: 审计日志
    """
    pass


def save_report(report: RiskReport) -> str:
    """保存风险报告到数据库。

    Args:
        report: 风险评估报告。

    Returns:
        报告 ID。
    """
    pass


def get_report(receipt_id: str) -> RiskReport | None:
    """根据发票 ID 获取风险报告。

    Args:
        receipt_id: 发票 ID。

    Returns:
        风险报告，不存在时返回 None。
    """
    pass


def get_all_hashes() -> dict[str, str]:
    """获取所有已存储的感知哈希。

    Returns:
        映射 {receipt_id: hash_value}。
    """
    pass


def save_hash(receipt_id: str, hash_value: str) -> None:
    """存储发票的感知哈希值。

    Args:
        receipt_id: 发票 ID。
        hash_value: 感知哈希值。
    """
    pass


def save_audit_log(entry: AuditLogEntry) -> None:
    """写入审计日志条目。

    Args:
        entry: 审计日志条目。
    """
    pass


def get_audit_logs(receipt_id: str) -> list[AuditLogEntry]:
    """获取指定发票的审计日志。

    Args:
        receipt_id: 发票 ID。

    Returns:
        审计日志条目列表。
    """
    pass

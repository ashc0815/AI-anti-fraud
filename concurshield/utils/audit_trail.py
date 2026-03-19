"""审计轨迹记录器 - 记录系统中所有关键操作的审计日志"""

from concurshield.models.schemas import AuditLogEntry


def log_action(action: str, receipt_id: str, actor: str = "system", detail: str = "") -> None:
    """记录一条审计日志。

    Args:
        action: 操作类型（如 'upload', 'analyze', 'flag'）。
        receipt_id: 关联的发票 ID。
        actor: 执行者，默认 'system'。
        detail: 详细信息。
    """
    pass


def get_trail(receipt_id: str) -> list[AuditLogEntry]:
    """获取指定发票的完整审计轨迹。

    Args:
        receipt_id: 发票 ID。

    Returns:
        按时间排序的审计日志列表。
    """
    pass


def export_trail(receipt_id: str, format: str = "json") -> str:
    """导出审计轨迹。

    Args:
        receipt_id: 发票 ID。
        format: 导出格式，支持 'json' 和 'csv'。

    Returns:
        导出的字符串内容。
    """
    pass

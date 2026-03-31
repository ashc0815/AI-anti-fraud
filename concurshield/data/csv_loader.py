"""CSV Loader — 解析 Concur Cognos 导出的 CSV，输出与 MockCompanyGenerator 相同格式。

自动检测中英文字段映射。13 个必需字段 + 可选字段。
支持 UTF-8 / GBK / GB18030 编码自动检测。

必需字段（英文 / 中文）：
  employee_id / 员工编号        approver_id / 审批人编号
  date / 消费日期               city / 消费城市
  merchant / 商户名称           category / 费用类型
  amount / 金额                 currency / 币种
  report_id / 报告编号          expense_id / 费用编号
  department / 部门             cost_center / 成本中心
  payment_type / 支付方式

可选字段：
  comment / 备注                subtotal / 小计
  tax_amount / 税额             tax_rate / 税率
  country / 国家                image_path / 附件路径
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Field mapping: English ↔ Chinese
# ═══════════════════════════════════════════════════════════════════════════

_FIELD_MAP_EN_TO_INTERNAL: dict[str, str] = {
    # Required
    "employee_id": "employee_id",
    "approver_id": "approver_id",
    "date": "date",
    "city": "city",
    "merchant": "merchant",
    "category": "category",
    "amount": "amount",
    "currency": "currency",
    "report_id": "report_id",
    "expense_id": "expense_id",
    "department": "department",
    "cost_center": "cost_center",
    "payment_type": "payment_type",
    # Optional
    "comment": "comment",
    "subtotal": "subtotal",
    "tax_amount": "tax_amount",
    "tax_rate": "tax_rate",
    "country": "country",
    "image_path": "image_path",
    # Common Concur Cognos variants
    "employee id": "employee_id",
    "approver id": "approver_id",
    "expense date": "date",
    "transaction date": "date",
    "vendor name": "merchant",
    "merchant name": "merchant",
    "expense type": "category",
    "report number": "report_id",
    "expense number": "expense_id",
    "cost center": "cost_center",
    "payment method": "payment_type",
}

_FIELD_MAP_CN_TO_INTERNAL: dict[str, str] = {
    "员工编号": "employee_id",
    "员工ID": "employee_id",
    "员工号": "employee_id",
    "审批人编号": "approver_id",
    "审批人ID": "approver_id",
    "审批人": "approver_id",
    "消费日期": "date",
    "交易日期": "date",
    "报销日期": "date",
    "日期": "date",
    "消费城市": "city",
    "城市": "city",
    "商户名称": "merchant",
    "商户": "merchant",
    "供应商": "merchant",
    "费用类型": "category",
    "类别": "category",
    "报销类型": "category",
    "金额": "amount",
    "报销金额": "amount",
    "消费金额": "amount",
    "币种": "currency",
    "货币": "currency",
    "报告编号": "report_id",
    "报告号": "report_id",
    "费用编号": "expense_id",
    "费用ID": "expense_id",
    "部门": "department",
    "成本中心": "cost_center",
    "支付方式": "payment_type",
    "付款方式": "payment_type",
    "备注": "comment",
    "说明": "comment",
    "小计": "subtotal",
    "税额": "tax_amount",
    "税率": "tax_rate",
    "国家": "country",
    "附件路径": "image_path",
    "附件": "image_path",
}

REQUIRED_FIELDS = {
    "employee_id", "approver_id", "date", "city", "merchant",
    "category", "amount", "currency", "report_id", "expense_id",
    "department", "cost_center", "payment_type",
}


# ═══════════════════════════════════════════════════════════════════════════
# Encoding detection
# ═══════════════════════════════════════════════════════════════════════════


def _read_with_encoding(path: Path) -> str:
    """尝试多种编码读取文件。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法解码文件 {path}，尝试了 UTF-8/GB18030/GBK/Latin-1")


# ═══════════════════════════════════════════════════════════════════════════
# Field mapping
# ═══════════════════════════════════════════════════════════════════════════


def _build_column_map(headers: list[str]) -> dict[int, str]:
    """将 CSV 列索引映射到内部字段名。"""
    col_map: dict[int, str] = {}

    for idx, raw_header in enumerate(headers):
        h = raw_header.strip().strip("\ufeff")
        h_lower = h.lower().strip()
        h_no_underscore = h_lower.replace("_", " ")

        # Try exact match (with underscores preserved)
        if h_lower in _FIELD_MAP_EN_TO_INTERNAL:
            col_map[idx] = _FIELD_MAP_EN_TO_INTERNAL[h_lower]
            continue

        # Try with underscores replaced by spaces
        if h_no_underscore in _FIELD_MAP_EN_TO_INTERNAL:
            col_map[idx] = _FIELD_MAP_EN_TO_INTERNAL[h_no_underscore]
            continue

        # Try all English keys case-insensitively
        matched = False
        for en_key, internal in _FIELD_MAP_EN_TO_INTERNAL.items():
            if h_lower == en_key.lower() or h_no_underscore == en_key.lower():
                col_map[idx] = internal
                matched = True
                break

        if not matched:
            # Try Chinese mapping
            for cn_key, internal in _FIELD_MAP_CN_TO_INTERNAL.items():
                if h.strip() == cn_key or h_lower == cn_key.lower():
                    col_map[idx] = internal
                    break

    return col_map


def _check_required(col_map: dict[int, str], headers: list[str]) -> list[str]:
    """检查必需字段是否都已映射。返回缺失字段列表。"""
    mapped = set(col_map.values())
    missing = REQUIRED_FIELDS - mapped
    return sorted(missing)


# ═══════════════════════════════════════════════════════════════════════════
# Parser
# ═══════════════════════════════════════════════════════════════════════════


def _parse_amount(val: str) -> float:
    """解析金额字符串：去逗号、去货币符号。"""
    cleaned = val.strip().replace(",", "").replace("¥", "").replace("$", "").replace("€", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_row(row: list[str], col_map: dict[int, str], row_idx: int) -> dict | None:
    """将一行 CSV 解析为内部 record 格式。"""
    record: dict[str, Any] = {}
    for idx, internal_name in col_map.items():
        if idx >= len(row):
            continue
        val = row[idx].strip()

        if internal_name in ("amount", "subtotal", "tax_amount", "tax_rate"):
            record[internal_name] = _parse_amount(val)
        else:
            record[internal_name] = val

    # 必需字段检查
    if not record.get("employee_id") or not record.get("date"):
        return None

    # 确保有 id 字段
    if "id" not in record:
        record["id"] = row_idx

    # 默认值
    record.setdefault("comment", "")
    record.setdefault("currency", "CNY")
    record.setdefault("amount", 0.0)

    return record


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


class CSVLoadResult:
    """CSV 加载结果。"""

    def __init__(
        self,
        company: dict[str, list[dict]],
        total_records: int,
        skipped_records: int,
        field_mapping: dict[str, str],
        missing_fields: list[str],
        warnings: list[str],
    ) -> None:
        self.company = company
        self.total_records = total_records
        self.skipped_records = skipped_records
        self.field_mapping = field_mapping
        self.missing_fields = missing_fields
        self.warnings = warnings

    @property
    def employee_ids(self) -> list[str]:
        return sorted(self.company.keys())

    @property
    def is_valid(self) -> bool:
        return len(self.missing_fields) == 0 and self.total_records > 0


def load_csv(
    path: str | Path,
    *,
    delimiter: str | None = None,
    strict: bool = False,
) -> CSVLoadResult:
    """加载 Concur Cognos 导出的 CSV 文件。

    Args:
        path: CSV 文件路径。
        delimiter: 分隔符（默认自动检测 , 或 \\t）。
        strict: 严格模式下缺失必需字段会抛异常。

    Returns:
        CSVLoadResult，company 格式与 MockCompanyGenerator 输出一致。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"CSV 文件不存在: {p}")

    text = _read_with_encoding(p)
    warnings: list[str] = []

    # 自动检测分隔符
    if delimiter is None:
        first_line = text.split("\n", 1)[0]
        if "\t" in first_line and "," not in first_line:
            delimiter = "\t"
        else:
            delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)

    if len(rows) < 2:
        raise ValueError("CSV 文件为空或只有表头")

    headers = rows[0]
    col_map = _build_column_map(headers)
    missing = _check_required(col_map, headers)

    if missing and strict:
        raise ValueError(f"CSV 缺少必需字段: {missing}")
    if missing:
        warnings.append(f"缺少字段（将使用默认值）: {missing}")

    # 解析数据行
    company: dict[str, list[dict]] = {}
    total = 0
    skipped = 0

    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # 跳过空行

        record = _parse_row(row, col_map, row_idx)
        if record is None:
            skipped += 1
            continue

        total += 1
        eid = record["employee_id"]
        company.setdefault(eid, []).append(record)

    # 按日期排序
    for eid in company:
        company[eid].sort(key=lambda r: r.get("date", ""))

    # 字段映射摘要
    field_mapping = {
        headers[idx]: internal for idx, internal in col_map.items()
    }

    logger.info(
        "Loaded %d records (%d skipped) for %d employees from %s",
        total, skipped, len(company), p.name,
    )

    return CSVLoadResult(
        company=company,
        total_records=total,
        skipped_records=skipped,
        field_mapping=field_mapping,
        missing_fields=missing,
        warnings=warnings,
    )


def load_csv_string(
    content: str,
    *,
    delimiter: str = ",",
) -> CSVLoadResult:
    """从字符串内容加载 CSV（用于测试或 API 上传）。"""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp_path = f.name

    try:
        return load_csv(tmp_path, delimiter=delimiter)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

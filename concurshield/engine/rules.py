"""确定性规则引擎 - 基于预定义规则检测发票异常

规则分两层：通用规则（所有国家）+ 国家专用规则（根据 merchant_country 自动选择）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable

from concurshield.models.schemas import ReceiptData, RuleCheckResult

# ── 货币-国家映射 ────────────────────────────────────────────────

_COUNTRY_CURRENCY: dict[str, str] = {
    "CN": "CNY",
    "AU": "AUD",
    "US": "USD",
    "GB": "GBP",
    "JP": "JPY",
    "EU": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "KR": "KRW",
    "HK": "HKD",
    "SG": "SGD",
    "CA": "CAD",
    "NZ": "NZD",
}

# ── 粗略汇率（→ USD），仅用于 AMOUNT_001 阈值判断 ────────────────

_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "CNY": 0.14,
    "AUD": 0.65,
    "GBP": 1.27,
    "EUR": 1.08,
    "JPY": 0.0067,
    "KRW": 0.00075,
    "HKD": 0.13,
    "SGD": 0.74,
    "CAD": 0.74,
    "NZD": 0.61,
}

# ── 国家规则注册表 ───────────────────────────────────────────────

RuleFunc = Callable[[ReceiptData], RuleCheckResult]

_country_rules: dict[str, list[RuleFunc]] = {}


def _register(country: str) -> Callable[[RuleFunc], RuleFunc]:
    """装饰器：将规则函数注册到指定国家。"""
    def decorator(fn: RuleFunc) -> RuleFunc:
        _country_rules.setdefault(country, []).append(fn)
        return fn
    return decorator


# ══════════════════════════════════════════════════════════════════
#  通用规则
# ══════════════════════════════════════════════════════════════════


def _math_001(receipt: ReceiptData) -> RuleCheckResult:
    """MATH_001: 行项加总校验 — sum(item.amount) ≈ subtotal"""
    rule_id, rule_name = "MATH_001", "行项加总校验"
    if not receipt.items or receipt.subtotal is None:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="无行项或无 subtotal，跳过校验",
        )
    item_sum = sum(item.amount for item in receipt.items)
    diff = abs(item_sum - receipt.subtotal)
    passed = diff <= 0.02
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="critical" if not passed else "info",
        detail=f"行项合计={item_sum:.2f}, subtotal={receipt.subtotal:.2f}, 差额={diff:.2f}",
    )


def _math_002(receipt: ReceiptData) -> RuleCheckResult:
    """MATH_002: 税额校验 — tax_amount ≈ subtotal * tax_rate"""
    rule_id, rule_name = "MATH_002", "税额校验"
    if receipt.tax_amount is None or receipt.tax_rate is None or receipt.subtotal is None:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="税额/税率/subtotal 缺失，跳过校验",
        )
    # tax_rate 可能是百分比（如 6）或小数（如 0.06），统一转为小数
    rate = receipt.tax_rate if receipt.tax_rate < 1 else receipt.tax_rate / 100
    expected = receipt.subtotal * rate
    diff = abs(receipt.tax_amount - expected)
    passed = diff <= 0.05
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="critical" if not passed else "info",
        detail=f"tax_amount={receipt.tax_amount:.2f}, expected={expected:.2f}, 差额={diff:.2f}",
    )


def _math_003(receipt: ReceiptData) -> RuleCheckResult:
    """MATH_003: 总额校验 — total ≈ subtotal + tax_amount"""
    rule_id, rule_name = "MATH_003", "总额校验"
    if receipt.subtotal is None or receipt.tax_amount is None:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="subtotal 或 tax_amount 缺失，跳过校验",
        )
    expected = receipt.subtotal + receipt.tax_amount
    diff = abs(receipt.total - expected)
    passed = diff <= 0.02
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="critical" if not passed else "info",
        detail=f"total={receipt.total:.2f}, subtotal+tax={expected:.2f}, 差额={diff:.2f}",
    )


def _math_004(receipt: ReceiptData) -> RuleCheckResult:
    """MATH_004: 货币与国家一致性"""
    rule_id, rule_name = "MATH_004", "货币与国家一致性"
    expected_currency = _COUNTRY_CURRENCY.get(receipt.merchant_country)
    if expected_currency is None:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail=f"国家 {receipt.merchant_country} 无预设货币映射，跳过",
        )
    passed = receipt.currency == expected_currency
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="warning" if not passed else "info",
        detail=f"国家={receipt.merchant_country}, 货币={receipt.currency}, 预期={expected_currency}",
    )


def _amount_001(receipt: ReceiptData) -> RuleCheckResult:
    """AMOUNT_001: 单笔金额异常 — 任何行项 > 500 USD 等价物"""
    rule_id, rule_name = "AMOUNT_001", "单笔金额异常"
    if not receipt.items:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="无行项，跳过校验",
        )
    rate = _TO_USD.get(receipt.currency, 1.0)
    threshold_local = 500.0 / rate if rate > 0 else 500.0
    flagged = [
        f"{item.description}={item.amount:.2f}"
        for item in receipt.items
        if item.amount > threshold_local
    ]
    passed = len(flagged) == 0
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="warning" if not passed else "info",
        detail=f"超过 500 USD 等价物的行项: {', '.join(flagged)}" if flagged else "所有行项金额正常",
    )


def _date_001(receipt: ReceiptData) -> RuleCheckResult:
    """DATE_001: 日期合理性 — 不能是未来，不能超过 90 天前"""
    rule_id, rule_name = "DATE_001", "日期合理性"
    try:
        dt = datetime.strptime(receipt.date, "%Y-%m-%d")
    except ValueError:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=False,
            severity="critical", detail=f"日期格式无效: {receipt.date}",
        )
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if dt > today:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=False,
            severity="critical", detail=f"日期 {receipt.date} 是未来日期",
        )
    if dt < today - timedelta(days=90):
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=False,
            severity="warning", detail=f"日期 {receipt.date} 超过 90 天前",
        )
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=True,
        severity="info", detail=f"日期 {receipt.date} 在合理范围内",
    )


# 通用规则列表（固定顺序）
_COMMON_RULES: list[RuleFunc] = [
    _math_001,
    _math_002,
    _math_003,
    _math_004,
    _amount_001,
    _date_001,
]


# ══════════════════════════════════════════════════════════════════
#  中国专用规则 (CN)
# ══════════════════════════════════════════════════════════════════

_CN_VALID_VAT_RATES = {0, 1, 3, 5, 6, 9, 13}


@_register("CN")
def _cn_tax_001(receipt: ReceiptData) -> RuleCheckResult:
    """CN_TAX_001: 增值税税率校验 — 必须是 0/1/3/5/6/9/13 之一"""
    rule_id, rule_name = "CN_TAX_001", "增值税税率校验"
    if receipt.tax_rate is None:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="无税率信息，跳过校验",
        )
    # tax_rate 可能是小数形式（如 0.13）或百分比形式（如 13）
    rate_pct = receipt.tax_rate if receipt.tax_rate >= 1 else receipt.tax_rate * 100
    rate_pct_int = round(rate_pct)
    passed = rate_pct_int in _CN_VALID_VAT_RATES
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="critical" if not passed else "info",
        detail=f"税率={receipt.tax_rate}（≈{rate_pct_int}%），有效值={sorted(_CN_VALID_VAT_RATES)}",
    )


@_register("CN")
def _cn_tax_002(receipt: ReceiptData) -> RuleCheckResult:
    """CN_TAX_002: 增值税税额验算（含税场景：tax_amount = total / (1+rate) * rate）"""
    rule_id, rule_name = "CN_TAX_002", "增值税税额验算"
    if receipt.tax_rate is None or receipt.tax_amount is None:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="税率或税额缺失，跳过校验",
        )
    rate = receipt.tax_rate if receipt.tax_rate < 1 else receipt.tax_rate / 100
    if rate == 0:
        passed = abs(receipt.tax_amount) <= 0.01
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=passed,
            severity="critical" if not passed else "info",
            detail=f"零税率，tax_amount 应为 0，实际={receipt.tax_amount:.2f}",
        )
    # 方式 1：不含税场景 tax_amount = subtotal * rate
    expected_excl = receipt.subtotal * rate if receipt.subtotal is not None else None
    # 方式 2：含税场景 tax_amount = total / (1 + rate) * rate
    expected_incl = receipt.total / (1 + rate) * rate
    tolerance = 0.05
    passed_excl = expected_excl is not None and abs(receipt.tax_amount - expected_excl) <= tolerance
    passed_incl = abs(receipt.tax_amount - expected_incl) <= tolerance
    passed = passed_excl or passed_incl
    detail_parts = [f"tax_amount={receipt.tax_amount:.2f}"]
    if expected_excl is not None:
        detail_parts.append(f"不含税预期={expected_excl:.2f}")
    detail_parts.append(f"含税预期={expected_incl:.2f}")
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="critical" if not passed else "info",
        detail=", ".join(detail_parts),
    )


# ══════════════════════════════════════════════════════════════════
#  澳洲专用规则 (AU)
# ══════════════════════════════════════════════════════════════════


@_register("AU")
def _au_gst_001(receipt: ReceiptData) -> RuleCheckResult:
    """AU_GST_001: GST 税率校验 — 必须是 0 或 10"""
    rule_id, rule_name = "AU_GST_001", "GST 税率校验"
    if receipt.tax_rate is None:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="无税率信息，跳过校验",
        )
    # tax_rate 可能是小数（0.1）或百分比（10）
    rate_pct = receipt.tax_rate if receipt.tax_rate >= 1 else receipt.tax_rate * 100
    rate_pct_int = round(rate_pct)
    passed = rate_pct_int in {0, 10}
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=passed,
        severity="critical" if not passed else "info",
        detail=f"税率={receipt.tax_rate}（≈{rate_pct_int}%），有效值=[0, 10]",
    )


@_register("AU")
def _au_abn_001(receipt: ReceiptData) -> RuleCheckResult:
    """AU_ABN_001: ABN 格式校验 — raw_text 中的 ABN 应为 11 位数字"""
    rule_id, rule_name = "AU_ABN_001", "ABN 格式校验"
    # 查找 raw_text 中所有 ABN 出现
    matches = re.findall(r"ABN[:\s]*(\d[\d\s]*\d)", receipt.raw_text, re.IGNORECASE)
    if not matches:
        return RuleCheckResult(
            rule_id=rule_id, rule_name=rule_name, passed=True,
            severity="info", detail="raw_text 中未发现 ABN",
        )
    for m in matches:
        digits = re.sub(r"\s", "", m)
        if len(digits) != 11:
            return RuleCheckResult(
                rule_id=rule_id, rule_name=rule_name, passed=False,
                severity="warning",
                detail=f"ABN 格式异常：'{digits}'（应为 11 位数字，实际 {len(digits)} 位）",
            )
    return RuleCheckResult(
        rule_id=rule_id, rule_name=rule_name, passed=True,
        severity="info", detail=f"ABN 格式正确（共 {len(matches)} 个）",
    )


# ══════════════════════════════════════════════════════════════════
#  公共 API
# ══════════════════════════════════════════════════════════════════


def run_rules(receipt: ReceiptData) -> list[RuleCheckResult]:
    """对 OCR 结果执行所有规则检查（通用规则 + 国家专用规则）。

    规则执行顺序固定：先通用规则，再国家专用规则。

    Args:
        receipt: OCR 结构化数据。

    Returns:
        所有规则的检查结果列表，按执行顺序排列。
    """
    results: list[RuleCheckResult] = []

    # 通用规则
    for rule_fn in _COMMON_RULES:
        results.append(rule_fn(receipt))

    # 国家专用规则
    country_fns = _country_rules.get(receipt.merchant_country, [])
    for rule_fn in country_fns:
        results.append(rule_fn(receipt))

    return results


def has_anomaly(results: list[RuleCheckResult]) -> bool:
    """检查规则结果中是否存在 critical 级别的失败。

    Args:
        results: run_rules 返回的结果列表。

    Returns:
        True 表示存在 critical 失败，应触发 Agent 调查。
    """
    return any(
        not r.passed and r.severity == "critical"
        for r in results
    )

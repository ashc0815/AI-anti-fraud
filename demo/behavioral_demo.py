"""员工行为画像分析 Demo

生成模拟报销记录，调用 LLM 分析跨时间行为模式，
识别地理异常、金额异常、商户集中度异常。
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta

import openai

from concurshield.config import settings

logger = logging.getLogger(__name__)

# ── Mock 数据生成 ──────────────────────────────────────────────────


# 正常模式参数
_NORMAL_CITIES = ["上海"]
_NORMAL_MERCHANTS = {
    "餐饮": ["海底捞（南京西路店）", "星巴克（陆家嘴店）", "麦当劳（人民广场店）", "全家便利店"],
    "交通": ["上海出租（强生）", "滴滴出行", "上海地铁"],
    "住宿": ["如家酒店（浦东店）", "全季酒店（虹桥店）"],
    "办公": ["得力办公旗舰店", "京东企业购"],
}
_NORMAL_AMOUNTS = {
    "餐饮": (30, 180),
    "交通": (15, 120),
    "住宿": (250, 450),
    "办公": (20, 200),
}


def generate_mock_expenses(employee_id: str) -> list[dict]:
    """生成 30 条模拟报销记录：25 条正常 + 5 条异常。

    异常包括：
      a) 3 条声称在广州消费（该员工从未去过广州）
      b) 1 条金额是同品类平均消费的 4 倍
      c) 1 条使用了只有此员工使用的「幽灵商户」
    """
    random.seed(42)  # 可复现
    records: list[dict] = []
    base_date = datetime(2025, 1, 6)  # 从 2025-01-06 (周一) 开始

    categories = list(_NORMAL_MERCHANTS.keys())

    # ── 25 条正常记录 ──────────────────────────────────────────
    for i in range(25):
        day_offset = (i // 2) * 1 + random.randint(0, 2)  # 大致每天 1~2 笔
        date = base_date + timedelta(days=day_offset)
        cat = random.choice(categories)
        lo, hi = _NORMAL_AMOUNTS[cat]
        amount = round(random.uniform(lo, hi), 2)
        records.append({
            "id": i + 1,
            "employee_id": employee_id,
            "date": date.strftime("%Y-%m-%d"),
            "city": random.choice(_NORMAL_CITIES),
            "merchant": random.choice(_NORMAL_MERCHANTS[cat]),
            "category": cat,
            "amount": amount,
            "currency": "CNY",
            "anomaly_label": None,  # 正常
        })

    # ── 异常 a：3 条广州消费（地理异常）───────────────────────
    for j in range(3):
        date = base_date + timedelta(days=10 + j)
        cat = "餐饮"
        records.append({
            "id": 26 + j,
            "employee_id": employee_id,
            "date": date.strftime("%Y-%m-%d"),
            "city": "广州",
            "merchant": f"广州酒家（天河店）" if j < 2 else "白天鹅宾馆餐厅",
            "category": cat,
            "amount": round(random.uniform(80, 200), 2),
            "currency": "CNY",
            "anomaly_label": "geo_anomaly",
        })

    # ── 异常 b：1 条 4 倍金额（金额异常）──────────────────────
    cat = "餐饮"
    avg = sum(_NORMAL_AMOUNTS[cat]) / 2  # (30+180)/2 = 105
    records.append({
        "id": 29,
        "employee_id": employee_id,
        "date": (base_date + timedelta(days=15)).strftime("%Y-%m-%d"),
        "city": "上海",
        "merchant": "海底捞（南京西路店）",
        "category": cat,
        "amount": round(avg * 4, 2),  # ~420
        "currency": "CNY",
        "anomaly_label": "amount_anomaly",
    })

    # ── 异常 c：1 条幽灵商户 ──────────────────────────────────
    records.append({
        "id": 30,
        "employee_id": employee_id,
        "date": (base_date + timedelta(days=18)).strftime("%Y-%m-%d"),
        "city": "上海",
        "merchant": "鑫源贸易有限公司",  # 不在已知商户列表中
        "category": "办公",
        "amount": 380.00,
        "currency": "CNY",
        "anomaly_label": "ghost_merchant",
    })

    # 按日期排序
    records.sort(key=lambda r: r["date"])
    return records


# ── 行为分析 ──────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """\
你是一个企业费用审计专家。下面是员工 {employee_id} 最近 30 条报销记录（JSON 格式）。

请完成以下分析任务：

1. **地理异常检测**：该员工的主要出差城市是哪里？是否有与常驻城市不一致的消费？
2. **金额异常检测**：按品类计算平均消费金额，找出明显偏离（>= 3 倍平均值）的记录。
3. **商户集中度异常**：是否有只出现过一次的商户？是否有只有该员工使用的商户？
4. **时间模式分析**：消费频率是否合理？是否有异常集中的消费时段？

请严格按以下 JSON 格式输出：
{{
  "employee_summary": {{
    "primary_city": "<主要出差城市>",
    "total_records": <记录总数>,
    "total_amount": <总金额>,
    "date_range": "<起止日期>"
  }},
  "findings": [
    {{
      "type": "geo_anomaly | amount_anomaly | merchant_anomaly | time_anomaly",
      "severity": "high | medium | low",
      "description": "<描述>",
      "affected_records": [<record id 列表>],
      "recommendation": "<建议>"
    }}
  ],
  "overall_risk": "high | medium | low",
  "reasoning_chain": "<完整推理过程>"
}}

员工报销记录：
{expenses_json}
"""


def analyze_behavior(expenses: list[dict], employee_id: str = "EMP-001") -> dict:
    """调用 LLM 分析员工行为模式。

    Args:
        expenses: generate_mock_expenses 生成的报销记录列表。
        employee_id: 员工 ID。

    Returns:
        包含 findings、overall_risk、reasoning_chain 的分析结果字典。
    """
    # 移除 anomaly_label（不能泄露给 LLM）
    clean_expenses = [
        {k: v for k, v in r.items() if k != "anomaly_label"}
        for r in expenses
    ]

    prompt = _ANALYSIS_PROMPT.format(
        employee_id=employee_id,
        expenses_json=json.dumps(clean_expenses, ensure_ascii=False, indent=2),
    )

    client_kwargs = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        client_kwargs["base_url"] = settings.OPENAI_BASE_URL

    client = openai.OpenAI(**client_kwargs)

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except openai.APIConnectionError:
        logger.warning("API connection failed, using fallback analysis")
        return _fallback_analysis(expenses, employee_id)
    except Exception as e:
        logger.error(f"Behavior analysis failed: {e}")
        return _fallback_analysis(expenses, employee_id)


def _fallback_analysis(expenses: list[dict], employee_id: str) -> dict:
    """API 不可用时的本地规则分析（确保 Demo 始终可运行）。"""
    # 统计
    cities = {}
    cat_amounts: dict[str, list[float]] = {}
    merchant_counts: dict[str, int] = {}

    for r in expenses:
        cities[r["city"]] = cities.get(r["city"], 0) + 1
        cat_amounts.setdefault(r["category"], []).append(r["amount"])
        merchant_counts[r["merchant"]] = merchant_counts.get(r["merchant"], 0) + 1

    primary_city = max(cities, key=cities.get)
    total_amount = round(sum(r["amount"] for r in expenses), 2)
    dates = sorted(r["date"] for r in expenses)

    findings = []

    # 地理异常
    for city, count in cities.items():
        if city != primary_city:
            affected = [r["id"] for r in expenses if r["city"] == city]
            findings.append({
                "type": "geo_anomaly",
                "severity": "high",
                "description": (
                    f"员工常驻 {primary_city}，但有 {count} 条消费发生在 {city}，"
                    f"且无该城市的出差审批记录。"
                ),
                "affected_records": affected,
                "recommendation": "核实是否有 {city} 出差审批；要求提供行程证明。".format(city=city),
            })

    # 金额异常
    for cat, amounts in cat_amounts.items():
        avg = sum(amounts) / len(amounts)
        for r in expenses:
            if r["category"] == cat and r["amount"] >= avg * 3:
                findings.append({
                    "type": "amount_anomaly",
                    "severity": "high",
                    "description": (
                        f"记录 #{r['id']}（{r['merchant']}）金额 {r['amount']} CNY，"
                        f"是该员工 {cat} 品类平均消费 {avg:.0f} CNY 的 "
                        f"{r['amount']/avg:.1f} 倍。"
                    ),
                    "affected_records": [r["id"]],
                    "recommendation": "要求提供消费明细和参与人数说明。",
                })

    # 商户异常
    single_use = [m for m, c in merchant_counts.items() if c == 1]
    unknown_merchants = [
        m for m in single_use
        if not any(m in merchants for merchants in _NORMAL_MERCHANTS.values())
    ]
    for m in unknown_merchants:
        affected = [r["id"] for r in expenses if r["merchant"] == m]
        findings.append({
            "type": "merchant_anomaly",
            "severity": "medium",
            "description": (
                f"商户「{m}」仅出现 1 次且不在公司已知合作商户名单中，"
                f"可能为虚假商户。"
            ),
            "affected_records": affected,
            "recommendation": "核实商户真实性，检查工商注册信息。",
        })

    overall_risk = "high" if any(f["severity"] == "high" for f in findings) else "medium"

    return {
        "employee_summary": {
            "primary_city": primary_city,
            "total_records": len(expenses),
            "total_amount": total_amount,
            "date_range": f"{dates[0]} ~ {dates[-1]}",
        },
        "findings": findings,
        "overall_risk": overall_risk,
        "reasoning_chain": (
            f"分析员工 {employee_id} 的 {len(expenses)} 条报销记录。"
            f"主要出差城市为 {primary_city}（{cities[primary_city]} 条）。"
            f"发现 {len(findings)} 条异常：包括地理异常（非常驻城市消费）、"
            f"金额异常（显著高于品类均值）和商户异常（未知一次性商户）。"
            f"综合风险评级：{overall_risk}。"
        ),
        "_analysis_mode": "local_fallback",
    }

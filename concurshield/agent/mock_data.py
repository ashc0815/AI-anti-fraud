"""Mock Company Data Generator — 20 人公司 6 个月报销数据。

16 个正常员工 + 4 个欺诈场景：
  EMP_PHANTOM    — 幽灵供应商（独占商户 City Express Transport 等）
  EMP_FABRICATED — 虚构出差（新城市无 booking 无交通费）
  EMP_THRESHOLD  — 阈值试探（6/8 笔在 ¥450-499）
  EMP_PERSONAL   — 私人消费（周末三亚，comment 声称拜访客户但 contradiction）
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# 真实中国格式商户名
# ═══════════════════════════════════════════════════════════════════════════

MERCHANTS: dict[str, list[str]] = {
    "餐饮": [
        "海底捞火锅（南京西路店）",
        "外婆家（来福士店）",
        "星巴克（陆家嘴中心店）",
        "麦当劳（人民广场店）",
        "全家便利店（浦东大道店）",
        "西贝莜面村（环球港店）",
        "小南国（淮海路店）",
        "肯德基（徐家汇店）",
        "大董烤鸭（国贸店）",
        "鼎泰丰（恒隆广场店）",
    ],
    "交通": [
        "上海强生出租汽车有限公司",
        "滴滴出行科技有限公司",
        "上海地铁运营有限公司",
        "首汽约车（北京）",
        "曹操出行（杭州）",
        "高德打车",
    ],
    "住宿": [
        "如家酒店（浦东国际机场店）",
        "全季酒店（虹桥商务区店）",
        "汉庭酒店（中关村店）",
        "亚朵酒店（西湖文化广场店）",
        "锦江之星（南京路店）",
        "桔子水晶酒店（三里屯店）",
    ],
    "办公": [
        "得力集团有限公司（企业直销）",
        "京东企业购",
        "齐心集团股份有限公司",
        "晨光文具（企业采购）",
        "史泰博办公用品（中国）",
    ],
}

CITIES_NORMAL = ["上海", "北京", "杭州"]

AMOUNT_RANGES: dict[str, tuple[float, float]] = {
    "餐饮": (25, 200),
    "交通": (12, 150),
    "住宿": (220, 480),
    "办公": (15, 250),
}

CATEGORIES = list(AMOUNT_RANGES.keys())

# 幽灵供应商专用商户
PHANTOM_MERCHANTS = [
    "城捷运输服务有限公司",          # City Express Transport
    "恒通达物流有限公司",
    "鑫源商贸发展有限公司",
]

# 审批人
APPROVERS = ["MGR-001", "MGR-002", "MGR-003", "MGR-004"]


# ═══════════════════════════════════════════════════════════════════════════
# ID 常量
# ═══════════════════════════════════════════════════════════════════════════

EMP_PHANTOM = "EMP_PHANTOM"
EMP_FABRICATED = "EMP_FABRICATED"
EMP_THRESHOLD = "EMP_THRESHOLD"
EMP_PERSONAL = "EMP_PERSONAL"

FRAUD_IDS = {EMP_PHANTOM, EMP_FABRICATED, EMP_THRESHOLD, EMP_PERSONAL}


# ═══════════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════════


def _next_id(counter: list[int]) -> int:
    counter[0] += 1
    return counter[0]


def _gen_normal(
    rng: random.Random,
    employee_id: str,
    approver_id: str,
    base_date: datetime,
    months: int,
    id_counter: list[int],
) -> list[dict]:
    """生成一个正常员工的报销记录。"""
    total_days = months * 30
    n = rng.randint(months * 4, months * 6)
    records: list[dict] = []

    for _ in range(n):
        day_offset = rng.randint(0, total_days - 1)
        dt = base_date + timedelta(days=day_offset)
        # 避免周末（正常员工极少周末消费）
        while dt.weekday() >= 5:
            dt -= timedelta(days=1)
        cat = rng.choice(CATEGORIES)
        lo, hi = AMOUNT_RANGES[cat]
        records.append({
            "id": _next_id(id_counter),
            "employee_id": employee_id,
            "approver_id": approver_id,
            "date": dt.strftime("%Y-%m-%d"),
            "city": rng.choice(CITIES_NORMAL),
            "merchant": rng.choice(MERCHANTS[cat]),
            "category": cat,
            "amount": round(rng.uniform(lo, hi), 2),
            "currency": "CNY",
            "comment": "",
        })

    records.sort(key=lambda r: r["date"])
    return records


# ═══════════════════════════════════════════════════════════════════════════
# 4 种欺诈场景
# ═══════════════════════════════════════════════════════════════════════════


def _gen_phantom(
    rng: random.Random,
    base_date: datetime,
    months: int,
    id_counter: list[int],
) -> list[dict]:
    """EMP_PHANTOM — 幽灵供应商。

    正常消费 + 每月 2-3 笔给独占商户 城捷运输/恒通达/鑫源商贸，
    金额 ¥300-490，类别"交通"或"办公"，只有该员工使用。
    """
    approver = "MGR-001"
    records = _gen_normal(rng, EMP_PHANTOM, approver, base_date, months, id_counter)

    # 注入幽灵供应商交易
    for m in range(months):
        n_phantom = rng.randint(2, 3)
        for _ in range(n_phantom):
            day_offset = m * 30 + rng.randint(1, 28)
            dt = base_date + timedelta(days=day_offset)
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            merchant = rng.choice(PHANTOM_MERCHANTS)
            cat = rng.choice(["交通", "办公"])
            records.append({
                "id": _next_id(id_counter),
                "employee_id": EMP_PHANTOM,
                "approver_id": approver,
                "date": dt.strftime("%Y-%m-%d"),
                "city": "上海",
                "merchant": merchant,
                "category": cat,
                "amount": round(rng.uniform(300, 490), 2),
                "currency": "CNY",
                "comment": "",
            })

    records.sort(key=lambda r: r["date"])
    return records


def _gen_fabricated(
    rng: random.Random,
    base_date: datetime,
    months: int,
    id_counter: list[int],
) -> list[dict]:
    """EMP_FABRICATED — 虚构出差。

    前 4 个月正常（上海/北京），后 2 个月突然出现成都/重庆消费，
    但无任何交通费、无出差预订记录。餐饮金额偏高（¥400-800）。
    """
    approver = "MGR-002"
    records = _gen_normal(rng, EMP_FABRICATED, approver, base_date, months, id_counter)

    # 后 2 个月注入虚构出差
    cutoff = base_date + timedelta(days=(months - 2) * 30)
    fabricated_cities = ["成都", "重庆"]
    fabricated_merchants = [
        "蜀大侠火锅（春熙路店）",
        "陈麻婆豆腐（总府路店）",
        "重庆十八梯老火锅（解放碑店）",
        "巴蜀大将火锅（洪崖洞店）",
    ]

    for m in range(2):
        n_fab = rng.randint(4, 6)
        for _ in range(n_fab):
            day_offset = (months - 2 + m) * 30 + rng.randint(1, 28)
            dt = base_date + timedelta(days=day_offset)
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            records.append({
                "id": _next_id(id_counter),
                "employee_id": EMP_FABRICATED,
                "approver_id": approver,
                "date": dt.strftime("%Y-%m-%d"),
                "city": rng.choice(fabricated_cities),
                "merchant": rng.choice(fabricated_merchants),
                "category": "餐饮",
                "amount": round(rng.uniform(400, 800), 2),
                "currency": "CNY",
                "comment": "出差客户拜访" if rng.random() < 0.3 else "",
                # 关键：无对应的交通费和住宿费
            })

    records.sort(key=lambda r: r["date"])
    return records


def _gen_threshold(
    rng: random.Random,
    base_date: datetime,
    months: int,
    id_counter: list[int],
) -> list[dict]:
    """EMP_THRESHOLD — 阈值试探。

    正常消费 + 每月 1-2 笔住宿恰好在 ¥450-499（阈值 ¥500 以下免审批）。
    6 个月共约 8 笔中 6 笔命中阈值区间。
    """
    approver = "MGR-003"
    records = _gen_normal(rng, EMP_THRESHOLD, approver, base_date, months, id_counter)

    # 注入阈值试探交易
    threshold_count = 0
    for m in range(months):
        n_thresh = rng.randint(1, 2)
        for _ in range(n_thresh):
            if threshold_count >= 8:
                break
            day_offset = m * 30 + rng.randint(1, 28)
            dt = base_date + timedelta(days=day_offset)
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)

            # 6/8 在 ¥450-499，2/8 正常
            if threshold_count < 6:
                amount = round(rng.uniform(450, 499), 2)
            else:
                amount = round(rng.uniform(280, 420), 2)
            threshold_count += 1

            records.append({
                "id": _next_id(id_counter),
                "employee_id": EMP_THRESHOLD,
                "approver_id": approver,
                "date": dt.strftime("%Y-%m-%d"),
                "city": rng.choice(CITIES_NORMAL),
                "merchant": rng.choice(MERCHANTS["住宿"]),
                "category": "住宿",
                "amount": amount,
                "currency": "CNY",
                "comment": "",
            })

    records.sort(key=lambda r: r["date"])
    return records


def _gen_personal(
    rng: random.Random,
    base_date: datetime,
    months: int,
    id_counter: list[int],
) -> list[dict]:
    """EMP_PERSONAL — 私人消费报公账。

    正常工作日消费 + 每月 1-2 笔周末三亚消费（餐饮/住宿），
    comment 声称"拜访客户"但 contradiction_detected=True（周末+旅游城市）。
    """
    approver = "MGR-004"
    records = _gen_normal(rng, EMP_PERSONAL, approver, base_date, months, id_counter)

    sanya_merchants_dining = [
        "亚龙湾百花谷餐厅",
        "海棠湾免税城美食广场",
        "三亚海鲜第一市场（春园店）",
        "椰梦长廊椰子鸡（大东海店）",
    ]
    sanya_merchants_hotel = [
        "三亚亚特兰蒂斯酒店",
        "三亚海棠湾万达希尔顿酒店",
        "三亚半山半岛洲际度假酒店",
    ]

    for m in range(months):
        n_personal = rng.randint(1, 2)
        for _ in range(n_personal):
            # 强制放到周末
            day_offset = m * 30 + rng.randint(5, 25)
            dt = base_date + timedelta(days=day_offset)
            # 挪到最近的周六
            days_to_sat = (5 - dt.weekday()) % 7
            dt = dt + timedelta(days=days_to_sat)
            # 周六或周日
            if rng.random() < 0.5:
                dt += timedelta(days=1)  # 周日

            cat = rng.choice(["餐饮", "住宿"])
            if cat == "餐饮":
                merchant = rng.choice(sanya_merchants_dining)
                amount = round(rng.uniform(200, 600), 2)
            else:
                merchant = rng.choice(sanya_merchants_hotel)
                amount = round(rng.uniform(500, 1200), 2)

            records.append({
                "id": _next_id(id_counter),
                "employee_id": EMP_PERSONAL,
                "approver_id": approver,
                "date": dt.strftime("%Y-%m-%d"),
                "city": "三亚",
                "merchant": merchant,
                "category": cat,
                "amount": amount,
                "currency": "CNY",
                "comment": rng.choice([
                    "周末拜访三亚客户张总",
                    "拜访海南分公司客户",
                    "与三亚合作方李经理晚餐",
                ]),
                "_weekend": True,
                "_contradiction": True,
            })

    records.sort(key=lambda r: r["date"])
    return records


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════


def generate_company(
    num_normal: int = 16,
    num_approvers: int = 4,
    months: int = 6,
    seed: int = 2025,
) -> dict[str, list[dict]]:
    """生成 20 人公司 6 个月数据。

    Returns:
        {employee_id: [expense_records, ...], ...}
        共 20 个员工：16 正常 + 4 欺诈。
    """
    rng = random.Random(seed)
    base_date = datetime(2024, 10, 1)
    approvers = APPROVERS[:num_approvers]
    id_counter = [0]

    company: dict[str, list[dict]] = {}

    # ── 16 个正常员工 ─────────────────────────────────────────────
    for idx in range(1, num_normal + 1):
        eid = f"EMP-{idx:03d}"
        aid = approvers[(idx - 1) % num_approvers]
        company[eid] = _gen_normal(rng, eid, aid, base_date, months, id_counter)

    # ── 4 个欺诈员工 ─────────────────────────────────────────────
    company[EMP_PHANTOM] = _gen_phantom(rng, base_date, months, id_counter)
    company[EMP_FABRICATED] = _gen_fabricated(rng, base_date, months, id_counter)
    company[EMP_THRESHOLD] = _gen_threshold(rng, base_date, months, id_counter)
    company[EMP_PERSONAL] = _gen_personal(rng, base_date, months, id_counter)

    return company


def get_fraud_labels() -> dict[str, str]:
    """返回欺诈员工 ID → 欺诈类型的映射（用于评估）。"""
    return {
        EMP_PHANTOM: "幽灵供应商 — 独占商户高频交易",
        EMP_FABRICATED: "虚构出差 — 新城市无交通费无预订",
        EMP_THRESHOLD: "阈值试探 — 金额集中在审批阈值下方",
        EMP_PERSONAL: "私人消费 — 周末旅游城市声称业务目的",
    }


def summarize_company(company: dict[str, list[dict]]) -> dict[str, Any]:
    """输出公司数据摘要。"""
    total_records = sum(len(v) for v in company.values())
    total_amount = sum(r["amount"] for exps in company.values() for r in exps)
    fraud_records = sum(len(company[fid]) for fid in FRAUD_IDS if fid in company)
    return {
        "total_employees": len(company),
        "normal_employees": len(company) - len(FRAUD_IDS),
        "fraud_employees": len(FRAUD_IDS),
        "total_records": total_records,
        "total_amount": round(total_amount, 2),
        "fraud_records": fraud_records,
        "fraud_ids": list(FRAUD_IDS),
    }

"""Employee Risk Scorer — 对每个员工计算风险评分，决定交易处理深度。

五个子维度（各 0-20 分），总分 0-100：
  A. 消费偏离度  B. 同组偏离度  C. 供应商集中度风险
  D. 模式稳定性  E. 时间模式异常

分级：
  0-30  normal   → 只跑 Layer 1 规则引擎
  31-60 elevated → Layer 1 + 行为信号检查
  61-100 high    → Layer 1 + 启动 Agent 调查
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from concurshield.agent.tools import ToolRegistry


# ═══════════════════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════════════════


class RiskScore(BaseModel):
    employee_id: str
    total_score: int = Field(ge=0, le=100)
    classification: str  # "normal" / "elevated" / "high"
    dimension_scores: dict  # {A: 12, B: 8, C: 16, D: 5, E: 10}
    dimension_details: dict  # 每个维度的具体计算过程
    top_risk_factors: list[str]  # 排名前 3 的风险因素描述


# ═══════════════════════════════════════════════════════════════════════════
# Mock data generator
# ═══════════════════════════════════════════════════════════════════════════

_CATEGORIES = ["餐饮", "交通", "住宿", "办公"]
_NORMAL_CITIES = ["上海", "北京", "杭州"]
_NORMAL_MERCHANTS: dict[str, list[str]] = {
    "餐饮": ["海底捞（南京西路店）", "星巴克（陆家嘴店）", "麦当劳（人民广场店）", "全家便利店"],
    "交通": ["上海出租（强生）", "滴滴出行", "上海地铁"],
    "住宿": ["如家酒店（浦东店）", "全季酒店（虹桥店）"],
    "办公": ["得力办公旗舰店", "京东企业购"],
}
_AMOUNT_RANGES: dict[str, tuple[float, float]] = {
    "餐饮": (30, 180),
    "交通": (15, 120),
    "住宿": (250, 450),
    "办公": (20, 200),
}


def _gen_normal_expenses(
    rng: random.Random,
    employee_id: str,
    approver_id: str,
    base_date: datetime,
    months: int,
) -> list[dict]:
    """生成正常员工的报销记录。"""
    records: list[str | dict] = []
    total_days = months * 30
    num_records = rng.randint(months * 4, months * 6)

    for i in range(num_records):
        day_offset = rng.randint(0, total_days - 1)
        date = base_date + timedelta(days=day_offset)
        cat = rng.choice(_CATEGORIES)
        lo, hi = _AMOUNT_RANGES[cat]
        amount = round(rng.uniform(lo, hi), 2)
        records.append({
            "id": i + 1,
            "employee_id": employee_id,
            "approver_id": approver_id,
            "date": date.strftime("%Y-%m-%d"),
            "city": rng.choice(_NORMAL_CITIES[:2]),
            "merchant": rng.choice(_NORMAL_MERCHANTS[cat]),
            "category": cat,
            "amount": amount,
            "currency": "CNY",
        })

    records.sort(key=lambda r: r["date"])
    return records


class MockEmployeeData:
    """生成 MVP 演示用的模拟公司数据。"""

    def generate_company(
        self,
        num_employees: int = 20,
        num_approvers: int = 4,
        months: int = 6,
    ) -> dict[str, list[dict]]:
        """生成一个模拟公司的完整数据。

        - 16 个正常员工
        - EMP-017: 金额飙升 + 新城市（疑似虚构出差）
        - EMP-018: 独占商户 + 高频使用（疑似幽灵供应商）
        - EMP-019: 阈值试探 + 费用类型突变（疑似有意识虚报）
        - EMP-020: 周末消费 + 无出差记录（疑似私人消费报公账）
        """
        rng = random.Random(2025)
        base_date = datetime(2024, 10, 1)
        approvers = [f"MGR-{i:03d}" for i in range(1, num_approvers + 1)]

        company: dict[str, list[dict]] = {}

        # ── 16 个正常员工 ─────────────────────────────────────────
        for idx in range(1, num_employees - 3):
            eid = f"EMP-{idx:03d}"
            aid = approvers[(idx - 1) % num_approvers]
            company[eid] = _gen_normal_expenses(rng, eid, aid, base_date, months)

        # ── EMP-017: 金额飙升 + 新城市 ───────────────────────────
        eid = f"EMP-{num_employees - 3:03d}"
        records = _gen_normal_expenses(rng, eid, approvers[0], base_date, months)
        # 最近 2 个月注入异常：金额 3-5 倍、出现新城市
        recent_cutoff = base_date + timedelta(days=(months - 2) * 30)
        for r in records:
            if datetime.strptime(r["date"], "%Y-%m-%d") >= recent_cutoff:
                r["amount"] = round(r["amount"] * rng.uniform(3.0, 5.0), 2)
                if rng.random() < 0.4:
                    r["city"] = "成都"
        company[eid] = records

        # ── EMP-018: 独占商户 + 高频 ─────────────────────────────
        eid = f"EMP-{num_employees - 2:03d}"
        records = _gen_normal_expenses(rng, eid, approvers[1], base_date, months)
        ghost_merchants = ["鑫源贸易有限公司", "瑞丰商贸中心", "恒达信息咨询"]
        for i, r in enumerate(records):
            if i % 3 == 0:
                r["merchant"] = rng.choice(ghost_merchants)
                r["category"] = "办公"
                r["amount"] = round(rng.uniform(300, 490), 2)
        company[eid] = records

        # ── EMP-019: 阈值试探 + 类型突变 ─────────────────────────
        eid = f"EMP-{num_employees - 1:03d}"
        records = _gen_normal_expenses(rng, eid, approvers[2], base_date, months)
        for r in records:
            if datetime.strptime(r["date"], "%Y-%m-%d") >= recent_cutoff:
                # 金额集中在阈值 (200 CNY) 的 90-99%
                r["category"] = "餐饮"
                r["amount"] = round(rng.uniform(180, 199), 2)
        company[eid] = records

        # ── EMP-020: 周末消费 + 无出差记录 ────────────────────────
        eid = f"EMP-{num_employees:03d}"
        records = _gen_normal_expenses(rng, eid, approvers[3], base_date, months)
        weekend_inject = 0
        for r in records:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            if weekend_inject < 10:
                # 强制放到周末
                days_to_sat = (5 - dt.weekday()) % 7
                new_dt = dt + timedelta(days=days_to_sat)
                r["date"] = new_dt.strftime("%Y-%m-%d")
                weekend_inject += 1
        company[eid] = records

        return company


# ═══════════════════════════════════════════════════════════════════════════
# Scorer
# ═══════════════════════════════════════════════════════════════════════════


def _clamp(value: float, lo: float = 0.0, hi: float = 20.0) -> int:
    return int(max(lo, min(hi, value)))


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """计算两个分布向量的余弦相似度。"""
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    mag_a = math.sqrt(sum(v ** 2 for v in a.values())) or 1e-9
    mag_b = math.sqrt(sum(v ** 2 for v in b.values())) or 1e-9
    return dot / (mag_a * mag_b)


class EmployeeRiskScorer:
    """计算每个员工的风险评分（0-100），决定交易处理深度。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    # ── A. 消费偏离度 (0-20) ──────────────────────────────────────

    def _score_expense_deviation(
        self, expenses: list[dict],
    ) -> tuple[int, dict]:
        """CV = std/mean，最近 2 个月权重 ×2。"""
        if len(expenses) < 3:
            return 0, {"cv": 0, "reason": "记录不足"}

        dates = sorted(expenses, key=lambda r: r["date"])
        all_dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in dates]
        cutoff = max(all_dates) - timedelta(days=60)

        recent = [r["amount"] for r in dates if datetime.strptime(r["date"], "%Y-%m-%d") >= cutoff]
        older = [r["amount"] for r in dates if datetime.strptime(r["date"], "%Y-%m-%d") < cutoff]

        # 加权序列：最近 2 个月权重 ×2
        weighted = older + recent * 2
        if not weighted or len(weighted) < 2:
            return 0, {"cv": 0, "reason": "加权序列不足"}

        mean_val = statistics.mean(weighted)
        std_val = statistics.stdev(weighted)
        cv = std_val / mean_val if mean_val > 0 else 0

        if cv > 0.5:
            score = _clamp(16 + (cv - 0.5) * 8)  # 0.5→16, 1.0→20
        elif cv > 0.3:
            score = _clamp(8 + (cv - 0.3) / 0.2 * 7)  # 0.3→8, 0.5→15
        else:
            score = _clamp(cv / 0.3 * 7)  # 0→0, 0.3→7

        detail = {
            "cv": round(cv, 4),
            "weighted_mean": round(mean_val, 2),
            "weighted_std": round(std_val, 2),
            "recent_count": len(recent),
            "older_count": len(older),
        }
        return score, detail

    # ── B. 同组偏离度 (0-20) ──────────────────────────────────────

    def _score_peer_deviation(
        self, employee_avg: float, company: dict[str, list[dict]], approver_id: str,
    ) -> tuple[int, dict]:
        """该员工月均 / 同审批人下中位数。"""
        peer_avgs: list[float] = []
        for eid, exps in company.items():
            if not exps or exps[0].get("approver_id") != approver_id:
                continue
            total = sum(r["amount"] for r in exps)
            dates = sorted(r["date"] for r in exps)
            first = datetime.strptime(dates[0], "%Y-%m-%d")
            last = datetime.strptime(dates[-1], "%Y-%m-%d")
            m = max((last - first).days / 30.0, 1)
            peer_avgs.append(total / m)

        if not peer_avgs:
            return 0, {"ratio": 0, "reason": "无同组数据"}

        median_val = statistics.median(peer_avgs)
        ratio = employee_avg / median_val if median_val > 0 else 0

        if ratio > 2.5:
            score = _clamp(16 + (ratio - 2.5) * 4)
        elif ratio > 1.5:
            score = _clamp(8 + (ratio - 1.5) / 1.0 * 7)
        else:
            score = _clamp(ratio / 1.5 * 7)

        detail = {
            "employee_monthly_avg": round(employee_avg, 2),
            "peer_median": round(median_val, 2),
            "ratio": round(ratio, 4),
            "peer_count": len(peer_avgs),
        }
        return score, detail

    # ── C. 供应商集中度风险 (0-20) ────────────────────────────────

    def _score_merchant_concentration(
        self, expenses: list[dict], company: dict[str, list[dict]], employee_id: str,
    ) -> tuple[int, dict]:
        """独占商户数 / 该员工使用的总商户数。"""
        emp_merchants = set(r["merchant"] for r in expenses)
        if not emp_merchants:
            return 0, {"exclusive_ratio": 0, "reason": "无商户数据"}

        # 全公司所有商户 → 使用人数
        company_merchant_users: dict[str, set[str]] = {}
        for eid, exps in company.items():
            for r in exps:
                company_merchant_users.setdefault(r["merchant"], set()).add(eid)

        exclusive = [
            m for m in emp_merchants
            if len(company_merchant_users.get(m, set())) == 1
        ]
        ratio = len(exclusive) / len(emp_merchants)

        if ratio > 0.3:
            score = _clamp(16 + (ratio - 0.3) / 0.7 * 4)
        elif ratio > 0.15:
            score = _clamp(8 + (ratio - 0.15) / 0.15 * 7)
        else:
            score = _clamp(ratio / 0.15 * 7)

        detail = {
            "total_merchants": len(emp_merchants),
            "exclusive_merchants": len(exclusive),
            "exclusive_names": exclusive[:5],
            "exclusive_ratio": round(ratio, 4),
        }
        return score, detail

    # ── D. 模式稳定性 (0-20) ──────────────────────────────────────

    def _score_pattern_stability(
        self, expenses: list[dict],
    ) -> tuple[int, dict]:
        """最近 1 个月 vs 前 5 个月的费用类型分布余弦相似度。"""
        if len(expenses) < 5:
            return 0, {"cosine_sim": 1.0, "reason": "记录不足"}

        dates = sorted(expenses, key=lambda r: r["date"])
        all_dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in dates]
        cutoff = max(all_dates) - timedelta(days=30)

        recent_dist: dict[str, float] = {}
        older_dist: dict[str, float] = {}
        for r in dates:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            target = recent_dist if dt >= cutoff else older_dist
            target[r["category"]] = target.get(r["category"], 0) + r["amount"]

        if not recent_dist or not older_dist:
            return 0, {"cosine_sim": 1.0, "reason": "分期数据不足"}

        sim = _cosine_similarity(recent_dist, older_dist)

        if sim < 0.7:
            score = _clamp(16 + (0.7 - sim) / 0.7 * 4)
        elif sim < 0.9:
            score = _clamp(8 + (0.9 - sim) / 0.2 * 7)
        else:
            score = _clamp((1.0 - sim) / 0.1 * 7)

        detail = {
            "cosine_sim": round(sim, 4),
            "recent_distribution": {k: round(v, 2) for k, v in recent_dist.items()},
            "older_distribution": {k: round(v, 2) for k, v in older_dist.items()},
        }
        return score, detail

    # ── E. 时间模式异常 (0-20) ────────────────────────────────────

    def _score_time_patterns(
        self, expenses: list[dict],
    ) -> tuple[int, dict]:
        """周末消费占比 + 月末集中度 + 提交延迟 + 阈值附近聚集度，各 0-5 分。"""
        if not expenses:
            return 0, {"reason": "无数据"}

        total = len(expenses)
        parsed_dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in expenses]

        # E1: 周末消费占比 (正常 ~0-5%，异常 >20%)
        weekend_count = sum(1 for d in parsed_dates if d.weekday() >= 5)
        weekend_ratio = weekend_count / total
        e1 = min(5, int(weekend_ratio / 0.2 * 5))

        # E2: 月末集中度 (25-31 号的消费占比，正常 ~22%，异常 >40%)
        month_end_count = sum(1 for d in parsed_dates if d.day >= 25)
        month_end_ratio = month_end_count / total
        e2 = min(5, int(max(0, month_end_ratio - 0.22) / 0.18 * 5))

        # E3: 提交延迟偏离 (MVP: 基于日期间隔模拟)
        if len(parsed_dates) >= 2:
            gaps = [
                (parsed_dates[i + 1] - parsed_dates[i]).days
                for i in range(len(parsed_dates) - 1)
                if (parsed_dates[i + 1] - parsed_dates[i]).days >= 0
            ]
            avg_gap = statistics.mean(gaps) if gaps else 0
            # 正常 1-3 天提交，异常 >7 天
            e3 = min(5, int(max(0, avg_gap - 3) / 4 * 5))
        else:
            e3 = 0

        # E4: 阈值附近聚集度 (金额在 [阈值*0.9, 阈值] 的占比)
        threshold_map = {"餐饮": 200, "交通": 500, "住宿": 800, "办公": 500}
        near_threshold = 0
        for r in expenses:
            t = threshold_map.get(r["category"], 500)
            if t * 0.9 <= r["amount"] <= t:
                near_threshold += 1
        near_ratio = near_threshold / total
        e4 = min(5, int(near_ratio / 0.15 * 5))

        score = e1 + e2 + e3 + e4
        detail = {
            "weekend_ratio": round(weekend_ratio, 4),
            "weekend_score": e1,
            "month_end_ratio": round(month_end_ratio, 4),
            "month_end_score": e2,
            "submit_delay_score": e3,
            "near_threshold_ratio": round(near_ratio, 4),
            "near_threshold_score": e4,
        }
        return _clamp(score), detail

    # ── 主评分入口 ────────────────────────────────────────────────

    def classify(self, score: int) -> str:
        if score <= 30:
            return "normal"
        elif score <= 60:
            return "elevated"
        else:
            return "high"

    def score(
        self,
        employee_id: str,
        expenses: list[dict],
        company: dict[str, list[dict]],
    ) -> RiskScore:
        """对单个员工计算完整风险评分。"""
        # 计算月均
        if expenses:
            total_amount = sum(r["amount"] for r in expenses)
            dates = sorted(r["date"] for r in expenses)
            first = datetime.strptime(dates[0], "%Y-%m-%d")
            last = datetime.strptime(dates[-1], "%Y-%m-%d")
            m = max((last - first).days / 30.0, 1)
            monthly_avg = total_amount / m
        else:
            monthly_avg = 0

        approver_id = expenses[0].get("approver_id", "") if expenses else ""

        # 五个维度
        a_score, a_detail = self._score_expense_deviation(expenses)
        b_score, b_detail = self._score_peer_deviation(monthly_avg, company, approver_id)
        c_score, c_detail = self._score_merchant_concentration(expenses, company, employee_id)
        d_score, d_detail = self._score_pattern_stability(expenses)
        e_score, e_detail = self._score_time_patterns(expenses)

        total = a_score + b_score + c_score + d_score + e_score
        total = max(0, min(100, total))

        # 生成 top risk factors
        factors: list[tuple[int, str]] = []
        if a_score >= 8:
            factors.append((a_score, f"消费偏离度高 (CV={a_detail.get('cv', 0):.2f})"))
        if b_score >= 8:
            factors.append((b_score, f"月均消费是同组中位数的 {b_detail.get('ratio', 0):.1f} 倍"))
        if c_score >= 8:
            factors.append((c_score, f"独占商户占比 {c_detail.get('exclusive_ratio', 0):.0%}"))
        if d_score >= 8:
            factors.append((d_score, f"消费模式突变 (余弦相似度={d_detail.get('cosine_sim', 0):.2f})"))
        if e_score >= 8:
            parts = []
            if e_detail.get("weekend_score", 0) >= 3:
                parts.append(f"周末消费占比 {e_detail.get('weekend_ratio', 0):.0%}")
            if e_detail.get("near_threshold_score", 0) >= 3:
                parts.append(f"阈值附近聚集 {e_detail.get('near_threshold_ratio', 0):.0%}")
            factors.append((e_score, "时间异常: " + "; ".join(parts) if parts else "时间模式异常"))

        factors.sort(key=lambda x: x[0], reverse=True)
        top_factors = [f for _, f in factors[:3]]
        if not top_factors:
            top_factors = ["未发现显著风险因素"]

        return RiskScore(
            employee_id=employee_id,
            total_score=total,
            classification=self.classify(total),
            dimension_scores={
                "A_expense_deviation": a_score,
                "B_peer_deviation": b_score,
                "C_merchant_concentration": c_score,
                "D_pattern_stability": d_score,
                "E_time_patterns": e_score,
            },
            dimension_details={
                "A_expense_deviation": a_detail,
                "B_peer_deviation": b_detail,
                "C_merchant_concentration": c_detail,
                "D_pattern_stability": d_detail,
                "E_time_patterns": e_detail,
            },
            top_risk_factors=top_factors,
        )

    def batch_score_all(
        self, company: dict[str, list[dict]],
    ) -> list[RiskScore]:
        """对所有员工批量打分并排序（降序）。"""
        results = [
            self.score(eid, exps, company)
            for eid, exps in company.items()
        ]
        results.sort(key=lambda r: r.total_score, reverse=True)
        return results

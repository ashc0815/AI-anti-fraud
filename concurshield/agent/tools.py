"""Agent Tool Registry — 将现有模块封装为 LLM function-calling 可用的标准化 Tool。

每个 Tool 拥有统一接口：name, description, input_schema, execute()。
ToolRegistry 负责注册、查询和执行 Tool。
"""

from __future__ import annotations

import asyncio
import statistics
import time
from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Base abstractions
# ---------------------------------------------------------------------------


class Tool(ABC):
    """所有 Agent Tool 的基类。"""

    name: str
    description: str
    input_schema: dict  # JSON Schema
    cost: str  # "free" | "1_api_call" …

    @abstractmethod
    def execute(self, **kwargs: Any) -> dict:
        """执行 Tool 并返回结构化 JSON 结果。"""


class ToolRegistry:
    """管理所有可用 Tool 的注册表。"""

    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get_tool_schemas(self) -> list[dict]:
        """返回所有 Tool 的 JSON Schema，用于 LLM function calling。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in self.tools.values()
        ]

    def execute(self, tool_name: str, **kwargs: Any) -> dict:
        """执行指定 Tool 并返回结果。"""
        if tool_name not in self.tools:
            raise KeyError(f"Tool '{tool_name}' not found. Available: {list(self.tools)}")
        return self.tools[tool_name].execute(**kwargs)

    def get_descriptions_for_prompt(self) -> str:
        """生成给 Agent system prompt 用的工具描述文本。"""
        lines: list[str] = []
        for t in self.tools.values():
            params = t.input_schema.get("properties", {})
            param_list = ", ".join(
                f"{k}: {v.get('type', 'any')}" for k, v in params.items()
            )
            required = t.input_schema.get("required", [])
            req_str = f" (required: {', '.join(required)})" if required else ""
            lines.append(
                f"- **{t.name}**({param_list}){req_str}\n"
                f"  {t.description}\n"
                f"  Cost: {t.cost}"
            )
        return "\n\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Tool 1: get_employee_profile
# ═══════════════════════════════════════════════════════════════════════════


class GetEmployeeProfileTool(Tool):
    name = "get_employee_profile"
    description = (
        "获取员工行为画像：月均消费、常用城市、常用商户、"
        "费用类型分布、周末消费占比、提交延迟均值。"
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "employee_id": {"type": "string", "description": "员工 ID"},
        },
        "required": ["employee_id"],
    }
    cost = "free"

    def execute(self, *, employee_id: str, **_: Any) -> dict:
        from demo.behavioral_demo import generate_mock_expenses

        expenses = generate_mock_expenses(employee_id)

        # 月均消费
        amounts = [r["amount"] for r in expenses]
        dates = sorted(r["date"] for r in expenses)
        first = datetime.strptime(dates[0], "%Y-%m-%d")
        last = datetime.strptime(dates[-1], "%Y-%m-%d")
        months = max((last - first).days / 30.0, 1)
        monthly_avg = round(sum(amounts) / months, 2)

        # 常用城市
        city_counter = Counter(r["city"] for r in expenses)
        top_cities = [c for c, _ in city_counter.most_common(3)]

        # 常用商户
        merchant_counter = Counter(r["merchant"] for r in expenses)
        top_merchants = [m for m, _ in merchant_counter.most_common(5)]

        # 费用类型分布
        cat_totals: dict[str, float] = {}
        for r in expenses:
            cat_totals[r["category"]] = cat_totals.get(r["category"], 0) + r["amount"]
        total_amount = sum(cat_totals.values())
        category_distribution = {
            cat: round(amt / total_amount, 4) for cat, amt in cat_totals.items()
        }

        # 周末消费占比
        weekend_count = sum(
            1 for r in expenses
            if datetime.strptime(r["date"], "%Y-%m-%d").weekday() >= 5
        )
        weekend_ratio = round(weekend_count / len(expenses), 4) if expenses else 0.0

        # 提交延迟均值（MVP: 模拟 1-5 天随机延迟）
        avg_submit_delay_days = 2.3

        return {
            "employee_id": employee_id,
            "monthly_avg_expense": monthly_avg,
            "top_cities": top_cities,
            "top_merchants": top_merchants,
            "category_distribution": category_distribution,
            "weekend_expense_ratio": weekend_ratio,
            "avg_submit_delay_days": avg_submit_delay_days,
            "total_records": len(expenses),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 2: get_employee_recent_expenses
# ═══════════════════════════════════════════════════════════════════════════


class GetEmployeeRecentExpensesTool(Tool):
    name = "get_employee_recent_expenses"
    description = "获取员工最近 N 个月的报销明细列表。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "employee_id": {"type": "string", "description": "员工 ID"},
            "months": {
                "type": "integer",
                "description": "查询月数（默认 6）",
                "default": 6,
            },
        },
        "required": ["employee_id"],
    }
    cost = "free"

    def execute(self, *, employee_id: str, months: int = 6, **_: Any) -> dict:
        from demo.behavioral_demo import generate_mock_expenses

        all_expenses = generate_mock_expenses(employee_id)

        cutoff = datetime.now() - timedelta(days=months * 30)
        filtered = [
            r for r in all_expenses
            if datetime.strptime(r["date"], "%Y-%m-%d") >= cutoff
        ]
        # 移除内部标签
        clean = [
            {k: v for k, v in r.items() if k != "anomaly_label"}
            for r in filtered
        ]

        return {
            "employee_id": employee_id,
            "months": months,
            "count": len(clean),
            "expenses": clean,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 3: check_math_consistency
# ═══════════════════════════════════════════════════════════════════════════


class CheckMathConsistencyTool(Tool):
    name = "check_math_consistency"
    description = "对 OCR 提取的结构化数据执行数学一致性校验（行项加总、税额、总额）。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "ocr_result": {
                "type": "object",
                "description": "OCR 结构化数据（ReceiptData 格式）",
            },
        },
        "required": ["ocr_result"],
    }
    cost = "free"

    def execute(self, *, ocr_result: dict, **_: Any) -> dict:
        from concurshield.engine.rules import run_rules
        from concurshield.models.schemas import ReceiptData

        receipt = ReceiptData(**ocr_result)
        all_results = run_rules(receipt)

        # 只取数学相关规则 (MATH_*)
        math_results = [r for r in all_results if r.rule_id.startswith("MATH_")]
        discrepancies = [
            {"rule_id": r.rule_id, "rule_name": r.rule_name, "detail": r.detail}
            for r in math_results
            if not r.passed
        ]

        return {
            "passed": len(discrepancies) == 0,
            "checks_run": len(math_results),
            "discrepancies": discrepancies,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 4: check_country_rules
# ═══════════════════════════════════════════════════════════════════════════


class CheckCountryRulesTool(Tool):
    name = "check_country_rules"
    description = "执行国家特定的规则校验（如中国增值税、澳洲 GST/ABN 等）。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "ocr_result": {
                "type": "object",
                "description": "OCR 结构化数据（ReceiptData 格式）",
            },
            "country_code": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 国家代码（如 CN、AU）",
            },
        },
        "required": ["ocr_result", "country_code"],
    }
    cost = "free"

    def execute(self, *, ocr_result: dict, country_code: str, **_: Any) -> dict:
        from concurshield.engine.rules import run_rules
        from concurshield.models.schemas import ReceiptData

        data = dict(ocr_result)
        data["merchant_country"] = country_code
        receipt = ReceiptData(**data)
        all_results = run_rules(receipt)

        # 取非 MATH/AMOUNT/DATE 开头的规则（即国家专用规则 + 货币一致性）
        country_results = [
            r for r in all_results
            if not r.rule_id.startswith(("MATH_00", "AMOUNT_", "DATE_"))
            or r.rule_id == "MATH_004"
        ]
        violations = [
            {"rule_id": r.rule_id, "rule_name": r.rule_name,
             "severity": r.severity, "detail": r.detail}
            for r in country_results
            if not r.passed
        ]

        return {
            "passed": len(violations) == 0,
            "violations": violations,
            "country": country_code,
            "rules_checked": len(country_results),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 5: check_duplicate_hash
# ═══════════════════════════════════════════════════════════════════════════


class CheckDuplicateHashTool(Tool):
    name = "check_duplicate_hash"
    description = "使用 pHash 感知哈希检测图片是否与历史发票重复。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "图片文件路径"},
        },
        "required": ["image_path"],
    }
    cost = "free"

    def execute(self, *, image_path: str, **_: Any) -> dict:
        from concurshield.engine.hasher import compute_hash, find_duplicates

        hash_value = compute_hash(image_path)
        matches = find_duplicates(hash_value)

        return {
            "hash_value": hash_value,
            "is_duplicate": len(matches) > 0,
            "similar_receipts": matches,
            "max_similarity": matches[0]["similarity"] if matches else 0.0,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 6: analyze_exif_metadata
# ═══════════════════════════════════════════════════════════════════════════


class AnalyzeExifMetadataTool(Tool):
    name = "analyze_exif_metadata"
    description = "提取并分析图片的 EXIF 元数据，检测编辑软件痕迹和异常。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "图片文件路径"},
        },
        "required": ["image_path"],
    }
    cost = "free"

    def execute(self, *, image_path: str, **_: Any) -> dict:
        from concurshield.agents.metadata_agent import extract_exif

        path = Path(image_path)
        exif = extract_exif(path)

        anomalies: list[str] = []

        # 编辑软件检测
        software = exif.get("Software", "")
        editing_software = ""
        suspicious_tools = ["photoshop", "gimp", "pixlr", "snapseed", "lightroom"]
        if software and any(t in software.lower() for t in suspicious_tools):
            editing_software = software
            anomalies.append(f"检测到图片编辑软件: {software}")

        # EXIF 完整性
        has_exif = bool(exif)
        if not has_exif:
            anomalies.append("无 EXIF 数据（可能被剥离或截图）")
        else:
            if "DateTimeOriginal" not in exif and "DateTime" not in exif:
                anomalies.append("缺少拍摄时间信息")
            if "Make" not in exif and "Model" not in exif:
                anomalies.append("缺少设备信息")

        # 文件大小
        file_size = path.stat().st_size if path.is_file() else 0
        if file_size < 5000:
            anomalies.append(f"文件异常小 ({file_size} bytes)，可能是截图或合成")

        # GPS
        gps_data: dict[str, Any] = {}
        for key in ("GPSLatitude", "GPSLongitude", "GPSLatitudeRef", "GPSLongitudeRef"):
            if key in exif:
                gps_data[key] = exif[key]

        camera = exif.get("Model", exif.get("Make", ""))
        timestamp = exif.get("DateTimeOriginal", exif.get("DateTime", ""))

        return {
            "has_exif": has_exif,
            "camera": camera,
            "gps": gps_data,
            "timestamp": timestamp,
            "editing_software": editing_software,
            "anomalies": anomalies,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 7: search_merchant_web
# ═══════════════════════════════════════════════════════════════════════════


class SearchMerchantWebTool(Tool):
    name = "search_merchant_web"
    description = "搜索验证商户真实性：是否存在、地址是否匹配、价格区间。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "merchant_name": {"type": "string", "description": "商户名称"},
            "claimed_city": {"type": "string", "description": "发票上声称的城市"},
        },
        "required": ["merchant_name", "claimed_city"],
    }
    cost = "1_api_call"

    def execute(self, *, merchant_name: str, claimed_city: str, **_: Any) -> dict:
        # MVP: 使用现有 merchant_verify 的本地逻辑做基础校验
        # 生产环境应接入搜索 API
        name = merchant_name.strip()

        exists = len(name) >= 2 and not name.isdigit()
        address_match = True  # MVP: 无法验证，默认 True

        # 基于商户名简单推断价格区间
        price_range = "unknown"
        luxury_keywords = ["五星", "豪华", "白金", "铂金", "luxury", "premium"]
        budget_keywords = ["快餐", "便利店", "全家", "711", "麦当劳", "subway"]
        if any(k in name.lower() for k in luxury_keywords):
            price_range = "high"
        elif any(k in name.lower() for k in budget_keywords):
            price_range = "low"
        else:
            price_range = "medium"

        return {
            "merchant_name": merchant_name,
            "claimed_city": claimed_city,
            "exists": exists,
            "address_match": address_match,
            "price_range": price_range,
            "search_results_summary": (
                f"商户 '{merchant_name}' 在 {claimed_city} "
                + ("可查询到相关信息" if exists else "未找到匹配结果")
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 8: get_peer_comparison  (新写)
# ═══════════════════════════════════════════════════════════════════════════


class GetPeerComparisonTool(Tool):
    name = "get_peer_comparison"
    description = "根据审批人 ID 查询同审批人下所有员工的消费统计，识别离群值。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "approver_id": {"type": "string", "description": "审批人 ID"},
        },
        "required": ["approver_id"],
    }
    cost = "free"

    def execute(self, *, approver_id: str, **_: Any) -> dict:
        # MVP: 模拟同审批人下 5 名员工的消费数据
        import random as _rng
        _rng.seed(hash(approver_id) % 2**32)

        peer_ids = [f"EMP-{i:03d}" for i in range(1, 6)]
        peers: list[dict] = []
        monthly_avgs: list[float] = []

        for pid in peer_ids:
            avg = round(_rng.uniform(2000, 8000), 2)
            monthly_avgs.append(avg)
            peers.append({
                "employee_id": pid,
                "monthly_avg": avg,
                "merchant_count": _rng.randint(5, 25),
            })

        monthly_avgs_sorted = sorted(monthly_avgs)
        n = len(monthly_avgs_sorted)
        median_monthly = round(statistics.median(monthly_avgs_sorted), 2)
        q1 = monthly_avgs_sorted[n // 4]
        q3 = monthly_avgs_sorted[(3 * n) // 4]
        iqr = round(q3 - q1, 2)

        # 默认检查第一个员工是否为离群值
        target_avg = peers[0]["monthly_avg"]
        is_outlier = target_avg > q3 + 1.5 * iqr or target_avg < q1 - 1.5 * iqr
        rank = sorted(monthly_avgs, reverse=True).index(target_avg) + 1

        return {
            "approver_id": approver_id,
            "peer_count": len(peers),
            "median_monthly": median_monthly,
            "iqr": iqr,
            "employee_rank": rank,
            "is_outlier": is_outlier,
            "peers": peers,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 9: get_merchant_usage_across_company  (新写)
# ═══════════════════════════════════════════════════════════════════════════


class GetMerchantUsageAcrossCompanyTool(Tool):
    name = "get_merchant_usage_across_company"
    description = "查询某商户在全公司的使用情况，判断是否为某员工独占。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "merchant_name": {"type": "string", "description": "商户名称"},
        },
        "required": ["merchant_name"],
    }
    cost = "free"

    def execute(self, *, merchant_name: str, **_: Any) -> dict:
        # MVP: 已知商户返回多人使用；未知商户返回独占
        from demo.behavioral_demo import _NORMAL_MERCHANTS

        known = any(
            merchant_name in merchants
            for merchants in _NORMAL_MERCHANTS.values()
        )

        if known:
            users = [
                {"employee_id": "EMP-001", "count": 5, "total_amount": 620.0},
                {"employee_id": "EMP-003", "count": 3, "total_amount": 410.0},
                {"employee_id": "EMP-007", "count": 2, "total_amount": 280.0},
            ]
            return {
                "merchant_name": merchant_name,
                "total_users": 3,
                "total_transactions": 10,
                "users": users,
                "is_exclusive": False,
                "exclusive_to": "",
            }

        return {
            "merchant_name": merchant_name,
            "total_users": 1,
            "total_transactions": 1,
            "users": [
                {"employee_id": "EMP-001", "count": 1, "total_amount": 380.0},
            ],
            "is_exclusive": True,
            "exclusive_to": "EMP-001",
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 10: get_travel_bookings  (新写 — MVP 模拟数据)
# ═══════════════════════════════════════════════════════════════════════════


class GetTravelBookingsTool(Tool):
    name = "get_travel_bookings"
    description = "查询员工的出差预订记录（如 Concur Travel 模块已启用）。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "employee_id": {"type": "string", "description": "员工 ID"},
            "date_range": {
                "type": "object",
                "description": "日期范围 {start: 'YYYY-MM-DD', end: 'YYYY-MM-DD'}",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
            },
        },
        "required": ["employee_id"],
    }
    cost = "free"

    def execute(
        self, *, employee_id: str, date_range: dict | None = None, **_: Any
    ) -> dict:
        # MVP: 返回模拟预订数据
        mock_bookings = [
            {
                "booking_id": "BK-20250110-001",
                "type": "flight",
                "origin": "上海",
                "destination": "北京",
                "departure": "2025-01-10",
                "return_date": "2025-01-12",
                "status": "confirmed",
            },
            {
                "booking_id": "BK-20250120-002",
                "type": "hotel",
                "city": "北京",
                "hotel_name": "全季酒店（中关村店）",
                "check_in": "2025-01-10",
                "check_out": "2025-01-12",
                "status": "confirmed",
            },
        ]

        # 按日期范围过滤
        if date_range and "start" in date_range and "end" in date_range:
            start = date_range["start"]
            end = date_range["end"]
            filtered = []
            for b in mock_bookings:
                d = b.get("departure", b.get("check_in", ""))
                if start <= d <= end:
                    filtered.append(b)
            mock_bookings = filtered

        return {
            "employee_id": employee_id,
            "module_enabled": True,
            "booking_count": len(mock_bookings),
            "bookings": mock_bookings,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 11: get_approval_history  (新写)
# ═══════════════════════════════════════════════════════════════════════════


class GetApprovalHistoryTool(Tool):
    name = "get_approval_history"
    description = "查询该员工的审批链历史：驳回率、审批时长、越权次数等。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "employee_id": {"type": "string", "description": "员工 ID"},
        },
        "required": ["employee_id"],
    }
    cost = "free"

    def execute(self, *, employee_id: str, **_: Any) -> dict:
        # MVP: 模拟审批历史数据
        import random as _rng
        _rng.seed(hash(employee_id) % 2**32)

        total_submissions = _rng.randint(30, 120)
        rejections = _rng.randint(0, total_submissions // 10)

        return {
            "employee_id": employee_id,
            "approver_id": f"MGR-{hash(employee_id) % 100:03d}",
            "total_submissions": total_submissions,
            "rejection_rate": round(rejections / total_submissions, 4),
            "avg_approval_time_hours": round(_rng.uniform(2.0, 48.0), 1),
            "override_count": _rng.randint(0, 3),
            "approver_switches": _rng.randint(0, 2),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 12: check_geographic_feasibility  (新写)
# ═══════════════════════════════════════════════════════════════════════════

# 城市间最少旅行时间（小时），基于常见中国城市交通
_CITY_TRAVEL_HOURS: dict[tuple[str, str], float] = {
    ("上海", "北京"): 4.5,   # 高铁
    ("上海", "广州"): 6.5,   # 高铁
    ("上海", "深圳"): 7.0,
    ("上海", "杭州"): 1.0,
    ("上海", "南京"): 1.5,
    ("上海", "成都"): 13.0,  # 高铁 or 3h 飞机
    ("北京", "广州"): 8.0,
    ("北京", "深圳"): 8.5,
    ("北京", "成都"): 7.5,
    ("广州", "深圳"): 0.5,
    ("广州", "成都"): 10.0,
}


def _get_travel_hours(city_a: str, city_b: str) -> float | None:
    """查表获取两城市间最少旅行时间（双向查找）。"""
    if city_a == city_b:
        return 0.0
    key1 = (city_a, city_b)
    key2 = (city_b, city_a)
    return _CITY_TRAVEL_HOURS.get(key1, _CITY_TRAVEL_HOURS.get(key2))


class CheckGeographicFeasibilityTool(Tool):
    name = "check_geographic_feasibility"
    description = "检查同一天多城市消费是否地理上可行。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "expenses_same_day": {
                "type": "array",
                "description": "同天消费列表，每项含 city 字段",
                "items": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "time": {"type": "string", "description": "HH:MM（可选）"},
                        "merchant": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["city"],
                },
            },
        },
        "required": ["expenses_same_day"],
    }
    cost = "free"

    def execute(self, *, expenses_same_day: list[dict], **_: Any) -> dict:
        cities = list({e["city"] for e in expenses_same_day})

        if len(cities) <= 1:
            return {
                "feasible": True,
                "reason": "所有消费在同一城市",
                "min_travel_time_hours": 0.0,
                "cities": cities,
            }

        # 计算所有城市对的最短旅行时间
        max_travel = 0.0
        infeasible_pairs: list[str] = []

        for i, c1 in enumerate(cities):
            for c2 in cities[i + 1:]:
                hours = _get_travel_hours(c1, c2)
                if hours is None:
                    hours = 5.0  # 未知城市对默认 5 小时
                max_travel = max(max_travel, hours)
                if hours > 14:  # 单日往返不可行
                    infeasible_pairs.append(f"{c1} ↔ {c2} ({hours}h)")

        # 一天有效活动时间约 16 小时，旅行超过 14 小时不可行
        feasible = max_travel <= 14.0

        if not feasible:
            reason = f"城市间最短旅行时间 {max_travel}h 超过单日可行范围: {', '.join(infeasible_pairs)}"
        elif max_travel > 8.0:
            reason = f"可行但紧张：城市间需 {max_travel}h，建议核实"
        else:
            reason = f"地理上可行，城市间旅行约 {max_travel}h"

        return {
            "feasible": feasible,
            "reason": reason,
            "min_travel_time_hours": round(max_travel, 1),
            "cities": cities,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 13: get_amount_distribution  (新写)
# ═══════════════════════════════════════════════════════════════════════════


class GetAmountDistributionTool(Tool):
    name = "get_amount_distribution"
    description = "分析某费用类型在审批阈值附近的金额分布，检测 threshold gaming。"
    input_schema: dict = {
        "type": "object",
        "properties": {
            "employee_id": {"type": "string", "description": "员工 ID"},
            "expense_type": {"type": "string", "description": "费用类型（如 餐饮、交通）"},
            "threshold": {
                "type": "number",
                "description": "审批阈值金额（可选，默认按类型推断）",
            },
        },
        "required": ["employee_id", "expense_type"],
    }
    cost = "free"

    # 常见审批阈值（按类型）
    _DEFAULT_THRESHOLDS: dict[str, float] = {
        "餐饮": 200.0,
        "交通": 500.0,
        "住宿": 800.0,
        "办公": 500.0,
    }

    def execute(
        self,
        *,
        employee_id: str,
        expense_type: str,
        threshold: float | None = None,
        **_: Any,
    ) -> dict:
        from demo.behavioral_demo import generate_mock_expenses

        expenses = generate_mock_expenses(employee_id)
        typed = [r for r in expenses if r["category"] == expense_type]
        amounts = [r["amount"] for r in typed]

        if not amounts:
            return {
                "employee_id": employee_id,
                "expense_type": expense_type,
                "total_count": 0,
                "near_threshold_count": 0,
                "near_threshold_ratio": 0.0,
                "distribution_stats": {},
            }

        if threshold is None:
            threshold = self._DEFAULT_THRESHOLDS.get(expense_type, 500.0)

        # "近阈值" = 阈值的 80%-100%
        near_low = threshold * 0.8
        near_count = sum(1 for a in amounts if near_low <= a <= threshold)

        mean_val = statistics.mean(amounts)
        median_val = statistics.median(amounts)
        std_val = statistics.stdev(amounts) if len(amounts) > 1 else 0.0
        sorted_a = sorted(amounts)
        n = len(sorted_a)
        p25 = sorted_a[n // 4] if n >= 4 else sorted_a[0]
        p75 = sorted_a[(3 * n) // 4] if n >= 4 else sorted_a[-1]

        return {
            "employee_id": employee_id,
            "expense_type": expense_type,
            "threshold": threshold,
            "total_count": len(amounts),
            "near_threshold_count": near_count,
            "near_threshold_ratio": round(near_count / len(amounts), 4),
            "distribution_stats": {
                "mean": round(mean_val, 2),
                "median": round(median_val, 2),
                "std": round(std_val, 2),
                "p25": round(p25, 2),
                "p75": round(p75, 2),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
# Registry factory
# ═══════════════════════════════════════════════════════════════════════════


def create_default_registry() -> ToolRegistry:
    """创建包含所有内置 Tool 的默认 ToolRegistry。"""
    registry = ToolRegistry()
    registry.register(GetEmployeeProfileTool())
    registry.register(GetEmployeeRecentExpensesTool())
    registry.register(CheckMathConsistencyTool())
    registry.register(CheckCountryRulesTool())
    registry.register(CheckDuplicateHashTool())
    registry.register(AnalyzeExifMetadataTool())
    registry.register(SearchMerchantWebTool())
    registry.register(GetPeerComparisonTool())
    registry.register(GetMerchantUsageAcrossCompanyTool())
    registry.register(GetTravelBookingsTool())
    registry.register(GetApprovalHistoryTool())
    registry.register(CheckGeographicFeasibilityTool())
    registry.register(GetAmountDistributionTool())
    return registry

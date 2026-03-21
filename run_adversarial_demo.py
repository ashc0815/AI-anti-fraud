#!/usr/bin/env python3
"""对抗性测试演示脚本

顺序运行 5 个 PRD Appendix A 测试用例，生成：
  - test_results/<test_name>.json  （每个用例的详细报告）
  - test_results/adversarial_summary.md  （面试展示用汇总报告）

用法：python run_adversarial_demo.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path("test_results")
SUMMARY_PATH = RESULTS_DIR / "adversarial_summary.md"

TEST_CASES = [
    "test_normal_receipt",
    "test_amount_tampered",
    "test_ai_generated",
    "test_prompt_injection",
    "test_duplicate_submission",
]

DESCRIPTIONS = {
    "test_normal_receipt": "Normal Receipt (T1 Auto-pass)",
    "test_amount_tampered": "Amount Tampered (MATH rule failure)",
    "test_ai_generated": "AI-Generated Receipt (Visual Forensics)",
    "test_prompt_injection": "Prompt Injection Attack",
    "test_duplicate_submission": "Duplicate Submission (Hash Dedup)",
}


def run_tests() -> tuple[bool, str, float]:
    """运行 pytest 并返回 (all_passed, stdout, duration_seconds)。"""
    start = time.time()
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_adversarial.py",
            "-v", "--tb=short", "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    duration = time.time() - start
    output = result.stdout + result.stderr
    return result.returncode == 0, output, duration


def load_result(test_name: str) -> dict | None:
    """从 test_results/<name>.json 读取结果。"""
    path = RESULTS_DIR / f"{test_name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def generate_summary(all_passed: bool, pytest_output: str, duration: float) -> str:
    """生成 Markdown 汇总报告。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# ConcurShield Adversarial Test Report",
        "",
        f"> Generated: {now}",
        f"> Duration: {duration:.1f}s",
        f"> Overall: **{'ALL PASSED' if all_passed else 'SOME FAILED'}**",
        "",
        "---",
        "",
        "## Summary Table",
        "",
        "| # | Test Case | Scenario | Tier | Score | Result |",
        "|---|-----------|----------|------|-------|--------|",
    ]

    results = []
    for i, name in enumerate(TEST_CASES, 1):
        data = load_result(name)
        if data is None:
            lines.append(f"| {i} | `{name}` | {DESCRIPTIONS[name]} | - | - | SKIPPED |")
            results.append(None)
            continue

        report = data.get("forensic_report", {})
        tier = report.get("confidence_tier", "?")
        score = report.get("risk_score", "?")
        passed = data.get("passed", False)
        status = "PASS" if passed else "FAIL"
        lines.append(
            f"| {i} | `{name}` | {DESCRIPTIONS[name]} | {tier} | {score} | {status} |"
        )
        results.append(data)

    lines.extend(["", "---", ""])

    # ── 每个用例的详细分析 ──────────────────────────────────────
    for i, name in enumerate(TEST_CASES, 1):
        data = results[i - 1]
        if data is None:
            continue

        report = data.get("forensic_report", {})
        lines.extend([
            f"## Test {i}: {DESCRIPTIONS[name]}",
            "",
            f"**File:** `{name}`",
            f"**Input:** {data.get('input_description', 'N/A')}",
            "",
            "### Expected vs Actual",
            "",
            "| Criterion | Expected | Actual |",
            "|-----------|----------|--------|",
        ])

        expected = data.get("expected", {})
        actual = data.get("actual", {})
        for key in expected:
            exp_val = expected[key]
            act_val = actual.get(key, "N/A")
            match = "==" if str(exp_val) == str(act_val) else "!="
            lines.append(f"| {key} | {exp_val} | {act_val} |")

        # 规则结果
        rule_checks = report.get("rule_checks", [])
        if rule_checks:
            lines.extend(["", "### Rule Check Results", ""])
            lines.append("| Rule ID | Rule Name | Severity | Passed |")
            lines.append("|---------|-----------|----------|--------|")
            for r in rule_checks:
                status = "PASS" if r["passed"] else "**FAIL**"
                lines.append(
                    f"| {r['rule_id']} | {r['rule_name']} | {r['severity']} | {status} |"
                )

        # Agent 行动
        agent_actions = report.get("agent_actions", [])
        if agent_actions:
            lines.extend(["", "### Agent Actions", ""])
            for a in agent_actions:
                lines.extend([
                    f"- **{a['agent_name']}** / `{a['tool_name']}` ({a['duration_ms']}ms)",
                    f"  - {a['output_summary'][:200]}",
                ])

        # 风险分解
        breakdown = report.get("risk_breakdown", {})
        if breakdown:
            lines.extend(["", "### Risk Breakdown", ""])
            for k, v in breakdown.items():
                if k != "weights_used":
                    lines.append(f"- {k}: {v}")

        lines.extend(["", "---", ""])

    # ── pytest 原始输出 ─────────────────────────────────────────
    lines.extend([
        "## Raw pytest Output",
        "",
        "```",
        pytest_output.strip(),
        "```",
        "",
        "---",
        "",
        "*Report generated by `run_adversarial_demo.py`*",
    ])

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("  ConcurShield Adversarial Test Suite")
    print("=" * 60)
    print()

    # 确保测试图片存在
    subprocess.run(
        [sys.executable, "scripts/generate_test_images.py"],
        check=True,
    )
    print()

    # 运行 pytest
    print("Running adversarial tests...")
    print("-" * 40)
    all_passed, output, duration = run_tests()
    print(output)
    print("-" * 40)
    print(f"Duration: {duration:.1f}s")
    print(f"Result: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print()

    # 生成汇总报告
    summary = generate_summary(all_passed, output, duration)
    RESULTS_DIR.mkdir(exist_ok=True)
    SUMMARY_PATH.write_text(summary, encoding="utf-8")
    print(f"Summary report: {SUMMARY_PATH}")
    print()

    # 列出所有输出文件
    print("Generated files:")
    for f in sorted(RESULTS_DIR.iterdir()):
        size = f.stat().st_size
        print(f"  {f}  ({size:,} bytes)")


if __name__ == "__main__":
    main()

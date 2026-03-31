"""运行评估: python -m concurshield.eval"""

import asyncio
import sys

from concurshield.eval.evaluator import run_eval, format_eval_report


def main():
    provider = sys.argv[1] if len(sys.argv) > 1 else "mock"
    api_key = sys.argv[2] if len(sys.argv) > 2 else ""
    runs = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    print(f"Running evaluation: provider={provider}, runs_per_case={runs}")
    print()

    result = asyncio.run(run_eval(llm_provider=provider, api_key=api_key, runs_per_case=runs))
    print(format_eval_report(result))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run golden-set evals against process_query and write a baseline JSON report.

Usage:
    python tests/evals/run_evals.py
    python tests/evals/run_evals.py --dry-run   # judge only, no API calls
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLDEN_PATH = Path(__file__).resolve().parent / "golden.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_golden() -> list[dict]:
    cases: list[dict] = []
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def run_evals(*, dry_run: bool = False, use_haiku: bool = False) -> dict:
    from config import Config
    from improvement.judge import judge_turn

    cases = _load_golden()
    results: list[dict] = []
    tools_called: list[str] = []

    if not dry_run:
        import pipeline
        from tools import registry

        original_dispatch = registry.dispatch_tool

        def tracking_dispatch(
            name: str,
            inputs: dict,
            confirm: bool = False,
            **kwargs,
        ):
            tools_called.append(name)
            return original_dispatch(name, inputs, confirm=confirm, **kwargs)

        registry.dispatch_tool = tracking_dispatch  # type: ignore[method-assign]
        cfg = Config.load()

    for golden in cases:
        tools_called.clear()
        actual = ""
        error = None
        if dry_run:
            actual = "(dry-run — no API call)"
        else:
            try:
                out = pipeline.process_query(golden["input"], cfg, speak=False)
                actual = str(out.get("reply", ""))
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                actual = ""

        verdict = judge_turn(
            golden,
            actual,
            list(tools_called),
            use_haiku=use_haiku and bool(golden.get("expected_behavior")),
        )
        results.append({
            "case_id": golden.get("id"),
            "input": golden.get("input"),
            "tags": golden.get("tags", []),
            "response": actual[:500],
            "tools_called": list(tools_called),
            "error": error,
            **verdict,
        })

    passed = sum(1 for r in results if r.get("pass"))
    report = {
        "date": date.today().isoformat(),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "results": results,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Jarvis golden-set evals")
    parser.add_argument("--dry-run", action="store_true", help="Skip process_query API calls")
    parser.add_argument("--haiku", action="store_true", help="Use Haiku for fuzzy behavior checks")
    parser.add_argument("--output", type=Path, help="Override output JSON path")
    args = parser.parse_args()

    report = run_evals(dry_run=args.dry_run, use_haiku=args.haiku)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.output or (RESULTS_DIR / f"baseline_{date.today().strftime('%Y%m%d')}.json")
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} — {report['passed']}/{report['total']} passed")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

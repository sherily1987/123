#!/usr/bin/env python3
"""只读 hybrid 上线资格门禁；绝不改变生产推荐开关。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def admission_report(evaluation: dict, *, minimum_n: int = 100) -> dict:
    reasons = []
    if int(evaluation.get("n") or 0) < minimum_n:
        reasons.append("insufficient_sample")
    metrics = evaluation.get("metrics") or {}
    for name in ("brier", "logloss"):
        metric = metrics.get(name) or {}
        delta = metric.get("delta_hybrid_minus_market")
        ci = metric.get("paired_bootstrap_95_ci")
        if not isinstance(delta, (int, float)) or delta >= 0:
            reasons.append(f"{name}_not_better_than_market")
        if not isinstance(ci, list) or len(ci) != 2 or not all(isinstance(x, (int, float)) for x in ci):
            reasons.append(f"{name}_ci_unavailable")
        elif ci[1] >= 0:
            reasons.append(f"{name}_ci_not_strictly_below_zero")
    return {
        "schema_version": "hybrid-admission-1.0",
        "research_only": True,
        "evaluation_n": int(evaluation.get("n") or 0),
        "minimum_n": minimum_n,
        "status": "BLOCKED" if reasons else "ELIGIBLE_FOR_HUMAN_REVIEW",
        "reasons": reasons,
        "automatic_production_change": False,
        "production_recommendations_enabled": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="hybrid 生产融合资格门禁（只读）")
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--minimum-n", type=int, default=100)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    evaluation = json.loads(Path(args.evaluation).read_text(encoding="utf-8"))
    report = admission_report(evaluation, minimum_n=args.minimum_n)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

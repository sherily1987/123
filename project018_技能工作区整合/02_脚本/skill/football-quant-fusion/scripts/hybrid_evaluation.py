#!/usr/bin/env python3
"""独立 hybrid 相对同场市场的赛后配对评测（只读研究工单）。"""
from __future__ import annotations

import json
import math
import random
import argparse
from datetime import datetime
from pathlib import Path


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _actual_index(score) -> int | None:
    try:
        if isinstance(score, dict):
            home, away = int(score["home"]), int(score["away"])
        elif isinstance(score, str) and "-" in score:
            home, away = (int(x.strip()) for x in score.split("-", 1))
        else:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return 0 if home > away else (2 if home < away else 1)


def _probabilities(values) -> list[float] | None:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return None
    try:
        probs = [float(value) / 100.0 if float(value) > 1.5 else float(value) for value in values]
    except (TypeError, ValueError):
        return None
    total = sum(probs)
    if any(value < 0 for value in probs) or total <= 0:
        return None
    return [value / total for value in probs]


def _brier(probs: list[float], actual: int) -> float:
    return sum((prob - (1.0 if index == actual else 0.0)) ** 2 for index, prob in enumerate(probs))


def _logloss(probs: list[float], actual: int) -> float:
    return -math.log(max(probs[actual], 1e-15))


def _score_90(job: dict, jobs_root: Path) -> object:
    settlement = job.get("settlement") or {}
    if settlement.get("score_90") is not None:
        return settlement["score_90"]
    match_id = (job.get("identity") or {}).get("match_id")
    if not match_id:
        return None
    result_path = jobs_root.parent / "backtest" / "results" / f"{match_id}.json"
    if not result_path.exists():
        return None
    try:
        return (json.loads(result_path.read_text(encoding="utf-8")) or {}).get("score_90")
    except (OSError, ValueError):
        return None


def _router_audit_reason(hybrid: dict, kickoff: datetime) -> str | None:
    """Require persisted point-in-time evidence for an independent prior."""
    audit = hybrid.get("routing_audit")
    if not isinstance(audit, dict):
        return "missing_router_audit"
    if audit.get("no_future_leakage") is not True:
        return "router_audit_no_future_leakage_not_confirmed"
    history_latest = _parse_time(audit.get("history_latest"))
    if history_latest is None:
        return "missing_router_history_latest"
    if history_latest >= kickoff:
        return "router_history_not_prematch"
    research_run_at = _parse_time(hybrid.get("research_run_at"))
    if research_run_at is None:
        return "missing_research_run_at"
    if research_run_at >= kickoff:
        return "research_run_not_prematch"
    return None


def _eligible(job: dict, jobs_root: Path) -> tuple[dict | None, str | None]:
    hybrid = ((job.get("research") or {}).get("hybrid") or {})
    if hybrid.get("research_only") is not True or hybrid.get("mode") != "hybrid" or hybrid.get("status") != "ok":
        return None, "not_independent_hybrid"
    if hybrid.get("market_derived") is True:
        return None, "market_derived"
    if not isinstance(hybrid.get("lambda_prior"), dict):
        return None, "missing_independent_prior"
    input_obj = job.get("input") or {}
    prediction_as_of = _parse_time(input_obj.get("prediction_as_of") or input_obj.get("collected_at"))
    kickoff = _parse_time(input_obj.get("kickoff") or input_obj.get("kickoff_iso"))
    if prediction_as_of is None or kickoff is None or prediction_as_of >= kickoff:
        return None, "not_prematch"
    audit_reason = _router_audit_reason(hybrid, kickoff)
    if audit_reason:
        return None, audit_reason
    hybrid_probs = _probabilities(hybrid.get("final_1x2_pct"))
    market_probs = _probabilities(hybrid.get("market_1x2_pct"))
    if hybrid_probs is None or market_probs is None:
        return None, "invalid_probability_pair"
    actual = _actual_index(_score_90(job, jobs_root))
    if actual is None:
        return None, "missing_verified_score_90"
    identity = job.get("identity") or {}
    return {
        "match_id": identity.get("match_id"),
        "actual_idx": actual,
        "hybrid_probs": hybrid_probs,
        "market_probs": market_probs,
        "weight_sweep": hybrid.get("weight_sweep"),
    }, None


def _mean(rows: list[dict], key: str) -> float:
    return sum(float(row[key]) for row in rows) / len(rows)


def _bootstrap_ci(rows: list[dict], key: str, samples: int, seed: int) -> list[float] | None:
    if len(rows) < 2 or samples <= 0:
        return None
    rng = random.Random(seed)
    n = len(rows)
    means = sorted(
        sum(float(rows[rng.randrange(n)][key]) for _ in range(n)) / n
        for _ in range(samples)
    )
    lower = means[int(0.025 * (samples - 1))]
    upper = means[math.ceil(0.975 * (samples - 1))]
    return [round(lower, 6), round(upper, 6)]


def _weight_key(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _weight_sweep_metrics(rows: list[dict], samples: int, seed: int) -> dict:
    """Same-match paired metrics for one explicit market-weight candidate."""
    return {
        "brier": {
            "candidate": round(_mean(rows, "brier_candidate"), 6),
            "market": round(_mean(rows, "brier_market"), 6),
            "delta_candidate_minus_market": round(_mean(rows, "brier_delta_candidate_minus_market"), 6),
            "paired_bootstrap_95_ci": _bootstrap_ci(
                rows, "brier_delta_candidate_minus_market", samples, seed),
        },
        "logloss": {
            "candidate": round(_mean(rows, "logloss_candidate"), 6),
            "market": round(_mean(rows, "logloss_market"), 6),
            "delta_candidate_minus_market": round(_mean(rows, "logloss_delta_candidate_minus_market"), 6),
            "paired_bootstrap_95_ci": _bootstrap_ci(
                rows, "logloss_delta_candidate_minus_market", samples, seed),
        },
    }


def evaluate_jobs(jobs_root: Path | str, *, bootstrap_samples: int = 2000,
                  bootstrap_seed: int = 20260821) -> dict:
    """评测所有 sales_day 工单；只统计可验证的独立赛前 hybrid 概率。"""
    root = Path(jobs_root)
    rows: list[dict] = []
    sweep_rows: dict[str, list[dict]] = {}
    excluded: dict[str, int] = {}
    scanned_jobs = 0
    hybrid_sidecars = 0
    hybrid_ok_sidecars = 0
    router_audited_sidecars = 0
    for path in sorted(root.rglob("sporttery-*.json")):
        scanned_jobs += 1
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            excluded["unreadable_job"] = excluded.get("unreadable_job", 0) + 1
            continue
        hybrid = ((job.get("research") or {}).get("hybrid") or {})
        if isinstance(hybrid, dict) and hybrid:
            hybrid_sidecars += 1
            if hybrid.get("status") == "ok" and hybrid.get("research_only") is True:
                hybrid_ok_sidecars += 1
            if isinstance(hybrid.get("routing_audit"), dict):
                router_audited_sidecars += 1
        row, reason = _eligible(job, root)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        assert row is not None
        actual = row.pop("actual_idx")
        hybrid_probs, market_probs = row.pop("hybrid_probs"), row.pop("market_probs")
        sweep = row.pop("weight_sweep", [])
        row["brier_hybrid"] = _brier(hybrid_probs, actual)
        row["brier_market"] = _brier(market_probs, actual)
        row["logloss_hybrid"] = _logloss(hybrid_probs, actual)
        row["logloss_market"] = _logloss(market_probs, actual)
        row["brier_delta_hybrid_minus_market"] = row["brier_hybrid"] - row["brier_market"]
        row["logloss_delta_hybrid_minus_market"] = row["logloss_hybrid"] - row["logloss_market"]
        rows.append(row)
        if not isinstance(sweep, list):
            continue
        for variant in sweep:
            if not isinstance(variant, dict) or variant.get("research_only") is not True:
                continue
            if variant.get("status") != "ok":
                continue
            try:
                weight = float(variant["market_weight"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0.0 <= weight <= 1.0:
                continue
            candidate_probs = _probabilities(variant.get("final_1x2_pct"))
            variant_market = _probabilities(variant.get("market_1x2_pct"))
            if candidate_probs is None or variant_market is None:
                continue
            # One sweep must hold the market snapshot fixed.  Otherwise its
            # comparison would conflate blend weight with a different price.
            if any(abs(left - right) > 1e-9 for left, right in zip(market_probs, variant_market)):
                continue
            variant_row = {
                "match_id": row["match_id"],
                "brier_candidate": _brier(candidate_probs, actual),
                "brier_market": row["brier_market"],
                "logloss_candidate": _logloss(candidate_probs, actual),
                "logloss_market": row["logloss_market"],
            }
            variant_row["brier_delta_candidate_minus_market"] = (
                variant_row["brier_candidate"] - variant_row["brier_market"])
            variant_row["logloss_delta_candidate_minus_market"] = (
                variant_row["logloss_candidate"] - variant_row["logloss_market"])
            sweep_rows.setdefault(_weight_key(weight), []).append(variant_row)
    report = {
        "schema_version": "hybrid-oos-evaluation-1.0",
        "research_only": True,
        "bootstrap": {"samples": bootstrap_samples, "seed": bootstrap_seed},
        "n": len(rows),
        "coverage": {
            "scanned_jobs": scanned_jobs,
            "hybrid_sidecars": hybrid_sidecars,
            "hybrid_ok_sidecars": hybrid_ok_sidecars,
            "router_audited_sidecars": router_audited_sidecars,
            "note": "覆盖率只描述工单证据完整度，不改变有效样本资格或生产门禁",
        },
        "excluded": excluded,
        "rows": rows,
    }
    if rows:
        report["metrics"] = {
            "brier": {
                "hybrid": round(_mean(rows, "brier_hybrid"), 6),
                "market": round(_mean(rows, "brier_market"), 6),
                "delta_hybrid_minus_market": round(_mean(rows, "brier_delta_hybrid_minus_market"), 6),
                "paired_bootstrap_95_ci": _bootstrap_ci(
                    rows, "brier_delta_hybrid_minus_market", bootstrap_samples, bootstrap_seed),
            },
            "logloss": {
                "hybrid": round(_mean(rows, "logloss_hybrid"), 6),
                "market": round(_mean(rows, "logloss_market"), 6),
                "delta_hybrid_minus_market": round(_mean(rows, "logloss_delta_hybrid_minus_market"), 6),
                "paired_bootstrap_95_ci": _bootstrap_ci(
                    rows, "logloss_delta_hybrid_minus_market", bootstrap_samples, bootstrap_seed),
            },
        }
    else:
        report["metrics"] = None
    report["weight_sweep"] = {
        "research_only": True,
        "n": sum(len(group) for group in sweep_rows.values()),
        "by_market_weight": {
            weight: {"n": len(group), "metrics": _weight_sweep_metrics(
                group, bootstrap_samples, bootstrap_seed)}
            for weight, group in sorted(sweep_rows.items(), key=lambda item: float(item[0]))
        },
        "note": "每个权重仅与同一场、同一盘口快照配对；不改变生产market_only输出。",
    }
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="独立 hybrid 相对同场市场的样本外配对评测")
    parser.add_argument("--jobs-root")
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260821)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    jobs_root = args.jobs_root
    if jobs_root is None:
        from job_ticket import jobs_root as default_jobs_root
        jobs_root = str(default_jobs_root())
    report = evaluate_jobs(jobs_root, bootstrap_samples=args.bootstrap_samples,
                           bootstrap_seed=args.bootstrap_seed)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

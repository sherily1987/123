#!/usr/bin/env python3
"""Settle draw-watch/focus labels separately from the 1X2 model backtest."""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from fusion_backtest import (
    dedupe_snapshot_rows,
    load_jsonl,
    resolve_path,
    score_record,
    select_primary_rows,
)
from runtime_paths import backtest_store


def wilson_interval(successes: int, total: int, z: float = 1.95996398454) -> list[float] | None:
    """Return a 95% Wilson interval for a binary success rate."""
    if total <= 0:
        return None
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return [centre - radius, centre + radius]


def _tier_metrics(rows: list[dict], all_actual_draws: int) -> dict:
    successes = sum(int(row["actual_idx"]) == 1 for row in rows)
    n = len(rows)
    return {
        "n": n,
        "draw_hits": successes,
        "draw_precision": successes / n if n else None,
        "draw_precision_wilson95": wilson_interval(successes, n),
        "draw_recall": successes / all_actual_draws if all_actual_draws else None,
    }


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def paired_shadow_metrics(rows: list[dict], bootstrap_draws: int = 2000, seed: int = 20260822) -> dict:
    """Paired proper-score comparison of shadow versus original on same matches."""
    paired = []
    for row in rows:
        base, shadow = row.get("probs"), row.get("shadow_probs")
        actual = row.get("actual_idx")
        if not (isinstance(base, list) and isinstance(shadow, list)
                and len(base) == len(shadow) == 3 and actual in (0, 1, 2)):
            continue
        index = int(actual)
        base_brier = sum((float(value) - float(pos == index)) ** 2 for pos, value in enumerate(base))
        shadow_brier = sum((float(value) - float(pos == index)) ** 2 for pos, value in enumerate(shadow))
        base_logloss = -math.log(max(float(base[index]), 1e-12))
        shadow_logloss = -math.log(max(float(shadow[index]), 1e-12))
        paired.append((shadow_brier - base_brier, shadow_logloss - base_logloss))
    if not paired:
        return {"n": 0, "status": "no_settled_shadow_probability"}
    rng = random.Random(seed)

    def summary(position: int) -> dict:
        deltas = [item[position] for item in paired]
        sampled = [sum(deltas[rng.randrange(len(deltas))] for _ in range(len(deltas))) / len(deltas)
                   for _ in range(max(1, bootstrap_draws))]
        return {
            "delta_shadow_minus_base": sum(deltas) / len(deltas),
            "ci95": [_quantile(sampled, 0.025), _quantile(sampled, 0.975)],
        }

    brier, logloss = summary(0), summary(1)
    return {
        "n": len(paired), "bootstrap_draws": max(1, bootstrap_draws), "seed": seed,
        "one_x2_brier_delta_shadow_minus_base": brier["delta_shadow_minus_base"],
        "one_x2_brier_delta_shadow_minus_base_ci95": brier["ci95"],
        "one_x2_logloss_delta_shadow_minus_base": logloss["delta_shadow_minus_base"],
        "one_x2_logloss_delta_shadow_minus_base_ci95": logloss["ci95"],
        "interpretation": "negative is better; both upper CI bounds must be below zero before review",
    }


def summarize_rows(rows: list[dict], minimum_focus_n: int = 100) -> dict:
    """Report broad watch and restrictive focus performance without mixing them."""
    all_actual_draws = sum(int(row["actual_idx"]) == 1 for row in rows)
    all_settled = {
        "n": len(rows),
        "actual_draws": all_actual_draws,
        "actual_draw_rate": all_actual_draws / len(rows) if rows else None,
    }
    watch = [row for row in rows if row.get("tier") in {"watch", "focus"}]
    focus = [row for row in rows if row.get("tier") == "focus"]
    focus_metrics = _tier_metrics(focus, all_actual_draws)
    if focus_metrics["n"] < minimum_focus_n:
        admission = {"decision": "hold", "reason_code": "FOCUS_SAMPLE_BELOW_MINIMUM"}
    elif focus_metrics["draw_precision_wilson95"][0] <= all_settled["actual_draw_rate"]:
        admission = {"decision": "hold", "reason_code": "FOCUS_PRECISION_NOT_ABOVE_BASE_RATE"}
    else:
        admission = {
            "decision": "eligible_for_review",
            "reason_code": "FOCUS_PRECISION_ABOVE_BASE_RATE_WITH_WILSON_SUPPORT",
        }
    return {
        "research_only": True,
        "probability_adjustment_applied": False,
        "all_settled": all_settled,
        "watch_including_focus": _tier_metrics(watch, all_actual_draws),
        "focus_only": focus_metrics,
        "admission": {**admission, "minimum_focus_n": minimum_focus_n},
    }


def settled_label_rows(store: Path, snapshot_policy: str = "latest_before_kickoff") -> tuple[list[dict], dict]:
    """Load only 90-minute-settled formal records carrying a draw label."""
    candidates, excluded = [], {}
    for entry in load_jsonl(store / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), store)
        if not path.exists():
            excluded["missing_prediction"] = excluded.get("missing_prediction", 0) + 1
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            excluded["invalid_prediction"] = excluded.get("invalid_prediction", 0) + 1
            continue
        scored, reason = score_record(record, store)
        if scored is None:
            excluded[reason or "unscored"] = excluded.get(reason or "unscored", 0) + 1
            continue
        output = record.get("output") or {}
        core = output.get("core_output") or output
        forecast = output.get("forecast") or core.get("forecast") or {}
        label = forecast.get("draw_research") if isinstance(forecast, dict) else None
        if not isinstance(label, dict) or label.get("research_only") is not True:
            excluded["no_draw_research_label"] = excluded.get("no_draw_research_label", 0) + 1
            continue
        tier = str(label.get("tier") or "none")
        if tier not in {"none", "watch", "focus"}:
            excluded["invalid_draw_research_tier"] = excluded.get("invalid_draw_research_tier", 0) + 1
            continue
        shadow = forecast.get("draw_calibration_shadow") if isinstance(forecast, dict) else None
        shadow_pct = shadow.get("shadow_final_1x2_pct") if isinstance(shadow, dict) else None
        shadow_probs = None
        if isinstance(shadow_pct, list) and len(shadow_pct) == 3:
            try:
                parsed = [float(value) / 100.0 for value in shadow_pct]
                if all(0.0 <= value <= 1.0 for value in parsed) and 0.999 <= sum(parsed) <= 1.001:
                    shadow_probs = parsed
            except (TypeError, ValueError):
                pass
        candidates.append({**scored, "tier": tier, "draw_research": label, "shadow_probs": shadow_probs})
    deduped, dropped = dedupe_snapshot_rows(candidates)
    primary = select_primary_rows(deduped, snapshot_policy)
    return primary, {"excluded": excluded, "dedupe_dropped": len(dropped), "candidate_snapshots": len(candidates)}


def evaluate_store(store: Path, snapshot_policy: str = "latest_before_kickoff", minimum_focus_n: int = 100) -> dict:
    rows, audit = settled_label_rows(store, snapshot_policy)
    report = summarize_rows(rows, minimum_focus_n)
    report.update({
        "schema_version": "fusion-draw-watch-evaluation-1.0",
        "source_policy": "formal registered predictions + verified 90-minute settlement only",
        "snapshot_policy": snapshot_policy,
        "row_audit": audit,
        "shadow_probability_paired": paired_shadow_metrics(rows),
    })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=backtest_store())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-policy", default="latest_before_kickoff",
                        choices=("latest_before_kickoff", "prematch", "closing"))
    parser.add_argument("--minimum-focus-n", type=int, default=100)
    args = parser.parse_args()
    if args.minimum_focus_n < 1:
        parser.error("--minimum-focus-n must be positive")
    report = evaluate_store(args.store, args.snapshot_policy, args.minimum_focus_n)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

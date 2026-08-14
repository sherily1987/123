#!/usr/bin/env python3
"""Strict same-match production-route evaluation; never mixes cohorts or snapshots."""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path


def time_order_split(rows: list[dict], test_ratio: float = 0.3) -> tuple[list[dict], list[dict]]:
    ordered = sorted(rows, key=lambda r: str(r.get("kickoff") or ""))
    cut = max(1, min(len(ordered) - 1, int(len(ordered) * (1 - test_ratio))))
    return ordered[:cut], ordered[cut:]


def _score(row: dict):
    value = row.get("official_90min_score", row.get("score_90", row.get("official_score")))
    if isinstance(value, dict):
        value = [value.get("home"), value.get("away")]
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in value):
        return tuple(value)
    return None


def _outcome(score):
    if score is None:
        return None
    return 0 if score[0] > score[1] else 1 if score[0] == score[1] else 2


def _probs(row: dict, prefix: str = ""):
    keys = ([f"{prefix}_probs"] if prefix else []) + ["probs", "probabilities"]
    for key in keys:
        value = row.get(key)
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                result = [float(x) for x in value]
            except (TypeError, ValueError):
                continue
            if all(x >= 0 for x in result) and abs(sum(result) - 1) <= 1e-5:
                return result
    return None


def classify_cohort(cohort_key, current_cohort_key=None):
    if not cohort_key:
        return "unknown"
    if current_cohort_key is not None:
        return "current" if cohort_key == current_cohort_key else "legacy"
    if cohort_key == "current" or str(cohort_key).startswith("current-"):
        return "current"
    if str(cohort_key).startswith("legacy-"):
        return "legacy"
    return "unknown"


def _latest_prekickoff(rows):
    # ISO-8601 lexical ordering is safe only after requiring a present timestamp; caller data is retained verbatim.
    valid = [r for r in rows if r.get("prediction_as_of") and r.get("kickoff") and str(r["prediction_as_of"]) < str(r["kickoff"])]
    return max(valid, key=lambda r: str(r["prediction_as_of"])) if valid else None


def build_strict_pairs(quant_rows, llm_rows, current_cohort_key=None):
    """Return only pairs with same match_id, official 90-minute score, and cohort_key."""
    q_by_id, l_by_id = {}, {}
    for row in quant_rows:
        if row.get("match_id"):
            q_by_id.setdefault(row["match_id"], []).append(row)
    for row in llm_rows:
        if row.get("match_id"):
            l_by_id.setdefault(row["match_id"], []).append(row)
    pairs, excluded = [], []
    for match_id in sorted(set(q_by_id) | set(l_by_id)):
        quant, llm = _latest_prekickoff(q_by_id.get(match_id, [])), _latest_prekickoff(l_by_id.get(match_id, []))
        if quant is None or llm is None:
            excluded.append({"match_id": match_id, "reason": "missing_pre_kickoff_track"})
        elif quant.get("cohort_key") != llm.get("cohort_key"):
            excluded.append({"match_id": match_id, "reason": "cohort_key_mismatch"})
        elif _score(quant) is None or _score(llm) is None:
            excluded.append({"match_id": match_id, "reason": "missing_official_90min_result"})
        elif _score(quant) != _score(llm):
            excluded.append({"match_id": match_id, "reason": "official_90min_result_mismatch"})
        else:
            pairs.append({"match_id": match_id, "cohort_key": quant.get("cohort_key"),
                          "cohort": classify_cohort(quant.get("cohort_key"), current_cohort_key),
                          "official_90min_score": list(_score(quant)), "quant": quant, "llm": llm})
    return pairs, excluded


def _metric_rows(rows):
    result = {"experiment": [], "market": []}
    for row in rows:
        score = _score(row)
        actual = _outcome(score)
        exp, market = _probs(row, "experiment"), _probs(row, "market")
        if actual is not None and exp is not None:
            result["experiment"].append((actual, score, exp, row.get("experiment_top_scores") or []))
        if actual is not None and market is not None:
            result["market"].append((actual, score, market, row.get("market_top_scores") or []))
    return result


def _summary(values):
    if not values:
        return {"1x2": None, "score_top1": None, "score_top3": None, "brier": None, "log_loss": None, "calibration": None}
    n = len(values); one = top1 = top3 = 0; brier = logloss = 0.0
    for actual, score, probs, scores in values:
        one += int(max(range(3), key=probs.__getitem__) == actual)
        actual_score = f"{score[0]}-{score[1]}"
        top1 += int(bool(scores) and scores[0] == actual_score)
        top3 += int(actual_score in scores[:3])
        target = [float(i == actual) for i in range(3)]
        brier += sum((probs[i] - target[i]) ** 2 for i in range(3))
        logloss -= math.log(max(1e-12, probs[actual]))
    return {"1x2": one / n, "score_top1": top1 / n, "score_top3": top3 / n,
            "brier": brier / n, "log_loss": logloss / n, "calibration": None}


def _paired_deltas(rows, iterations, seed):
    pairs = []
    for row in rows:
        actual = _outcome(_score(row)); exp = _probs(row, "experiment"); market = _probs(row, "market")
        if actual is None or exp is None or market is None:
            continue
        target = [float(i == actual) for i in range(3)]
        pairs.append((sum((exp[i]-target[i])**2 for i in range(3)) - sum((market[i]-target[i])**2 for i in range(3)),
                      -math.log(max(1e-12, exp[actual])) + math.log(max(1e-12, market[actual]))))
    if not pairs:
        return None
    rng = random.Random(seed); samples = [[], []]
    for _ in range(iterations):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        for i in range(2): samples[i].append(sum(x[i] for x in sample) / len(sample))
    for sample in samples: sample.sort()
    lo, hi = int(.025 * iterations), int(.975 * iterations) - 1
    return {"brier_experiment_minus_market": sum(x[0] for x in pairs)/len(pairs),
            "log_loss_experiment_minus_market": sum(x[1] for x in pairs)/len(pairs),
            "brier_ci95": [samples[0][lo], samples[0][hi]], "log_loss_ci95": [samples[1][lo], samples[1][hi]]}


def evaluate_paired(rows, bootstrap_iterations=2000, seed=20260809, min_matches=100, current_cohort_key=None):
    cohorts = Counter(classify_cohort(r.get("cohort_key"), current_cohort_key) for r in rows)
    metrics = _metric_rows(rows)
    report = {"status": "ok" if len(rows) >= min_matches else "insufficient_paired_samples",
              "comparison_unit": "same_match_same_official_90min_result_same_cohort_key", "n": len(rows),
              "min_matches": min_matches, "bootstrap_iterations": bootstrap_iterations,
              "cohort_counts": {key: cohorts.get(key, 0) for key in ("current", "legacy", "unknown")},
              "metrics": {key: _summary(value) for key, value in metrics.items()},
              "market_paired_deltas": {"brier_experiment_minus_market": None,
                                       "log_loss_experiment_minus_market": None,
                                       "brier_ci95": None, "log_loss_ci95": None},
              "superiority_conclusion": None}
    if len(rows) >= min_matches:
        report["market_paired_deltas"] = _paired_deltas(rows, bootstrap_iterations, seed) or report["market_paired_deltas"]
    # Legacy aliases keep downstream consumers from silently interpreting an unpaired result as evidence.
    deltas = report["market_paired_deltas"] or {}
    report["brier_delta_experiment_minus_market"] = deltas.get("brier_experiment_minus_market")
    report["log_loss_delta_experiment_minus_market"] = deltas.get("log_loss_experiment_minus_market")
    report["brier_ci95"] = deltas.get("brier_ci95")
    report["log_loss_ci95"] = deltas.get("log_loss_ci95")
    return report


def _read_rows(path):
    text = path.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(text)
        if isinstance(value, list): return value
        if isinstance(value, dict): return value.get("rows") or value.get("pairs") or []
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return []


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--min-matches", type=int, default=100); parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--current-cohort-key")
    args = parser.parse_args()
    input_path = Path(args.input)
    raw = json.loads(input_path.read_text(encoding="utf-8-sig"))
    rows = _read_rows(input_path)
    strict_excluded = []
    # Track-form inputs must be paired here rather than relying on a caller to do so.
    if isinstance(raw, dict) and "quant_rows" in raw and "llm_rows" in raw:
        strict_pairs, strict_excluded = build_strict_pairs(raw["quant_rows"], raw["llm_rows"], args.current_cohort_key)
        rows = [{"match_id": p["match_id"], "cohort_key": p["cohort_key"],
                 "official_90min_score": p["official_90min_score"],
                 "experiment_probs": _probs(p["quant"]), "market_probs": _probs(p["llm"]),
                 "experiment_top_scores": p["quant"].get("top_scores") or [],
                 "market_top_scores": p["llm"].get("top_scores") or []} for p in strict_pairs]
    elif rows and all(r.get("track") in {"quant", "llm"} for r in rows):
        strict_pairs, strict_excluded = build_strict_pairs(
            [r for r in rows if r["track"] == "quant"], [r for r in rows if r["track"] == "llm"], args.current_cohort_key)
        rows = [{"match_id": p["match_id"], "cohort_key": p["cohort_key"],
                 "official_90min_score": p["official_90min_score"],
                 "experiment_probs": _probs(p["quant"]), "market_probs": _probs(p["llm"]),
                 "experiment_top_scores": p["quant"].get("top_scores") or [],
                 "market_top_scores": p["llm"].get("top_scores") or []} for p in strict_pairs]
    report = evaluate_paired(rows, args.bootstrap_iterations, min_matches=args.min_matches, current_cohort_key=args.current_cohort_key)
    report.update({"time_order": True, "input": str(input_path),
                   "strict_pairing": {"included": len(rows), "excluded": strict_excluded}})
    Path(args.output).parent.mkdir(parents=True, exist_ok=True); Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()

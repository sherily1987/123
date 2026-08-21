#!/usr/bin/env python3
"""Compare the validated Big5 score candidate in a research-only shadow.

The only candidate used here is the 2026-08-16 Big5 chronological holdout
winner (lambda3=0.15, T=1.1).  It is never applied to production output, and
the report refuses admission until it has sufficient same-family registered
samples.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


GRID_MAX = 12
MIN_ADMISSION_N = 120
BIG5 = {"英超", "西甲", "德甲", "意甲", "法甲", "premier league", "la liga", "bundesliga", "serie a", "ligue 1"}
# The production engine exposes two distinct score distributions:
# ``score_matrix`` is the raw BP matrix, while ``top_scores`` is ranked after
# a temperature transform.  Do not score the raw matrix with the Top-score
# temperature: that would fabricate a probability change that production does
# not make.
DEFAULT_LAMBDA3 = 0.05
DEFAULT_TOP_TEMPERATURE = 1.30
BIG5_CANDIDATE_LAMBDA3 = 0.15
BIG5_CANDIDATE_TOP_TEMPERATURE = 1.10


def bivariate_matrix(lambda_home: float, lambda_away: float, *, lambda3: float,
                     temperature: float) -> dict[str, float]:
    """Generate the truncated, normalized BP score matrix used for shadow only."""
    if min(lambda_home, lambda_away, lambda3) < 0 or temperature <= 0:
        raise ValueError("invalid score parameters")
    raw: dict[str, float] = {}
    for home in range(GRID_MAX + 1):
        for away in range(GRID_MAX + 1):
            probability = 0.0
            for shared in range(min(home, away) + 1):
                probability += (
                    lambda_home ** (home - shared)
                    * lambda_away ** (away - shared)
                    * lambda3 ** shared
                    / (math.factorial(home - shared) * math.factorial(away - shared) * math.factorial(shared))
                )
            raw[f"{home}-{away}"] = math.exp(-(lambda_home + lambda_away + lambda3)) * probability
    sharpened = {score: max(probability, 1e-15) ** (1.0 / temperature)
                 for score, probability in raw.items()}
    total = sum(sharpened.values())
    return {score: probability / total for score, probability in sharpened.items()}


def _metrics(rows: Iterable[Mapping[str, Any]], params: Mapping[str, float]) -> dict[str, float | int | None]:
    log_losses: list[float] = []
    top1 = top3 = 0
    for row in rows:
        xg = row["xg"]
        matrix = bivariate_matrix(float(xg[0]), float(xg[1]), **params)
        actual = str(row["actual_score"])
        if actual not in matrix:
            continue
        log_losses.append(-math.log(max(matrix[actual], 1e-15)))
        ranked = sorted(matrix, key=matrix.__getitem__, reverse=True)
        top1 += int(actual == ranked[0])
        top3 += int(actual in ranked[:3])
    n = len(log_losses)
    return {"n": n, "score_log_loss": round(sum(log_losses) / n, 6) if n else None,
            "top1_accuracy_pct": round(100 * top1 / n, 2) if n else None,
            "top3_accuracy_pct": round(100 * top3 / n, 2) if n else None}


def _is_big5(league: Any) -> bool:
    return str(league or "").casefold().strip() in BIG5


def compare_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = []
    for row in rows:
        xg = row.get("xg")
        if (not _is_big5(row.get("league")) or not isinstance(xg, (list, tuple)) or len(xg) != 2
                or not isinstance(row.get("actual_score"), str)):
            continue
        try:
            if min(float(xg[0]), float(xg[1])) < 0:
                continue
        except (TypeError, ValueError):
            continue
        eligible.append(row)
    # ``score_matrix`` is exactly the probability object used for full-matrix
    # log loss in fusion_backtest, therefore both sides use T=1.  The separate
    # ``top_scores`` block evaluates the displayed rankings with their real
    # production/candidate temperatures.
    matrix_baseline_params = {"lambda3": DEFAULT_LAMBDA3, "temperature": 1.0}
    matrix_candidate_params = {"lambda3": BIG5_CANDIDATE_LAMBDA3, "temperature": 1.0}
    top_baseline_params = {"lambda3": DEFAULT_LAMBDA3, "temperature": DEFAULT_TOP_TEMPERATURE}
    top_candidate_params = {"lambda3": BIG5_CANDIDATE_LAMBDA3,
                            "temperature": BIG5_CANDIDATE_TOP_TEMPERATURE}
    matrix_baseline = _metrics(eligible, matrix_baseline_params)
    matrix_candidate = _metrics(eligible, matrix_candidate_params)
    top_baseline = _metrics(eligible, top_baseline_params)
    top_candidate = _metrics(eligible, top_candidate_params)
    n = matrix_candidate["n"]
    return {
        "schema": "score-shadow-compare-1.0",
        "research_only": True,
        "production_unchanged": True,
        "source_holdout": "project021/05_交付/score_params_by_league.json: big5 adopt_for_research=true",
        "big5_candidate": {
            "n": n,
            "score_matrix": {
                "baseline": {**matrix_baseline_params, **matrix_baseline},
                "candidate": {**matrix_candidate_params, **matrix_candidate},
                "delta_log_loss_candidate_minus_baseline": (
                    round(matrix_candidate["score_log_loss"] - matrix_baseline["score_log_loss"], 6)
                    if matrix_candidate["score_log_loss"] is not None
                    and matrix_baseline["score_log_loss"] is not None else None),
            },
            "top_scores": {
                "baseline": {**top_baseline_params, **top_baseline},
                "candidate": {**top_candidate_params, **top_candidate},
                "delta_top1_accuracy_pct_candidate_minus_baseline": (
                    round(top_candidate["top1_accuracy_pct"] - top_baseline["top1_accuracy_pct"], 2)
                    if top_candidate["top1_accuracy_pct"] is not None
                    and top_baseline["top1_accuracy_pct"] is not None else None),
                "delta_top3_accuracy_pct_candidate_minus_baseline": (
                    round(top_candidate["top3_accuracy_pct"] - top_baseline["top3_accuracy_pct"], 2)
                    if top_candidate["top3_accuracy_pct"] is not None
                    and top_baseline["top3_accuracy_pct"] is not None else None),
            },
            "admission": "shadow_only_pending_oos" if n >= MIN_ADMISSION_N else "insufficient_n",
            "minimum_admission_n": MIN_ADMISSION_N,
        },
    }


def load_registered_rows(store: str, snapshot_policy: str) -> list[dict[str, Any]]:
    from fusion_backtest import dedupe_snapshot_rows, load_jsonl, resolve_path, select_primary_rows  # type: ignore[import-not-found]

    root = Path(store)
    rows = []
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        match_id = str(rec.get("match_id") or "")
        result_path = root / "results" / f"{match_id}.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            score = result.get("score_90") or {}
            home, away = int(score["home"]), int(score["away"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if result.get("status") != "finished" or result.get("settlement_scope") != "90min":
            continue
        output = rec.get("output") or {}
        core = output.get("core_output") if isinstance(output.get("core_output"), Mapping) else output
        rows.append({
            "match_id": match_id, "created_at": rec.get("created_at") or "",
            "snapshot_type": rec.get("snapshot_type"),
            "league": (rec.get("match") or {}).get("competition") or (rec.get("match") or {}).get("stage"),
            "xg": core.get("xg"), "actual_score": f"{home}-{away}",
        })
    deduped, _ = dedupe_snapshot_rows(rows)
    return select_primary_rows(deduped, snapshot_policy)


def main() -> None:
    from runtime_paths import backtest_store  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser(description="Big5 比分参数影子对照，不修改生产概率")
    parser.add_argument("--store", default=str(backtest_store()))
    parser.add_argument("--snapshot-policy", choices=("latest_before_kickoff", "prematch", "closing"),
                        default="latest_before_kickoff")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = load_registered_rows(args.store, args.snapshot_policy)
    report = compare_rows(rows)
    report.update({"store": args.store, "snapshot_policy": args.snapshot_policy,
                   "registered_primary_rows": len(rows)})
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(target), "big5_candidate": report["big5_candidate"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build an auditable single-model calibration sample from job tickets.

The filename is retained for backward compatibility. Samples are always
filtered by the explicit model id, so K3 and DeepSeek V4 Flash cannot mix.

The builder deliberately does not infer results from external aggregates.  A
row is scored only when its job has a pre-kickoff timestamp and a verified
Sporttery 90-minute result in the shared results store (or an equivalent
settlement embedded in the ticket).  Unusable rows remain visible in the
quality summary with an explicit reason.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL_ID = "moonshot/kimi-k3"
RESULT_LABELS = {0: "H", 1: "D", 2: "A"}


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _mid(value: Any) -> str:
    text = str(value or "")
    return text if text.startswith("sporttery-") else f"sporttery-{text}" if text else ""


def _result_label(home: int, away: int) -> str:
    return RESULT_LABELS[0 if home > away else 1 if home == away else 2]


def _load_results(results_root: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not results_root.is_dir():
        return found
    for path in results_root.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        score = item.get("score_90") or {}
        if item.get("status") not in {"finished", "settled", "FT"}:
            continue
        if score.get("home") is None or score.get("away") is None:
            continue
        found[_mid(item.get("match_id") or path.stem)] = item
    return found


def _llm_output(job: dict[str, Any]) -> dict[str, Any] | None:
    rows = [row for row in (job.get("outputs") or [])
            if isinstance(row, dict) and row.get("track") == "llm"]
    return rows[-1] if rows else None


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    direction_rows = [row for row in rows if row.get("direction") in {"H", "D", "A"}]
    probability_rows = []
    probability_source_counts = {
        "production_llm_probs": 0,
        "research_raw_llm_probs": 0,
    }
    for row in rows:
        production_values = row.get("llm_probs_1x2")
        raw_values = row.get("llm_raw_probs_1x2")
        # A rejected/abstained prediction may still contain a normalized raw
        # self-report.  It is research-only and must never be promoted to the
        # production ``llm_probs_1x2`` field.
        values = production_values or raw_values
        if production_values:
            probability_source_counts["production_llm_probs"] += 1
        elif raw_values:
            probability_source_counts["research_raw_llm_probs"] += 1
        if not isinstance(values, list) or len(values) != 3:
            continue
        try:
            probs = [float(value) / 100.0 for value in values]
        except (TypeError, ValueError):
            continue
        if any(value < 0 for value in probs) or sum(probs) <= 0:
            continue
        total = sum(probs)
        probability_rows.append((row, [value / total for value in probs]))
    brier = []
    logloss = []
    index = {"H": 0, "D": 1, "A": 2}
    for row, probs in probability_rows:
        actual = index.get(row.get("actual_direction"))
        if actual is None:
            continue
        brier.append(sum((prob - (1.0 if i == actual else 0.0)) ** 2
                         for i, prob in enumerate(probs)))
        logloss.append(-math.log(max(probs[actual], 1e-15)))
    ou_rows = [row for row in rows if row.get("llm_ou25") in {"大", "大2.5", "小", "小2.5"}]
    ou_correct = sum(
        (row["llm_ou25"] in {"大", "大2.5"}) == (int(row["total_goals"]) >= 3)
        for row in ou_rows
    )
    return {
        "direction_n": len(direction_rows),
        "direction_accuracy_pct": round(
            sum(row.get("direction_correct") is True for row in direction_rows)
            / len(direction_rows) * 100.0, 2) if direction_rows else None,
        "probability_n": len(probability_rows),
        "probability_source_counts": probability_source_counts,
        "brier": round(sum(brier) / len(brier), 8) if brier else None,
        "log_loss": round(sum(logloss) / len(logloss), 8) if logloss else None,
        "score_n": len(rows),
        "score_exact_accuracy_pct": round(
            sum(row.get("score_exact") is True for row in rows) / len(rows) * 100.0, 2)
        if rows else None,
        "ou25_n": len(ou_rows),
        "ou25_accuracy_pct": round(ou_correct / len(ou_rows) * 100.0, 2) if ou_rows else None,
    }


def build_sample(
    jobs_root: Path,
    results_root: Path,
    model_id: str = MODEL_ID,
) -> dict[str, Any]:
    results = _load_results(results_root)
    rows: list[dict[str, Any]] = []
    reasons = Counter()
    llm_count = 0
    for path in sorted(jobs_root.glob("**/sporttery-*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            reasons["invalid_job_json"] += 1
            continue
        output = _llm_output(job)
        if output is None:
            continue
        llm_count += 1
        recorded_model = output.get("model_id") or MODEL_ID
        if recorded_model != model_id:
            reasons["non_target_model"] += 1
            continue
        identity = job.get("identity") or {}
        match_id = _mid(identity.get("match_id") or path.stem.removesuffix(".json"))
        kickoff = _time(identity.get("kickoff"))
        as_of = _time(output.get("llm_prediction_as_of")) or _time(
            (job.get("input") or {}).get("prediction_as_of")
        )
        if not kickoff or not as_of:
            reasons["missing_prediction_or_kickoff_time"] += 1
            continue
        if as_of >= kickoff:
            reasons["post_kickoff_prediction"] += 1
            continue
        result = results.get(match_id)
        if result is None:
            embedded = job.get("settlement") or {}
            score = embedded.get("score_90") or {}
            result = embedded if score.get("home") is not None and score.get("away") is not None else None
        if result is None:
            reasons["pending_or_missing_official_result"] += 1
            continue
        score = result.get("score_90") or {}
        home, away = int(score["home"]), int(score["away"])
        direction = str(output.get("direction") or "")
        direction_code = direction if direction in {"H", "D", "A"} else {"主胜": "H", "平局": "D", "客胜": "A"}.get(direction)
        rows.append({
            "model": model_id,
            "match_id": match_id,
            "prediction_as_of": as_of.isoformat(),
            "kickoff": kickoff.isoformat(),
            "home": identity.get("home"),
            "away": identity.get("away"),
            "competition": identity.get("competition"),
            "direction": direction_code,
            "alt_direction": output.get("alt_direction"),
            "vote_share": (output.get("strength") or {}).get("value"),
            "llm_probs_1x2": output.get("llm_probs_1x2"),
            "llm_raw_probs_1x2": output.get("llm_raw_probs_1x2"),
            "llm_confidence": output.get("llm_confidence"),
            "llm_decision": output.get("llm_decision"),
            "llm_top_scores": output.get("llm_top_scores") or [],
            "llm_ou25": output.get("llm_ou25"),
            "llm_hafu": output.get("llm_hafu"),
            "llm_raw_top_scores": output.get("llm_raw_top_scores") or [],
            "llm_raw_ou25": output.get("llm_raw_ou25"),
            "llm_raw_hafu": output.get("llm_raw_hafu"),
            "score_prediction": output.get("score"),
            "ou25_prediction": output.get("ou25"),
            "hafu_prediction": output.get("hafu"),
            "evidence_gap": bool(output.get("evidence_gap")),
            "action": output.get("action"),
            "score_90": {"home": home, "away": away},
            "actual_direction": _result_label(home, away),
            "direction_correct": direction_code == _result_label(home, away),
            "score_exact": output.get("score") == f"{home}-{away}",
            "total_goals": home + away,
            "settlement_source": (result.get("source") or {}).get("name") or result.get("settlement_evidence"),
        })
    return {
        "schema": "llm-calibration-sample-1.0",
        "model": model_id,
        "research_only": True,
        "production_change_allowed": False,
        "jobs_scanned": sum(1 for _ in jobs_root.glob("**/sporttery-*.json")) if jobs_root.is_dir() else 0,
        "llm_rows": llm_count,
        "eligible_settled_rows": len(rows),
        "excluded_by_reason": dict(sorted(reasons.items())),
        "metrics": _metrics(rows),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default=MODEL_ID,
                        help="只纳入该模型；默认保留历史 K3 校准口径")
    args = parser.parse_args()
    report = build_sample(args.jobs_root, args.results_root, args.model_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

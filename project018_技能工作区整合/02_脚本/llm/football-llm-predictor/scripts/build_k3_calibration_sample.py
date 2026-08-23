#!/usr/bin/env python3
"""Build an auditable K3-only calibration sample from job tickets.

The builder deliberately does not infer results from external aggregates.  A
row is scored only when its job has a pre-kickoff timestamp and a verified
Sporttery 90-minute result in the shared results store (or an equivalent
settlement embedded in the ticket).  Unusable rows remain visible in the
quality summary with an explicit reason.
"""
from __future__ import annotations

import argparse
import json
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


def build_sample(jobs_root: Path, results_root: Path) -> dict[str, Any]:
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
        identity = job.get("identity") or {}
        match_id = _mid(identity.get("match_id") or path.stem.removesuffix(".json"))
        kickoff = _time(identity.get("kickoff"))
        as_of = _time((job.get("input") or {}).get("prediction_as_of"))
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
            "model": MODEL_ID,
            "match_id": match_id,
            "prediction_as_of": as_of.isoformat(),
            "kickoff": kickoff.isoformat(),
            "home": identity.get("home"),
            "away": identity.get("away"),
            "competition": identity.get("competition"),
            "direction": direction_code,
            "alt_direction": output.get("alt_direction"),
            "vote_share": (output.get("strength") or {}).get("value"),
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
        "schema": "k3-calibration-sample-1.0",
        "model": MODEL_ID,
        "research_only": True,
        "production_change_allowed": False,
        "jobs_scanned": sum(1 for _ in jobs_root.glob("**/sporttery-*.json")) if jobs_root.is_dir() else 0,
        "llm_rows": llm_count,
        "eligible_settled_rows": len(rows),
        "excluded_by_reason": dict(sorted(reasons.items())),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_sample(args.jobs_root, args.results_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

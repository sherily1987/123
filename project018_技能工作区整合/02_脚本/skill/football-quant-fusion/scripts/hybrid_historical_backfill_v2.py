#!/usr/bin/env python3
"""Current-signature, no-leakage historical hybrid replay under a v2 audit contract."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from historical_independent_market_replay import match_to_pair
from hybrid_admission import review_protocol
from hybrid_contract import (
    HISTORICAL_HYBRID_REPLAY_CURRENT,
    load_active_cohort_lock,
    stamp_success_sidecar,
    validate_historical_replay_sidecar,
)
from hybrid_evaluation import _actual_index, _brier, _logloss, _probabilities
from job_ticket import hybrid_from_fusion_output
from production_router import BIG5, GOALS_ONLY, _event_in_league, load_event_rows, route_match
from fusion_predict_core import load_core, predict_one


def build_replay_row(
        core, version: dict, job: dict, result: dict, cohort_lock: dict,
        *, replay_generated_at: datetime,
        predict_fn: Callable[..., dict] = predict_one) -> dict:
    input_obj = dict(job.get("input") or {})
    prior = (((job.get("research") or {}).get("hybrid") or {}).get("lambda_prior") or {})
    routing = (((job.get("research") or {}).get("hybrid") or {}).get("routing_audit") or {})
    as_of = input_obj.get("prediction_as_of")
    pool_meta = {
        field: {
            "reliability": 100,
            "freshness": 100,
            "source": "official_sporttery_historical_prematch_snapshot",
            "collected_at": as_of,
            "prediction_as_of": as_of,
            "observed_at": as_of,
        }
        for field in ("odds", "hhad", "ttg", "hafu", "crs")
        if input_obj.get(field) is not None
    }
    model_input = {
        **input_obj,
        "mode": "hybrid",
        "research_only": True,
        "lambda_prior": prior,
        "context_confirmed": True,
        "sporttery_meta": {"match_id": (job.get("identity") or {}).get("match_id")},
        "field_meta": {**pool_meta, "production_router": routing},
    }
    try:
        output = predict_fn(core, version, model_input)
    except Exception as exc:  # one corrupt historical row must not abort the audit batch
        return {"status": "error", "match_id": (job.get("identity") or {}).get("match_id"),
                "errors": [f"HYBRID_REPLAY_PREDICT_FAILED:{type(exc).__name__}:{exc}"]}
    blob = hybrid_from_fusion_output(output, prior=prior)
    blob.update({
        "research_only": True,
        "status": output.get("fusion_status"),
        "mode": output.get("mode"),
        "market_derived": False,
        "execution_type": "historical_replay",
        "historical_replay": True,
        "routing_audit": routing,
        "simulation_as_of": input_obj.get("prediction_as_of"),
        "market_input_as_of": input_obj.get("prediction_as_of"),
        "replay_generated_at": replay_generated_at.astimezone(timezone.utc).isoformat(),
    })
    blob = stamp_success_sidecar(blob, output.get("build_identity") or {})
    errors = validate_historical_replay_sidecar(blob, input_obj, cohort_lock)
    if errors:
        return {"status": "error", "match_id": (job.get("identity") or {}).get("match_id"),
                "errors": errors, "hybrid": blob}
    hybrid_probs = _probabilities(blob.get("final_1x2_pct"))
    market_probs = _probabilities(blob.get("market_1x2_pct"))
    actual = _actual_index(result.get("score_90"))
    if hybrid_probs is None or market_probs is None or actual is None:
        return {"status": "error", "match_id": (job.get("identity") or {}).get("match_id"),
                "errors": ["HYBRID_REPLAY_UNSCORABLE"], "hybrid": blob}
    brier_hybrid = _brier(hybrid_probs, actual)
    brier_market = _brier(market_probs, actual)
    logloss_hybrid = _logloss(hybrid_probs, actual)
    logloss_market = _logloss(market_probs, actual)
    return {
        "status": "ok",
        "denominator_id": HISTORICAL_HYBRID_REPLAY_CURRENT,
        "match_id": (job.get("identity") or {}).get("match_id"),
        "kickoff": (job.get("identity") or {}).get("kickoff") or input_obj.get("kickoff"),
        "hybrid": blob,
        "score_90": result.get("score_90"),
        "brier_hybrid": brier_hybrid,
        "brier_market": brier_market,
        "brier_delta_hybrid_minus_market": brier_hybrid - brier_market,
        "logloss_hybrid": logloss_hybrid,
        "logloss_market": logloss_market,
        "logloss_delta_hybrid_minus_market": logloss_hybrid - logloss_market,
    }


def build_report(
        pairs: list[tuple[dict, dict]], core, version: dict, cohort_lock: dict,
        *, predict_fn: Callable[..., dict] = predict_one,
        replay_generated_at: datetime | None = None) -> dict:
    generated_at = replay_generated_at or datetime.now(timezone.utc)
    attempted = [build_replay_row(
        core, version, job, result, cohort_lock,
        replay_generated_at=generated_at, predict_fn=predict_fn,
    ) for job, result in pairs]
    rows = [row for row in attempted if row.get("status") == "ok"]
    excluded = Counter(error for row in attempted if row.get("status") != "ok"
                       for error in row.get("errors", ["UNKNOWN_ERROR"]))
    cohorts = Counter(row["hybrid"]["hybrid_cohort_key"] for row in rows)
    review_rows = [{
        "match_id": row["match_id"], "kickoff": row["kickoff"],
        "brier_delta_hybrid_minus_market": row["brier_delta_hybrid_minus_market"],
        "logloss_delta_hybrid_minus_market": row["logloss_delta_hybrid_minus_market"],
    } for row in rows]
    review = review_protocol(
        review_rows, minimum_n=100, bootstrap_samples=10000, bootstrap_seed=20260826,
        denominator_id=HISTORICAL_HYBRID_REPLAY_CURRENT)
    return {
        "schema_version": "hybrid-historical-replay-2.0",
        "denominator_id": HISTORICAL_HYBRID_REPLAY_CURRENT,
        "research_only": True,
        "production_change_allowed": False,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "cohort_lock": cohort_lock,
        "source_policy": {
            "market_snapshot": "last verified Sporttery snapshot strictly before kickoff",
            "history_cutoff": "strictly before kickoff",
            "weight_tuning_on_evaluation_set": False,
            "execution_time_truth": "replay_generated_at is wall-clock; simulation_as_of is pre-match cutoff",
        },
        "attempted": len(attempted),
        "n": len(rows),
        "excluded": dict(sorted(excluded.items())),
        "error_rows": [row for row in attempted if row.get("status") != "ok"],
        "cohorts": dict(cohorts),
        "rows": rows,
        "review": review,
    }


def historical_pairs(matches: list[dict], understat_rows: list[dict], event_rows: list[dict],
                     *, min_history: int = 5) -> tuple[list[tuple[dict, dict]], dict[str, int]]:
    competitions = {str(match.get("leagueAbbName") or match.get("leagueAllName") or "")
                    for match in matches}
    event_subsets = {
        competition: [row for row in event_rows if _event_in_league(row, GOALS_ONLY[competition])]
        for competition in competitions if competition in GOALS_ONLY and competition not in BIG5
    }
    pairs = []
    excluded = Counter()
    for match in matches:
        competition = str(match.get("leagueAbbName") or match.get("leagueAllName") or "")
        pair, reason = match_to_pair(
            match, understat_rows, event_subsets.get(competition, event_rows),
            route_fn=route_match, min_history=min_history)
        if pair is None:
            excluded[str(reason)] += 1
        else:
            pairs.append(pair)
    return pairs, dict(sorted(excluded.items()))


def reevaluate_report(report: dict) -> dict:
    """Re-run only the frozen decision protocol over persisted replay rows."""
    if report.get("denominator_id") != HISTORICAL_HYBRID_REPLAY_CURRENT:
        raise ValueError("not a current historical hybrid replay report")
    review_rows = [{
        "match_id": row["match_id"], "kickoff": row["kickoff"],
        "brier_delta_hybrid_minus_market": row["brier_delta_hybrid_minus_market"],
        "logloss_delta_hybrid_minus_market": row["logloss_delta_hybrid_minus_market"],
    } for row in report.get("rows", [])]
    repaired = dict(report)
    repaired["review"] = review_protocol(
        review_rows, minimum_n=100, bootstrap_samples=10000, bootstrap_seed=20260826,
        denominator_id=HISTORICAL_HYBRID_REPLAY_CURRENT)
    return repaired


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--understat-store", type=Path)
    parser.add_argument("--events-store", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reevaluate-existing", type=Path)
    parser.add_argument("--min-history", type=int, default=5)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.reevaluate_existing:
        path = args.reevaluate_existing
        report = reevaluate_report(json.loads(path.read_text(encoding="utf-8")))
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        print(json.dumps({"status": "ok", "n": report["n"],
                          "decision": report["review"]["decision"], "output": str(path)},
                         ensure_ascii=False, indent=2))
        return 0
    if not all((args.input, args.understat_store, args.events_store, args.output)):
        parser.error("--input, --understat-store, --events-store and --output are required for replay")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    understat = load_event_rows(args.understat_store)
    events = load_event_rows(args.events_store)
    pairs, source_excluded = historical_pairs(
        source.get("matches") or [], understat, events, min_history=args.min_history)
    if args.limit is not None:
        pairs = pairs[:max(0, args.limit)]
    core, version = load_core()
    report = build_report(pairs, core, version, load_active_cohort_lock())
    report["input"] = str(args.input.resolve())
    report["understat_store"] = str(args.understat_store.resolve())
    report["events_store"] = str(args.events_store.resolve())
    report["source_excluded"] = source_excluded
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok" if not report["excluded"] else "partial",
        "attempted": report["attempted"], "n": report["n"],
        "excluded": report["excluded"], "cohorts": report["cohorts"],
        "decision": report["review"]["decision"], "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0 if report["n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

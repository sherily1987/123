#!/usr/bin/env python3
"""Replay independent pre-match lambdas over Sporttery's historical four-pool sample."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from independent_lambda_market_shadow import evaluate_by_lambda_source, evaluate_settled_pairs
from production_router import BIG5, GOALS_ONLY, _event_in_league, load_event_rows, route_match


HAFU_KEYS = ("hh", "hd", "ha", "dh", "dd", "da", "ah", "ad", "aa")
CRS_OTHER = {"s-1sh": "胜其他", "s-1sd": "平其他", "s-1sa": "负其他"}
CRS_RE = re.compile(r"^s(\d{2})s(\d{2})$")


def _price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 1.0 else None


def _score(value: Any) -> dict[str, int] | None:
    try:
        home, away = str(value).split(":", 1)
        return {"home": int(home), "away": int(away)}
    except (AttributeError, TypeError, ValueError):
        return None


def _market_as_of(closing: dict[str, Any]) -> datetime | None:
    values = []
    for pool in closing.values():
        if not isinstance(pool, dict) or not pool.get("updateDate") or not pool.get("updateTime"):
            continue
        try:
            parsed = datetime.fromisoformat(f'{pool["updateDate"]}T{pool["updateTime"]}+08:00')
        except ValueError:
            continue
        values.append(parsed)
    return max(values) if values else None


def _crs_pool(raw: dict[str, Any]) -> dict[str, float]:
    output = {}
    for key, value in raw.items():
        match = CRS_RE.fullmatch(str(key))
        if match:
            price = _price(value)
            if price is not None:
                output[f"{int(match.group(1))}-{int(match.group(2))}"] = price
    for key, label in CRS_OTHER.items():
        price = _price(raw.get(key))
        if price is not None:
            output[label] = price
    return output


def _input_pools(match: dict[str, Any]) -> dict[str, Any] | None:
    closing = match.get("closing_pre_match") or {}
    had, ttg, hafu, crs = (closing.get(name) or {} for name in ("had", "ttg", "hafu", "crs"))
    had_odds = [_price(had.get(key)) for key in ("h", "d", "a")]
    ttg_odds = [_price(ttg.get(f"s{i}")) for i in range(8)]
    hafu_odds = [_price(hafu.get(key)) for key in HAFU_KEYS]
    crs_odds = _crs_pool(crs)
    if any(value is None for value in had_odds + ttg_odds + hafu_odds):
        return None
    if not all(label in crs_odds for label in CRS_OTHER.values()):
        return None
    return {
        "odds": had_odds,
        "ttg": {"odds": ttg_odds},
        "hafu": {"odds": hafu_odds},
        "crs": crs_odds,
    }


def match_to_pair(
    match: dict[str, Any],
    understat_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    *,
    route_fn: Callable[..., dict[str, Any]] = route_match,
    min_history: int = 5,
) -> tuple[tuple[dict[str, Any], dict[str, Any]] | None, str | None]:
    kickoff_text = str(match.get("kickoff_iso") or "")
    try:
        kickoff = datetime.fromisoformat(kickoff_text.replace("Z", "+00:00"))
    except ValueError:
        return None, "invalid_kickoff"
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    closing = match.get("closing_pre_match") or {}
    as_of = _market_as_of(closing)
    if as_of is None or as_of >= kickoff:
        return None, "unverified_prematch_odds_timestamp"
    pools = _input_pools(match)
    if pools is None:
        return None, "incomplete_corresponding_odds_pools"
    full_score = _score(match.get("sectionsNo999"))
    if full_score is None:
        return None, "missing_verified_full_time_score"

    route_input = {
        "kickoff": kickoff_text,
        "competition": str(match.get("leagueAbbName") or match.get("leagueAllName") or ""),
        "stage": str(match.get("leagueAllName") or match.get("leagueAbbName") or ""),
        "home": str(match.get("homeTeamAbbName") or match.get("homeTeamAllName") or ""),
        "away": str(match.get("awayTeamAbbName") or match.get("awayTeamAllName") or ""),
    }
    routed = route_fn(route_input, understat_rows, event_rows, min_history, True)
    prior = routed.get("lambda_prior") or {}
    routing = (routed.get("field_meta") or {}).get("production_router") or {}
    if prior.get("lambda_home") is None or prior.get("lambda_away") is None:
        return None, "no_independent_lambda"
    history_latest = routing.get("history_latest")
    try:
        history_time = datetime.fromisoformat(str(history_latest).replace("Z", "+00:00"))
    except ValueError:
        return None, "unverified_history_timestamp"
    if history_time.tzinfo is None or history_time >= kickoff:
        return None, "future_or_unverified_history"

    match_id = f'sporttery-{match.get("matchId")}'
    identity = {
        "match_id": match_id,
        "match_num": match.get("matchNumStr"),
        "home": route_input["home"],
        "away": route_input["away"],
        "competition": route_input["competition"],
        "kickoff": kickoff_text,
    }
    job = {
        "identity": identity,
        "input": {
            **route_input,
            **pools,
            "prediction_as_of": as_of.isoformat(),
            "odds_evidence": "official_sporttery_closing_pre_match",
        },
        "research": {"hybrid": {
            "lambda_prior": prior,
            "routing_audit": routing,
            "research_run_at": as_of.isoformat(),
            "historical_replay": True,
        }},
    }
    result = {
        "status": "finished",
        "score_90": full_score,
        "score_ht": _score(match.get("sectionsNo1")),
        "settlement_evidence": "official_sporttery_sections",
    }
    return (job, result), None


def _calibrated_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    home_multiplier: float,
    away_multiplier: float,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    output = []
    for job, result in pairs:
        calibrated = deepcopy(job)
        prior = calibrated["research"]["hybrid"]["lambda_prior"]
        prior["lambda_home"] = max(0.05, min(6.0, float(prior["lambda_home"]) * home_multiplier))
        prior["lambda_away"] = max(0.05, min(6.0, float(prior["lambda_away"]) * away_multiplier))
        prior["calibration"] = {
            "method": "train_period_score_ratio",
            "home_multiplier": home_multiplier,
            "away_multiplier": away_multiplier,
            "same_match_odds_used": False,
        }
        output.append((calibrated, result))
    return output


def chronological_lambda_calibration(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    train_fraction: float = 0.70,
) -> dict[str, Any]:
    """Fit two score-only multipliers on early dates and evaluate later dates."""
    ordered = sorted(
        pairs,
        key=lambda pair: str((pair[0].get("identity") or {}).get("kickoff") or ""),
    )
    days = sorted({str((job.get("identity") or {}).get("kickoff") or "")[:10] for job, _ in ordered})
    if len(days) < 2:
        return {
            "fit_policy": "score_only_train_period_no_same_match_odds",
            "train_n": 0,
            "test_n": 0,
            "lambda_multipliers": None,
            "decision": "hold",
            "reason": "insufficient_date_groups",
        }
    split = max(1, min(len(days) - 1, int(len(days) * train_fraction)))
    test_from = days[split]
    train = [pair for pair in ordered if str((pair[0].get("identity") or {}).get("kickoff") or "")[:10] < test_from]
    test = [pair for pair in ordered if str((pair[0].get("identity") or {}).get("kickoff") or "")[:10] >= test_from]

    raw_home = sum(float(job["research"]["hybrid"]["lambda_prior"]["lambda_home"]) for job, _ in train)
    raw_away = sum(float(job["research"]["hybrid"]["lambda_prior"]["lambda_away"]) for job, _ in train)
    actual_home = sum(int(result["score_90"]["home"]) for _, result in train)
    actual_away = sum(int(result["score_90"]["away"]) for _, result in train)
    if raw_home <= 0 or raw_away <= 0:
        return {
            "fit_policy": "score_only_train_period_no_same_match_odds",
            "train_n": len(train),
            "test_n": len(test),
            "lambda_multipliers": None,
            "decision": "hold",
            "reason": "invalid_train_lambda_mass",
        }
    home_multiplier = max(0.5, min(2.0, actual_home / raw_home))
    away_multiplier = max(0.5, min(2.0, actual_away / raw_away))
    calibrated_test = _calibrated_pairs(test, home_multiplier, away_multiplier)
    return {
        "schema": "chronological-lambda-calibration-1.0",
        "fit_policy": "score_only_train_period_no_same_match_odds",
        "split": "date_group_early_train_late_test",
        "test_from": test_from,
        "train_n": len(train),
        "test_n": len(test),
        "lambda_multipliers": {
            "home": round(home_multiplier, 8),
            "away": round(away_multiplier, 8),
        },
        "raw_test_evaluation": evaluate_settled_pairs(test),
        "calibrated_test_evaluation": evaluate_settled_pairs(calibrated_test),
        "decision": "hold",
        "reason": "market-level paired-CI and betting-policy validation still required",
    }


def build_report(
    matches: list[dict[str, Any]],
    understat_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    *,
    route_fn: Callable[..., dict[str, Any]] = route_match,
    min_history: int = 5,
) -> dict[str, Any]:
    competitions = {
        str(match.get("leagueAbbName") or match.get("leagueAllName") or "")
        for match in matches
    }
    event_subsets = {
        competition: [row for row in event_rows if _event_in_league(row, GOALS_ONLY[competition])]
        for competition in competitions
        if route_fn is route_match and competition in GOALS_ONLY and competition not in BIG5
    }
    pairs = []
    excluded = Counter()
    audit_rows = []
    for match in matches:
        competition = str(match.get("leagueAbbName") or match.get("leagueAllName") or "")
        routed_events = event_subsets.get(competition, event_rows)
        pair, reason = match_to_pair(
            match,
            understat_rows,
            routed_events,
            route_fn=route_fn,
            min_history=min_history,
        )
        if pair is None:
            excluded[str(reason)] += 1
            continue
        pairs.append(pair)
        job, _ = pair
        prior = job["research"]["hybrid"]["lambda_prior"]
        audit_rows.append({
            "match_id": job["identity"]["match_id"],
            "kickoff": job["identity"]["kickoff"],
            "competition": job["identity"]["competition"],
            "lambda_source": prior.get("source"),
            "lambda_home": prior.get("lambda_home"),
            "lambda_away": prior.get("lambda_away"),
            "sample_legs": prior.get("sample_legs"),
        })
    return {
        "schema": "historical-independent-four-market-replay-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_change_allowed": False,
        "source_policy": {
            "probability_input": "timestamped team history strictly before kickoff",
            "same_match_odds_used_as_probability_input": False,
            "same_match_odds_usage": "official corresponding-pool price and market baseline only",
            "settlement": "official Sporttery 90-minute and half-time sections",
        },
        "coverage": {
            "source_matches": len(matches),
            "understat_rows": len(understat_rows),
            "event_rows": len(event_rows),
            "independent_lambda_pairs": len(pairs),
            "excluded_by_reason": dict(sorted(excluded.items())),
        },
        "evaluation": evaluate_settled_pairs(pairs),
        "by_lambda_source": evaluate_by_lambda_source(pairs),
        "chronological_lambda_calibration": chronological_lambda_calibration(pairs),
        "chronological_lambda_calibration_by_source": {
            source: chronological_lambda_calibration([
                pair for pair in pairs
                if pair[0]["research"]["hybrid"]["lambda_prior"].get("source") == source
            ])
            for source in sorted({
                str(pair[0]["research"]["hybrid"]["lambda_prior"].get("source") or "unknown")
                for pair in pairs
            })
        },
        "audit_rows": audit_rows,
        "admission": {
            "decision": "hold",
            "reason": "requires chronological calibration and bet-policy validation after coverage audit",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--understat-store", required=True, type=Path)
    parser.add_argument("--events-store", required=True, type=Path)
    parser.add_argument("--min-history", type=int, default=5)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    understat_rows = load_event_rows(args.understat_store)
    event_rows = load_event_rows(args.events_store)
    report = build_report(
        source.get("matches") or [], understat_rows, event_rows, min_history=args.min_history
    )
    report["input"] = str(args.input.resolve())
    report["understat_store"] = str(args.understat_store.resolve())
    report["events_store"] = str(args.events_store.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

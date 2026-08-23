#!/usr/bin/env python3
"""Pair walk-forward Dixon-Coles probabilities with official Sporttery pools."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from historical_independent_market_replay import match_to_pair
from independent_lambda_market_shadow import evaluate_by_lambda_source, evaluate_settled_pairs
from production_router import _same_team
from runtime_paths import core_scripts_dir


LEAGUES = {
    "英超": {"id": 152, "slug": "premier_league", "half_life": 120.0},
    "西甲": {"id": 302, "slug": "la_liga", "half_life": 500.0},
    "意甲": {"id": 207, "slug": "serie_a", "half_life": 500.0},
    "德甲": {"id": 175, "slug": "bundesliga", "half_life": 750.0},
    "法甲": {"id": 168, "slug": "ligue_1", "half_life": 365.0},
}

DC_REPLAY_ALIASES = {
    "布伦特": {"Brentford"},
    "奥维耶多": {"Oviedo", "R. Oviedo"},
    "毕尔巴鄂": {"Athletic", "Athletic Bilbao", "Ath Bilbao"},
    "帕尔马": {"Parma"},
    "不来梅": {"Bremen", "Werder Bremen"},
    "斯图加特": {"Stuttgart"},
    "沃夫斯堡": {"Wolfsburg"},
    "海登海姆": {"Heidenheim"},
    "莱红牛": {"Leipzig", "RB Leipzig"},
    "门兴": {"B. Monchengladbach"},
    "巴黎圣曼": {"PSG"},
}


def canonical_team(available: set[str] | dict[str, set[str]], target: str) -> str | None:
    research_aliases = DC_REPLAY_ALIASES.get(target, set())
    def matches_target(name: str) -> bool:
        return _same_team(name, target) or name in research_aliases
    if isinstance(available, dict):
        matches = sorted(
            team_id for team_id, names in available.items()
            if any(matches_target(name) for name in names)
        )
    else:
        matches = sorted(team for team in available if matches_target(team))
    return matches[0] if len(matches) == 1 else None


def predict_with_fallback(
    model: dict[str, Any],
    home: str,
    away: str,
    team_index_fn: Callable[[dict[str, Any]], dict[str, int]],
) -> dict[str, Any]:
    index = team_index_fn(model)
    home_index, away_index = index.get(home), index.get(away)
    fallback = model.get("fallback")
    if (home_index is None or away_index is None) and not fallback:
        return {"status": "UNFITTED_TEAM"}
    attack = lambda idx: float(fallback["alpha"]) if idx is None else float(model["alpha"][idx])
    defence = lambda idx: float(fallback["beta"]) if idx is None else float(model["beta"][idx])
    return {
        "status": "VALID",
        "lambda_home": math.exp(float(model["home_adv"]) + attack(home_index) + defence(away_index)),
        "lambda_away": math.exp(attack(away_index) + defence(home_index)),
        "fallback_used": home_index is None or away_index is None,
    }


def replay_league_pairs(
    sporttery_matches: list[dict[str, Any]],
    training_matches: list[dict[str, Any]],
    *,
    half_life: float,
    min_train: int = 200,
    refit_days: int = 30,
    fit_fn: Callable[..., dict[str, Any]],
    predict_fn: Callable[..., dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], dict[str, int]]:
    targets = sorted(sporttery_matches, key=lambda row: str(row.get("kickoff_iso") or ""))
    if not targets:
        return [], {}
    target_days = [datetime.fromisoformat(str(row["kickoff_iso"]).replace("Z", "+00:00")).date().toordinal() for row in targets]
    available: dict[str, set[str]] = {}
    for row in training_matches:
        for side in ("home", "away"):
            team_id = str(row.get(side) or "")
            if not team_id:
                continue
            display = str(row.get(f"{side}_name") or team_id)
            available.setdefault(team_id, set()).add(display)
    pairs = []
    excluded: Counter[str] = Counter()
    point = min(target_days)
    end = max(target_days) + 1
    while point < end:
        nxt = point + refit_days
        chunk = [row for row, day_number in zip(targets, target_days) if point <= day_number < nxt]
        train = [row for row in training_matches if int(row["day"]) < point]
        if len(train) < min_train:
            excluded["insufficient_walk_forward_train"] += len(chunk)
            point = nxt
            continue
        model = fit_fn(train, half_life)
        history_latest = date.fromordinal(max(int(row["day"]) for row in train)).isoformat() + "T23:59:59+00:00"
        for match in chunk:
            home_target = str(match.get("homeTeamAbbName") or match.get("homeTeamAllName") or "")
            away_target = str(match.get("awayTeamAbbName") or match.get("awayTeamAllName") or "")
            resolved_home = canonical_team(available, home_target)
            resolved_away = canonical_team(available, away_target)
            unmatched = home_target if resolved_home is None else (away_target if resolved_away is None else None)
            if unmatched is not None:
                excluded[f"unmatched_team:{unmatched}"] += 1
                continue

            def route_fn(route_input, understat, events, min_history, enable_experimental):
                prediction = predict_fn(model, resolved_home, resolved_away)
                if prediction.get("status") != "VALID":
                    return {**route_input, "field_meta": {"production_router": {"fallback_reason": prediction.get("status")}}}
                prior = {
                    "lambda_home": float(prediction["lambda_home"]),
                    "lambda_away": float(prediction["lambda_away"]),
                    "source": "dixon_coles_walk_forward",
                    "sample_legs": len(train),
                    "team_sample_sizes": {"home": None, "away": None},
                    "half_life_days": half_life,
                    "refit_days": refit_days,
                }
                return {
                    **route_input,
                    "lambda_prior": prior,
                    "field_meta": {"production_router": {
                        "route": "dixon_coles_walk_forward",
                        "no_future_leakage": True,
                        "history_latest": history_latest,
                        "sample_legs": len(train),
                    }},
                }

            pair, reason = match_to_pair(match, [], [], route_fn=route_fn, min_history=0)
            if pair is None:
                excluded[str(reason)] += 1
            else:
                pairs.append(pair)
        point = nxt
    return pairs, dict(sorted(excluded.items()))


def _load_module(path: Path):
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location("dc_sporttery_team_strength", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def competition_reports(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    competitions = sorted({
        str((job.get("identity") or {}).get("competition") or "unknown")
        for job, _ in pairs
    })
    output = {}
    for competition in competitions:
        subset = [
            pair for pair in pairs
            if str((pair[0].get("identity") or {}).get("competition") or "unknown") == competition
        ]
        source_report = evaluate_by_lambda_source(subset).get("dixon_coles_walk_forward") or {}
        output[competition] = {
            "n": len(subset),
            "evaluation": evaluate_settled_pairs(subset),
            "market_weight_scan": source_report.get("weight_scan"),
            "bet_policy_scans": source_report.get("bet_policy_scans"),
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sporttery-input", required=True, type=Path)
    parser.add_argument("--training-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-train", type=int, default=200)
    args = parser.parse_args()
    strength = _load_module(core_scripts_dir() / "team_strength.py")
    sporttery_source = json.loads(args.sporttery_input.read_text(encoding="utf-8-sig"))
    all_sporttery = sporttery_source.get("matches") or []
    pairs = []
    coverage = {}
    for competition, config in LEAGUES.items():
        source_path = args.training_root / f'{config["slug"]}_events_provider_market.jsonl'
        training = strength.load_matches(source_path, league_id=config["id"], require_odds=False)
        targets = [row for row in all_sporttery if row.get("leagueAbbName") == competition]
        league_pairs, excluded = replay_league_pairs(
            targets,
            training,
            half_life=config["half_life"],
            min_train=args.min_train,
            fit_fn=lambda rows, half_life: strength.attach_fallback(
                strength.fit_model(rows, half_life=half_life),
                strength.estimate_newcomer_prior(rows),
            ),
            predict_fn=lambda model, home, away: predict_with_fallback(
                model, home, away, strength.team_index
            ),
        )
        pairs.extend(league_pairs)
        coverage[competition] = {
            "sporttery_matches": len(targets),
            "training_matches": len(training),
            "paired": len(league_pairs),
            "excluded_by_reason": excluded,
            "half_life_days": config["half_life"],
        }
    report = {
        "schema": "dixon-coles-sporttery-walk-forward-replay-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_change_allowed": False,
        "protocol": {
            "refit_days": 30,
            "history_filter": "training day strictly before refit window",
            "probability_input": "Dixon-Coles team attack/defence history",
            "same_match_odds_used_as_probability_input": False,
            "same_match_odds_usage": "Sporttery corresponding-pool baseline and price only",
        },
        "coverage": coverage,
        "paired_total": len(pairs),
        "evaluation": evaluate_settled_pairs(pairs),
        "by_lambda_source": evaluate_by_lambda_source(pairs),
        "by_competition": competition_reports(pairs),
        "admission": {
            "decision": "hold",
            "reason": "requires paired probability and chronological bet-policy gates",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

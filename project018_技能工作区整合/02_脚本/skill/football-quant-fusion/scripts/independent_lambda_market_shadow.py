#!/usr/bin/env python3
"""Research-only four-market probabilities from independent pre-match lambdas.

This module consumes only the rolling-xG lambda prior saved before kickoff.
Same-match Sporttery odds are used afterwards as prices for paper EV comparison,
never as probability inputs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HAD_LABELS = ["胜", "平", "负"]
TTG_LABELS = ["0球", "1球", "2球", "3球", "4球", "5球", "6球", "7+球"]
HAFU_LABELS = ["胜胜", "胜平", "胜负", "平胜", "平平", "平负", "负胜", "负平", "负负"]
HALF_SHARE = 0.45
_SCORE_RE = re.compile(r"^(\d+)-(\d+)$")


def _poisson_vector(lam: float, max_goals: int = 20) -> list[float]:
    if not isinstance(lam, (int, float)) or not math.isfinite(lam) or lam <= 0:
        raise ValueError("lambda must be a positive finite number")
    values = [math.exp(-lam)]
    for goals in range(1, max_goals + 1):
        values.append(values[-1] * lam / goals)
    mass = sum(values)
    return [value / mass for value in values]


def _score_matrix(lambda_home: float, lambda_away: float) -> dict[tuple[int, int], float]:
    home = _poisson_vector(lambda_home)
    away = _poisson_vector(lambda_away)
    return {(h, a): hp * ap for h, hp in enumerate(home) for a, ap in enumerate(away)}


def _outcome_index(home: int, away: int) -> int:
    return 0 if home > away else (1 if home == away else 2)


def _had_probabilities(matrix: dict[tuple[int, int], float]) -> dict[str, float]:
    totals = [0.0, 0.0, 0.0]
    for (home, away), probability in matrix.items():
        totals[_outcome_index(home, away)] += probability
    return dict(zip(HAD_LABELS, totals))


def _ttg_probabilities(lambda_total: float) -> dict[str, float]:
    exact = [math.exp(-lambda_total)]
    for goals in range(1, 7):
        exact.append(exact[-1] * lambda_total / goals)
    values = exact + [max(0.0, 1.0 - sum(exact))]
    return dict(zip(TTG_LABELS, values))


def _hafu_probabilities(lambda_home: float, lambda_away: float) -> dict[str, float]:
    first = _score_matrix(lambda_home * HALF_SHARE, lambda_away * HALF_SHARE)
    second = _score_matrix(lambda_home * (1.0 - HALF_SHARE), lambda_away * (1.0 - HALF_SHARE))
    totals = [0.0] * 9
    for (h1, a1), p1 in first.items():
        half_index = _outcome_index(h1, a1)
        for (h2, a2), p2 in second.items():
            full_index = _outcome_index(h1 + h2, a1 + a2)
            totals[half_index * 3 + full_index] += p1 * p2
    return dict(zip(HAFU_LABELS, totals))


def _crs_probabilities(
    matrix: dict[tuple[int, int], float], labels: list[str]
) -> dict[str, float]:
    probabilities = {str(label): 0.0 for label in labels}
    exact = {label for label in probabilities if _SCORE_RE.fullmatch(label)}
    other = ["胜其他", "平其他", "负其他"]
    if not all(label in probabilities for label in other):
        raise ValueError("CRS pool must include 胜其他/平其他/负其他 to preserve probability mass")
    for (home, away), probability in matrix.items():
        label = f"{home}-{away}"
        if label in exact:
            probabilities[label] += probability
        else:
            probabilities[other[_outcome_index(home, away)]] += probability
    return probabilities


def four_market_probabilities(
    lambda_home: float,
    lambda_away: float,
    *,
    crs_labels: list[str],
) -> dict[str, dict[str, float]]:
    """Generate four normalized probability pools without accepting odds."""
    matrix = _score_matrix(float(lambda_home), float(lambda_away))
    return {
        "HAD": _had_probabilities(matrix),
        "TTG": _ttg_probabilities(float(lambda_home) + float(lambda_away)),
        "HAFU": _hafu_probabilities(float(lambda_home), float(lambda_away)),
        "CRS": _crs_probabilities(matrix, list(crs_labels)),
    }


def _odds_pools(job: dict[str, Any]) -> dict[str, dict[str, float]]:
    inputs = job.get("input") or {}
    pools = {
        "HAD": dict(zip(HAD_LABELS, inputs.get("odds") or [])),
        "TTG": dict(zip(TTG_LABELS, (inputs.get("ttg") or {}).get("odds") or [])),
        "HAFU": dict(zip(HAFU_LABELS, (inputs.get("hafu") or {}).get("odds") or [])),
        "CRS": dict(inputs.get("crs") or {}),
    }
    return {
        market: {
            label: float(price)
            for label, price in pool.items()
            if isinstance(price, (int, float)) and not isinstance(price, bool) and float(price) > 1.0
        }
        for market, pool in pools.items()
    }


def build_paper_candidates(
    job: dict[str, Any], *, as_of: datetime | None = None
) -> list[dict[str, Any]]:
    """Return the highest raw paper EV in each available corresponding pool."""
    if as_of is not None:
        kickoff = _parse_time((job.get("identity") or {}).get("kickoff"))
        if kickoff is None or kickoff <= as_of:
            return []
    hybrid = (job.get("research") or {}).get("hybrid") or {}
    prior = hybrid.get("lambda_prior") or {}
    if lambda_evidence_class(job) != "strict_no_future_leakage":
        return []
    lambda_home = prior.get("lambda_home")
    lambda_away = prior.get("lambda_away")
    if lambda_home is None or lambda_away is None:
        return []
    odds = _odds_pools(job)
    crs_labels = list(odds["CRS"])
    if not crs_labels:
        return []
    probabilities = four_market_probabilities(
        float(lambda_home), float(lambda_away), crs_labels=crs_labels
    )
    identity = job.get("identity") or {}
    candidates = []
    for market in ("HAD", "TTG", "HAFU", "CRS"):
        priced = [
            (label, probability, odds[market][label], probability * odds[market][label] - 1.0)
            for label, probability in probabilities[market].items()
            if label in odds[market]
        ]
        if not priced:
            continue
        label, probability, price, ev = max(priced, key=lambda row: row[3])
        candidates.append({
            "candidate_id": f"{identity.get('match_id')}:{market}:{label}",
            "match_id": identity.get("match_id"),
            "match_num": identity.get("match_num"),
            "home": identity.get("home"),
            "away": identity.get("away"),
            "kickoff": identity.get("kickoff"),
            "market": market,
            "selection": label,
            "odds": price,
            "model_probability": probability,
            "decimal_ev": ev,
            "probability_source": "independent_prematch_lambda",
            "lambda_source": prior.get("source"),
            "research_only": True,
            "calibration_status": "UNFITTED_SHADOW",
            "purchase_authorized": False,
        })
    return candidates


def actual_market_labels(
    result: dict[str, Any], *, crs_labels: list[str]
) -> dict[str, str | None]:
    """Map verified settlement scores to the four Sporttery pool labels."""
    full = result.get("score_90") or {}
    if full.get("home") is None or full.get("away") is None:
        return {"HAD": None, "TTG": None, "CRS": None, "HAFU": None}
    home, away = int(full["home"]), int(full["away"])
    outcome = _outcome_index(home, away)
    total = home + away
    exact = f"{home}-{away}"
    crs = exact if exact in set(crs_labels) else ["胜其他", "平其他", "负其他"][outcome]
    half = result.get("score_ht") or {}
    hafu = None
    if half.get("home") is not None and half.get("away") is not None:
        half_index = _outcome_index(int(half["home"]), int(half["away"]))
        hafu = HAFU_LABELS[half_index * 3 + outcome]
    return {
        "HAD": HAD_LABELS[outcome],
        "TTG": TTG_LABELS[min(total, 7)],
        "CRS": crs,
        "HAFU": hafu,
    }


def power_devig(odds: dict[str, float]) -> dict[str, float]:
    """Remove overround with the same power-family convention as production."""
    valid = {
        label: float(price)
        for label, price in odds.items()
        if isinstance(price, (int, float)) and not isinstance(price, bool) and float(price) > 1.0
    }
    if not valid:
        return {}
    implied = {label: 1.0 / price for label, price in valid.items()}
    lo, hi = 0.01, 100.0
    for _ in range(120):
        exponent = (lo + hi) / 2.0
        total = sum(value ** exponent for value in implied.values())
        if total > 1.0:
            lo = exponent
        else:
            hi = exponent
    exponent = (lo + hi) / 2.0
    powered = {label: value ** exponent for label, value in implied.items()}
    mass = sum(powered.values())
    return {label: value / mass for label, value in powered.items()}


def _brier(probabilities: dict[str, float], actual: str) -> float:
    return sum(
        (probability - (1.0 if label == actual else 0.0)) ** 2
        for label, probability in probabilities.items()
    )


def _bootstrap_mean_ci(values: list[float], *, samples: int = 3000, seed: int = 20260823) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(samples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((samples - 1) * 0.025)]
    hi = means[int((samples - 1) * 0.975)]
    return [round(lo, 8), round(hi, 8)]


def evaluate_settled_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    allow_legacy_claims: bool = False,
    allow_replay_verified: bool = False,
) -> dict[str, Any]:
    """Compare independent-lambda probabilities with same-fixture market baselines."""
    accumulators = {
        market: {
            "model_brier": [],
            "market_brier": [],
            "model_logloss": [],
            "market_logloss": [],
            "model_top1": [],
            "market_top1": [],
            "paper_profit_units": [],
        }
        for market in ("HAD", "TTG", "HAFU", "CRS")
    }
    for job, result in pairs:
        hybrid = (job.get("research") or {}).get("hybrid") or {}
        prior = hybrid.get("lambda_prior") or {}
        evidence_class = lambda_evidence_class(job)
        allowed = evidence_class == "strict_no_future_leakage"
        allowed = allowed or (allow_legacy_claims and evidence_class == "legacy_prematch_claim_only")
        allowed = allowed or (allow_replay_verified and evidence_class == "deterministic_replay_verified")
        if not allowed:
            continue
        if prior.get("lambda_home") is None or prior.get("lambda_away") is None:
            continue
        odds = _odds_pools(job)
        if not odds["CRS"]:
            continue
        model = four_market_probabilities(
            float(prior["lambda_home"]),
            float(prior["lambda_away"]),
            crs_labels=list(odds["CRS"]),
        )
        actual = actual_market_labels(result, crs_labels=list(odds["CRS"]))
        for market in accumulators:
            actual_label = actual.get(market)
            if actual_label is None or not odds[market]:
                continue
            market_probs = power_devig(odds[market])
            if actual_label not in model[market] or actual_label not in market_probs:
                continue
            bucket = accumulators[market]
            bucket["model_brier"].append(_brier(model[market], actual_label))
            bucket["market_brier"].append(_brier(market_probs, actual_label))
            bucket["model_logloss"].append(-math.log(max(model[market][actual_label], 1e-15)))
            bucket["market_logloss"].append(-math.log(max(market_probs[actual_label], 1e-15)))
            bucket["model_top1"].append(max(model[market], key=model[market].get) == actual_label)
            bucket["market_top1"].append(max(market_probs, key=market_probs.get) == actual_label)
            priced = [
                (label, probability * odds[market][label] - 1.0)
                for label, probability in model[market].items()
                if label in odds[market]
            ]
            if priced:
                selection, raw_ev = max(priced, key=lambda row: row[1])
                if raw_ev > 0:
                    bucket["paper_profit_units"].append(
                        odds[market][selection] - 1.0 if selection == actual_label else -1.0
                    )

    output = {}
    for market, bucket in accumulators.items():
        n = len(bucket["model_brier"])
        minimum = 200 if market == "HAFU" else 100

        def mean(values: list[Any]) -> float | None:
            return sum(values) / len(values) if values else None

        model_brier = mean(bucket["model_brier"])
        market_brier = mean(bucket["market_brier"])
        model_logloss = mean(bucket["model_logloss"])
        market_logloss = mean(bucket["market_logloss"])
        point_better = bool(
            n
            and model_brier is not None
            and market_brier is not None
            and model_logloss is not None
            and market_logloss is not None
            and model_brier < market_brier
            and model_logloss < market_logloss
        )
        brier_deltas = [
            model_value - market_value
            for model_value, market_value in zip(bucket["model_brier"], bucket["market_brier"])
        ]
        logloss_deltas = [
            model_value - market_value
            for model_value, market_value in zip(bucket["model_logloss"], bucket["market_logloss"])
        ]
        brier_ci = _bootstrap_mean_ci(brier_deltas, seed=20260823 + len(output) * 2)
        logloss_ci = _bootstrap_mean_ci(logloss_deltas, seed=20260824 + len(output) * 2)
        ci_better = bool(
            brier_ci is not None
            and logloss_ci is not None
            and brier_ci[1] < 0
            and logloss_ci[1] < 0
        )
        output[market] = {
            "n": n,
            "minimum_n": minimum,
            "model_brier": round(model_brier, 8) if model_brier is not None else None,
            "market_brier": round(market_brier, 8) if market_brier is not None else None,
            "model_minus_market_brier": round(model_brier - market_brier, 8)
            if model_brier is not None and market_brier is not None else None,
            "model_logloss": round(model_logloss, 8) if model_logloss is not None else None,
            "market_logloss": round(market_logloss, 8) if market_logloss is not None else None,
            "model_minus_market_logloss": round(model_logloss - market_logloss, 8)
            if model_logloss is not None and market_logloss is not None else None,
            "model_top1_pct": round(float(mean(bucket["model_top1"])) * 100.0, 2)
            if bucket["model_top1"] else None,
            "market_top1_pct": round(float(mean(bucket["market_top1"])) * 100.0, 2)
            if bucket["market_top1"] else None,
            "raw_positive_ev_bets": len(bucket["paper_profit_units"]),
            "raw_positive_ev_roi_pct": round(float(mean(bucket["paper_profit_units"])) * 100.0, 2)
            if bucket["paper_profit_units"] else None,
            "point_estimate_better_on_brier_and_logloss": point_better,
            "brier_delta_ci95": brier_ci,
            "logloss_delta_ci95": logloss_ci,
            "paired_ci_both_below_zero": ci_better,
            "admission": "hold",
            "hold_reason": "sample_below_minimum" if n < minimum else "paired_ci_and_calibration_required",
        }
    return {
        "schema": "independent-lambda-market-evaluation-1.0",
        "research_only": True,
        "production_change_allowed": False,
        "markets": output,
    }


def _scoring_rows(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    allow_legacy_claims: bool,
    allow_replay_verified: bool,
) -> dict[str, list[dict[str, Any]]]:
    rows = {market: [] for market in ("HAD", "TTG", "HAFU", "CRS")}
    ordered = sorted(
        pairs,
        key=lambda pair: str((pair[0].get("identity") or {}).get("kickoff") or ""),
    )
    for job, result in ordered:
        evidence_class = lambda_evidence_class(job)
        allowed = evidence_class == "strict_no_future_leakage"
        allowed = allowed or (allow_legacy_claims and evidence_class == "legacy_prematch_claim_only")
        allowed = allowed or (allow_replay_verified and evidence_class == "deterministic_replay_verified")
        if not allowed:
            continue
        hybrid = (job.get("research") or {}).get("hybrid") or {}
        prior = hybrid.get("lambda_prior") or {}
        odds = _odds_pools(job)
        if prior.get("lambda_home") is None or prior.get("lambda_away") is None or not odds["CRS"]:
            continue
        model = four_market_probabilities(
            float(prior["lambda_home"]),
            float(prior["lambda_away"]),
            crs_labels=list(odds["CRS"]),
        )
        actual = actual_market_labels(result, crs_labels=list(odds["CRS"]))
        for market in rows:
            label = actual.get(market)
            market_probs = power_devig(odds[market])
            if label is None or label not in model[market] or label not in market_probs:
                continue
            rows[market].append({
                "actual": label,
                "model": model[market],
                "market": market_probs,
            })
    return rows


def walk_forward_market_weight_scan(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    weights: list[float] | None = None,
    allow_legacy_claims: bool = False,
    allow_replay_verified: bool = False,
) -> dict[str, Any]:
    """Fit market shrinkage on the earlier 70% and score it on the later 30%."""
    weights = weights or [round(step / 10.0, 1) for step in range(11)]
    if any(weight < 0 or weight > 1 for weight in weights):
        raise ValueError("market weights must be within [0, 1]")
    by_market = _scoring_rows(
        pairs,
        allow_legacy_claims=allow_legacy_claims,
        allow_replay_verified=allow_replay_verified,
    )
    output = {}
    for market, rows in by_market.items():
        if len(rows) < 4:
            output[market] = {
                "n": len(rows),
                "train_n": 0,
                "test_n": 0,
                "selected_market_weight": None,
                "decision": "hold",
                "reason": "insufficient_for_time_split",
            }
            continue
        split = max(1, min(len(rows) - 1, int(len(rows) * 0.70)))
        train, test = rows[:split], rows[split:]

        def mixed(row: dict[str, Any], weight: float) -> dict[str, float]:
            return {
                label: (1.0 - weight) * row["model"][label] + weight * row["market"][label]
                for label in row["model"]
            }

        def score(sample: list[dict[str, Any]], weight: float) -> tuple[float, float]:
            probs = [mixed(row, weight) for row in sample]
            brier = sum(_brier(prob, row["actual"]) for prob, row in zip(probs, sample)) / len(sample)
            logloss = sum(
                -math.log(max(prob[row["actual"]], 1e-15))
                for prob, row in zip(probs, sample)
            ) / len(sample)
            return brier, logloss

        scored = [(weight, *score(train, weight)) for weight in weights]
        selected, train_brier, train_logloss = min(scored, key=lambda row: (row[2], row[1]))
        test_brier, test_logloss = score(test, selected)
        market_brier, market_logloss = score(test, 1.0)
        output[market] = {
            "n": len(rows),
            "train_n": len(train),
            "test_n": len(test),
            "selected_market_weight": selected,
            "train_brier": round(train_brier, 8),
            "train_logloss": round(train_logloss, 8),
            "test_brier": round(test_brier, 8),
            "test_logloss": round(test_logloss, 8),
            "test_market_brier": round(market_brier, 8),
            "test_market_logloss": round(market_logloss, 8),
            "test_brier_delta_vs_market": round(test_brier - market_brier, 8),
            "test_logloss_delta_vs_market": round(test_logloss - market_logloss, 8),
            "decision": "hold",
            "reason": "minimum_sample_and_paired_ci_not_satisfied",
        }
    return {
        "schema": "independent-lambda-market-weight-scan-1.0",
        "research_only": True,
        "split": "chronological_70_30",
        "markets": output,
    }


def evaluate_by_lambda_source(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    allow_legacy_claims: bool = False,
    allow_replay_verified: bool = False,
) -> dict[str, Any]:
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for job, result in pairs:
        source = str(
            ((((job.get("research") or {}).get("hybrid") or {}).get("lambda_prior") or {}).get("source"))
            or "unknown"
        )
        grouped.setdefault(source, []).append((job, result))
    return {
        source: {
            "settled_pairs": len(source_pairs),
            "evaluation": evaluate_settled_pairs(
                source_pairs,
                allow_legacy_claims=allow_legacy_claims,
                allow_replay_verified=allow_replay_verified,
            ),
            "weight_scan": walk_forward_market_weight_scan(
                source_pairs,
                allow_legacy_claims=allow_legacy_claims,
                allow_replay_verified=allow_replay_verified,
            ),
            "bet_policy_scans": {
                market: walk_forward_bet_policy_scan(
                    settled_paper_bets(
                        source_pairs,
                        market=market,
                        allow_legacy_claims=allow_legacy_claims,
                        allow_replay_verified=allow_replay_verified,
                    )
                )
                for market in ("HAD", "TTG", "HAFU", "CRS")
            },
        }
        for source, source_pairs in sorted(grouped.items())
    }


def settled_paper_bets(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    market: str,
    allow_legacy_claims: bool = False,
    allow_replay_verified: bool = False,
) -> list[dict[str, Any]]:
    if market not in {"HAD", "TTG", "HAFU", "CRS"}:
        raise ValueError("unknown market")
    rows = []
    for job, result in pairs:
        evidence_class = lambda_evidence_class(job)
        allowed = evidence_class == "strict_no_future_leakage"
        allowed = allowed or (allow_legacy_claims and evidence_class == "legacy_prematch_claim_only")
        allowed = allowed or (allow_replay_verified and evidence_class == "deterministic_replay_verified")
        if not allowed:
            continue
        hybrid = (job.get("research") or {}).get("hybrid") or {}
        prior = hybrid.get("lambda_prior") or {}
        odds = _odds_pools(job)
        if prior.get("lambda_home") is None or prior.get("lambda_away") is None or not odds["CRS"]:
            continue
        probabilities = four_market_probabilities(
            float(prior["lambda_home"]), float(prior["lambda_away"]), crs_labels=list(odds["CRS"])
        )
        actual = actual_market_labels(result, crs_labels=list(odds["CRS"])).get(market)
        if actual is None:
            continue
        priced = [
            (label, probability, odds[market][label], probability * odds[market][label] - 1.0)
            for label, probability in probabilities[market].items()
            if label in odds[market]
        ]
        if not priced:
            continue
        selection, probability, price, raw_ev = max(priced, key=lambda row: row[3])
        if raw_ev <= 0:
            continue
        identity = job.get("identity") or {}
        rows.append({
            "match_id": identity.get("match_id"),
            "kickoff": identity.get("kickoff"),
            "lambda_source": prior.get("source"),
            "market": market,
            "selection": selection,
            "actual": actual,
            "odds": price,
            "model_probability": probability,
            "raw_ev": raw_ev,
            "won": selection == actual,
            "profit_units": price - 1.0 if selection == actual else -1.0,
        })
    return rows


def bet_policy_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {
            "n": 0,
            "wins": 0,
            "hit_rate": None,
            "profit_units": 0.0,
            "roi": None,
            "max_drawdown_units": 0.0,
            "largest_winner_profit_share": None,
        }
    profits = [float(row.get("profit_units") or 0.0) for row in rows]
    wins = sum(bool(row.get("won")) for row in rows)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for profit in profits:
        cumulative += profit
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    winner_profits = [profit for profit in profits if profit > 0]
    positive_profit = sum(winner_profits)
    concentration = max(winner_profits) / positive_profit if positive_profit else None
    total_profit = sum(profits)
    return {
        "n": n,
        "wins": wins,
        "hit_rate": round(wins / n, 8),
        "profit_units": round(total_profit, 8),
        "roi": round(total_profit / n, 8),
        "max_drawdown_units": round(max_drawdown, 8),
        "largest_winner_profit_share": round(concentration, 8) if concentration is not None else None,
    }


def walk_forward_bet_policy_scan(
    bets: list[dict[str, Any]],
    *,
    train_ratio: float = 0.7,
    ev_thresholds: tuple[float, ...] = (0.0, 0.05, 0.10, 0.20, 0.30),
    odds_caps: tuple[float, ...] = (3.0, 5.0, 10.0, 20.0, 1000.0),
    minimum_train_bets: int = 10,
    minimum_test_bets: int = 10,
) -> dict[str, Any]:
    """Select an EV/odds policy on the early sample and inspect it on later matches."""
    ordered = sorted(bets, key=lambda row: (str(row.get("kickoff") or ""), str(row.get("match_id") or "")))
    split_at = int(len(ordered) * train_ratio)
    train = ordered[:split_at]
    test = ordered[split_at:]

    def apply_policy(rows: list[dict[str, Any]], threshold: float, cap: float) -> list[dict[str, Any]]:
        return [
            row for row in rows
            if float(row.get("raw_ev") or 0.0) >= threshold
            and float(row.get("odds") or 0.0) <= cap
        ]

    grid = []
    for threshold in ev_thresholds:
        for cap in odds_caps:
            train_metrics = bet_policy_metrics(apply_policy(train, threshold, cap))
            grid.append({
                "minimum_raw_ev": threshold,
                "maximum_odds": cap,
                "train": train_metrics,
            })
    eligible = [row for row in grid if row["train"]["n"] >= minimum_train_bets]
    if not eligible:
        return {
            "schema": "walk-forward-bet-policy-scan-1.0",
            "selected_on": "train_only",
            "train_n": len(train),
            "test_n": len(test),
            "selected_policy": None,
            "train": bet_policy_metrics([]),
            "test": bet_policy_metrics([]),
            "decision": "hold",
            "reason": "insufficient_train_bets",
            "grid": grid,
        }
    selected = max(
        eligible,
        key=lambda row: (
            float(row["train"]["roi"]),
            row["train"]["n"],
            -float(row["maximum_odds"]),
            -float(row["minimum_raw_ev"]),
        ),
    )
    test_metrics = bet_policy_metrics(
        apply_policy(test, float(selected["minimum_raw_ev"]), float(selected["maximum_odds"]))
    )
    train_metrics = selected["train"]
    if test_metrics["n"] < minimum_test_bets:
        decision, reason = "hold", "insufficient_test_bets"
    elif (train_metrics["roi"] or 0.0) <= 0 or (test_metrics["roi"] or 0.0) <= 0:
        decision, reason = "hold", "roi_not_positive_in_both_splits"
    elif (test_metrics["largest_winner_profit_share"] or 1.0) > 0.5:
        decision, reason = "hold", "test_profit_concentrated_in_one_winner"
    else:
        decision, reason = "candidate_review", "positive_both_splits_but_requires_market_admission_gate"
    return {
        "schema": "walk-forward-bet-policy-scan-1.0",
        "selected_on": "train_only",
        "train_n": len(train),
        "test_n": len(test),
        "selected_policy": {
            "minimum_raw_ev": selected["minimum_raw_ev"],
            "maximum_odds": selected["maximum_odds"],
        },
        "train": train_metrics,
        "test": test_metrics,
        "decision": decision,
        "reason": reason,
        "grid": grid,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def attach_replay_verification(
    job: dict[str, Any], replay_rows: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    match_id = str((job.get("identity") or {}).get("match_id") or "")
    row = replay_rows.get(match_id)
    if not row or row.get("status") != "equivalent" or row.get("equivalent") is not True:
        return deepcopy(job)
    prior = ((job.get("research") or {}).get("hybrid") or {}).get("lambda_prior") or {}
    saved = row.get("saved_prior") or {}
    fields = ("lambda_home", "lambda_away", "source", "sample_legs", "team_sample_sizes")
    if any(prior.get(field) != saved.get(field) for field in fields if field in prior or field in saved):
        return deepcopy(job)
    enriched = deepcopy(job)
    hybrid = enriched.setdefault("research", {}).setdefault("hybrid", {})
    hybrid["replay_verification"] = {
        "equivalent": True,
        "routing_audit": deepcopy(row.get("routing_audit") or {}),
        "source": "lambda-prior-replay-audit-1.0",
    }
    return enriched


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def lambda_evidence_class(job: dict[str, Any]) -> str:
    hybrid = (job.get("research") or {}).get("hybrid") or {}
    prior = hybrid.get("lambda_prior") or {}
    if prior.get("lambda_home") is None or prior.get("lambda_away") is None:
        return "invalid"
    routing = hybrid.get("routing_audit") or {}
    as_of = _parse_time((job.get("input") or {}).get("prediction_as_of"))
    kickoff = _parse_time(
        (job.get("identity") or {}).get("kickoff")
        or (job.get("input") or {}).get("kickoff")
    )
    history_latest = _parse_time(routing.get("history_latest"))
    research_run_at = _parse_time(hybrid.get("research_run_at"))
    if (
        routing.get("no_future_leakage") is True
        and as_of is not None
        and kickoff is not None
        and history_latest is not None
        and research_run_at is not None
        and as_of < kickoff
        and history_latest < kickoff
        and research_run_at < kickoff
    ):
        return "strict_no_future_leakage"
    replay = hybrid.get("replay_verification") or {}
    replay_routing = replay.get("routing_audit") or {}
    replay_history_latest = _parse_time(replay_routing.get("history_latest"))
    if (
        replay.get("equivalent") is True
        and replay_routing.get("no_future_leakage") is True
        and as_of is not None
        and kickoff is not None
        and replay_history_latest is not None
        and as_of < kickoff
        and replay_history_latest < kickoff
    ):
        return "deterministic_replay_verified"
    note = str(prior.get("note") or "")
    source = str(prior.get("source") or "")
    if (
        as_of is not None
        and kickoff is not None
        and as_of < kickoff
        and "开球前" in note
        and source in {"understat_rolling_xg", "apifootball_events_goals_only"}
    ):
        return "legacy_prematch_claim_only"
    return "invalid"


def _safe_lambda(job: dict[str, Any]) -> bool:
    return lambda_evidence_class(job) == "strict_no_future_leakage"


def _result_path(results_root: Path, match_id: str) -> Path | None:
    numeric = re.sub(r"^sporttery-", "", match_id)
    for name in (f"{match_id}.json", f"{numeric}.json"):
        path = results_root / name
        if path.is_file():
            return path
    return None


def _verified_half_time_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not Path(path).is_file():
        return {}
    try:
        payload = _read_json(Path(path))
    except (OSError, ValueError):
        return {}
    return {
        str(row.get("match_id")): row
        for row in (payload.get("rows") or [])
        if row.get("status") == "verified"
        and isinstance(row.get("score_ht"), dict)
        and isinstance(row.get("score_90"), dict)
    }


def _join_verified_half_time(
    match_id: str,
    result: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    if result.get("score_ht"):
        return result, False
    row = evidence.get(match_id)
    if not row or row.get("score_90") != result.get("score_90"):
        return result, False
    enriched = dict(result)
    enriched["score_ht"] = dict(row["score_ht"])
    enriched["score_ht_evidence"] = {
        "status": "verified",
        "matched_by": row.get("matched_by"),
        "provider": row.get("provider"),
    }
    return enriched, True


def build_report(
    jobs_root: Path,
    results_root: Path,
    *,
    half_time_evidence: Path | None = None,
    lambda_replay_audit: Path | None = None,
) -> dict[str, Any]:
    report_as_of = datetime.now(timezone.utc)
    strict_jobs_by_id: dict[str, dict[str, Any]] = {}
    replay_jobs_by_id: dict[str, dict[str, Any]] = {}
    expanded_jobs_by_id: dict[str, dict[str, Any]] = {}
    replay_rows: dict[str, dict[str, Any]] = {}
    if lambda_replay_audit and Path(lambda_replay_audit).is_file():
        try:
            replay_payload = _read_json(Path(lambda_replay_audit))
            replay_rows = {
                str(row.get("match_id")): row
                for row in (replay_payload.get("rows") or [])
                if row.get("match_id")
            }
        except (OSError, ValueError):
            replay_rows = {}
    for path in sorted(Path(jobs_root).rglob("sporttery-*.json")):
        try:
            job = _read_json(path)
        except (OSError, ValueError):
            continue
        match_id = str((job.get("identity") or {}).get("match_id") or "")
        job = attach_replay_verification(job, replay_rows)
        evidence_class = lambda_evidence_class(job)
        if match_id and evidence_class != "invalid":
            expanded_jobs_by_id[match_id] = job
            if evidence_class == "strict_no_future_leakage":
                strict_jobs_by_id[match_id] = job
                replay_jobs_by_id[match_id] = job
            elif evidence_class == "deterministic_replay_verified":
                replay_jobs_by_id[match_id] = job
    strict_settled_pairs = []
    replay_settled_pairs = []
    expanded_settled_pairs = []
    pending_jobs = []
    half_time_map = _verified_half_time_map(half_time_evidence)
    joined_half_time_ids: set[str] = set()
    for match_id, job in expanded_jobs_by_id.items():
        result_path = _result_path(Path(results_root), match_id)
        if result_path is None:
            if match_id in strict_jobs_by_id:
                pending_jobs.append(job)
            continue
        try:
            result = _read_json(result_path)
        except (OSError, ValueError):
            if match_id in strict_jobs_by_id:
                pending_jobs.append(job)
            continue
        if result.get("status") == "finished" and result.get("score_90"):
            result, joined = _join_verified_half_time(match_id, result, half_time_map)
            if joined:
                joined_half_time_ids.add(match_id)
            expanded_settled_pairs.append((job, result))
            if match_id in strict_jobs_by_id:
                strict_settled_pairs.append((job, result))
            if match_id in replay_jobs_by_id:
                replay_settled_pairs.append((job, result))
        elif match_id in strict_jobs_by_id:
            pending_jobs.append(job)
    paper_candidates = [
        candidate
        for job in pending_jobs
        for candidate in build_paper_candidates(job, as_of=report_as_of)
    ]
    paper_candidates.sort(key=lambda row: row.get("decimal_ev", float("-inf")), reverse=True)
    return {
        "schema": "independent-lambda-four-market-shadow-1.0",
        "generated_at": report_as_of.isoformat(),
        "research_only": True,
        "production_change_allowed": False,
        "probability_input_contract": {
            "allowed": "pre-match rolling-xG lambda prior",
            "forbidden": "same-match HAD/TTG/HAFU/CRS odds as probability input",
            "odds_usage": "price and market baseline only",
        },
        "coverage": {
            "unique_jobs_with_safe_lambda": len(strict_jobs_by_id),
            "deterministic_replay_verified_jobs": len(replay_jobs_by_id),
            "legacy_prematch_claim_only_jobs": len(expanded_jobs_by_id) - len(strict_jobs_by_id),
            "settled_pairs": len(strict_settled_pairs),
            "deterministic_replay_settled_pairs": len(replay_settled_pairs),
            "legacy_plus_strict_settled_pairs": len(expanded_settled_pairs),
            "unsettled_or_result_unavailable": len(pending_jobs),
            "verified_half_time_joined": len(joined_half_time_ids),
        },
        "evaluation": evaluate_settled_pairs(strict_settled_pairs),
        "market_weight_walk_forward": walk_forward_market_weight_scan(strict_settled_pairs),
        "deterministic_replay_evaluation": evaluate_settled_pairs(
            replay_settled_pairs, allow_replay_verified=True
        ),
        "deterministic_replay_weight_scan": walk_forward_market_weight_scan(
            replay_settled_pairs, allow_replay_verified=True
        ),
        "deterministic_replay_by_source": evaluate_by_lambda_source(
            replay_settled_pairs, allow_replay_verified=True
        ),
        "legacy_plus_strict_exploratory_evaluation": evaluate_settled_pairs(
            expanded_settled_pairs, allow_legacy_claims=True
        ),
        "legacy_plus_strict_exploratory_weight_scan": walk_forward_market_weight_scan(
            expanded_settled_pairs, allow_legacy_claims=True
        ),
        "pending_paper_candidates": paper_candidates,
        "admission": {
            "decision": "hold",
            "reason": "each market must meet its own sample, calibration, paired-CI and release gates",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--half-time-evidence")
    parser.add_argument("--lambda-replay-audit")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report(
        Path(args.jobs_root),
        Path(args.results_root),
        half_time_evidence=Path(args.half_time_evidence) if args.half_time_evidence else None,
        lambda_replay_audit=Path(args.lambda_replay_audit) if args.lambda_replay_audit else None,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

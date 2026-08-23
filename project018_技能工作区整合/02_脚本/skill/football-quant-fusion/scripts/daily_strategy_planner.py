#!/usr/bin/env python3
"""Build an auditable daily strategy plan without bypassing production gates.

The planner intentionally separates market baselines from independent model
probabilities.  Official Sporttery odds may describe what the market prices;
they are never, by themselves, evidence of a positive expected-value bet.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from recommendation_policy import load_policy


TTG_LABELS = ["0球", "1球", "2球", "3球", "4球", "5球", "6球", "7+球"]
HAFU_LABELS = ["胜胜", "胜平", "胜负", "平胜", "平平", "平负", "负胜", "负平", "负负"]
HAD_LABELS = ["胜", "平", "负"]
RECREATIONAL_QUOTAS = {"HAD": 3, "TTG": 2, "HAFU": 1, "CRS": 1}
RECREATIONAL_SINGLE_STAKES = {"HAD": 14.0, "TTG": 10.0, "HAFU": 8.0, "CRS": 6.0}
DEFAULT_RECREATIONAL_REQUIRED_EVIDENCE_STATUSES = {
    "team_stats": {"VALID", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"},
    "recent_form": {"VALID", "PARTIAL", "OK", "AVAILABLE", "FRESH", "AGING"},
}
RECREATIONAL_LIMITS = {
    "HAD": {"minimum_probability_pct": 42.0, "minimum_odds": 1.30, "maximum_odds": 2.8, "maximum_overround_pct": 16.0},
    "TTG": {"minimum_probability_pct": 18.0, "minimum_odds": 2.50, "maximum_odds": 6.0, "maximum_overround_pct": 30.0},
    "HAFU": {"minimum_probability_pct": 18.0, "minimum_odds": 1.80, "maximum_odds": 7.0, "maximum_overround_pct": 32.0},
    "CRS": {"minimum_probability_pct": 8.0, "minimum_odds": 4.00, "maximum_odds": 15.0, "maximum_overround_pct": 50.0},
}


class StrategyGateError(RuntimeError):
    """Raised when a caller attempts a production plan past a closed gate."""


def _valid_price(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 1.0


def _pool_from_list(labels: list[str], odds: Any) -> list[tuple[str, float]]:
    if not isinstance(odds, list) or len(odds) != len(labels):
        return []
    return [(label, float(price)) for label, price in zip(labels, odds) if _valid_price(price)]


def _pool_from_mapping(odds: Any) -> list[tuple[str, float]]:
    if not isinstance(odds, dict):
        return []
    return [(str(label), float(price)) for label, price in odds.items() if _valid_price(price)]


def _market_baseline(pool: list[tuple[str, float]]) -> dict[str, Any]:
    if not pool:
        return {
            "official_pool_used": False,
            "market_top_selection": None,
            "market_top_odds": None,
            "market_top_probability_pct": None,
            "market_overround_pct": None,
        }
    inverse = [(label, price, 1.0 / price) for label, price in pool]
    inverse_sum = sum(row[2] for row in inverse)
    label, price, implied = max(inverse, key=lambda row: row[2])
    return {
        "official_pool_used": True,
        "market_top_selection": label,
        "market_top_odds": price,
        "market_top_probability_pct": round(implied / inverse_sum * 100.0, 2),
        "market_overround_pct": round((inverse_sum - 1.0) * 100.0, 2),
    }


def _top_from_probabilities(labels: list[str], probs: Any) -> tuple[str | None, float | None]:
    if not isinstance(probs, list) or len(probs) != len(labels):
        return None, None
    numeric = [float(value) if isinstance(value, (int, float)) else float("-inf") for value in probs]
    index = max(range(len(numeric)), key=numeric.__getitem__)
    if numeric[index] == float("-inf"):
        return None, None
    return labels[index], numeric[index]


def _model_views(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    quant = next(
        (row for row in (job.get("outputs") or []) if row.get("track") == "quant"),
        {},
    )
    forecasts = quant.get("market_forecasts") or {}
    had_selection, had_probability = _top_from_probabilities(
        HAD_LABELS, quant.get("final_1x2_pct")
    )
    views = {
        "HAD": {
            "selection": had_selection,
            "probability_pct": had_probability,
            "source": "market_conditioned_model" if quant.get("mode") == "market_only" else "hybrid_model",
            "independent": False,
        }
    }
    for market, labels in (("TTG", TTG_LABELS), ("HAFU", HAFU_LABELS)):
        data = forecasts.get(market) or {}
        selection, probability = _top_from_probabilities(labels, data.get("model_prob_pct"))
        views[market] = {
            "selection": selection,
            "probability_pct": probability,
            "source": data.get("probability_source"),
            "independent": data.get("independent_from_same_pool") is True,
        }
    score = forecasts.get("CRS") or {}
    top_scores = score.get("top_scores") or []
    first = top_scores[0] if top_scores else {}
    views["CRS"] = {
        "selection": first.get("score"),
        "probability_pct": first.get("prob_pct", first.get("probability_pct")),
        "source": score.get("probability_source"),
        "independent": score.get("independent_from_same_pool") is True,
    }
    return views


def _job_evidence_audit(job: dict[str, Any]) -> dict[str, Any]:
    quant = next((row for row in (job.get("outputs") or []) if row.get("track") == "quant"), {})
    audit = quant.get("evidence_audit") or job.get("evidence_audit") or {}
    if not audit:
        return {"evidence_gap": True, "evidence_status": "MISSING", "evidence_gap_reasons": ["EVIDENCE_AUDIT_MISSING"]}
    return audit


def _market_rows(
    job: dict[str, Any],
    policy: dict[str, Any],
    independent_index: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    identity = job.get("identity") or {}
    inputs = job.get("input") or {}
    match_id = identity.get("match_id")
    common = {
        "match_id": match_id,
        "match_num": identity.get("match_num"),
        "home": identity.get("home"),
        "away": identity.get("away"),
        "competition": identity.get("competition"),
        "kickoff": identity.get("kickoff"),
    }
    pools = {
        "HAD": _pool_from_list(HAD_LABELS, inputs.get("odds")),
        "TTG": _pool_from_list(TTG_LABELS, (inputs.get("ttg") or {}).get("odds")),
        "HAFU": _pool_from_list(HAFU_LABELS, (inputs.get("hafu") or {}).get("odds")),
        "CRS": _pool_from_mapping(inputs.get("crs")),
    }
    model_views = _model_views(job)
    evidence = _job_evidence_audit(job)
    evidence_gap = bool(evidence.get("evidence_gap"))
    evidence_reasons = list(evidence.get("evidence_gap_reasons") or [])
    rows = []
    for market, pool in pools.items():
        baseline = _market_baseline(pool)
        model_view = model_views.get(market) or {}
        independent = independent_index.get((str(match_id), market)) or {}
        reasons = ["MARKET_DERIVED_ONLY", "INDEPENDENT_MODEL_PROBABILITY_UNAVAILABLE"]
        if evidence_gap:
            reasons.append("EVIDENCE_GAP")
            reasons.extend(f"EVIDENCE_GAP_REASON:{reason}" for reason in evidence_reasons)
        if model_view.get("source") == "market_conditioned_model":
            reasons.append("MARKET_CONDITIONED_MODEL")
        if not baseline["official_pool_used"]:
            reasons.append("OFFICIAL_POOL_UNAVAILABLE")
        if policy.get("production_recommendations_enabled") is not True:
            reasons.append("PRODUCTION_RECOMMENDATIONS_DISABLED")
        independent_probability = independent.get("model_probability")
        calibration_status = str(independent.get("calibration_status") or "").upper()
        independent_approved = bool(
            independent.get("purchase_authorized") is True
            and calibration_status in {"VALID", "APPROVED"}
        )
        if independent_probability is not None:
            reasons = [reason for reason in reasons if reason != "INDEPENDENT_MODEL_PROBABILITY_UNAVAILABLE"]
            if not independent_approved:
                reasons.append("INDEPENDENT_MODEL_UNCALIBRATED")
        strategy_eligible = bool(
            baseline["official_pool_used"]
            and policy.get("production_recommendations_enabled") is True
            and independent_approved
            and not evidence_gap
        )
        if strategy_eligible:
            reasons = []
        rows.append({
            **common,
            "candidate_id": f"{match_id}:{market}" if match_id else None,
            "market": market,
            "official_odds_source": "Sporttery official odds",
            "international_odds_policy": "research_only",
            **baseline,
            "model_top_selection": model_view.get("selection"),
            "model_top_probability_pct": model_view.get("probability_pct"),
            "model_probability_source": model_view.get("source"),
            "independent_selection": independent.get("selection"),
            "independent_model_probability_pct": round(float(independent_probability) * 100.0, 2)
            if independent_probability is not None else None,
            "independent_raw_ev_pct": round(float(independent.get("decimal_ev")) * 100.0, 2)
            if independent.get("decimal_ev") is not None else None,
            "independent_probability_source": independent.get("probability_source"),
            "independent_calibration_status": independent.get("calibration_status"),
            "strategy_eligible": strategy_eligible,
            "block_reasons": reasons,
            "evidence_gap": evidence_gap,
            "evidence_status": evidence.get("evidence_status"),
            "evidence_gap_reasons": evidence_reasons,
            "evidence_entries": evidence.get("entries") or {},
            "risk_tags": ["EVIDENCE_GAP"] if evidence_gap else [],
            "note": "对应市场官方赔率仅作为市场基线；没有获批的独立校准概率时不得转成购买建议。",
        })
    return rows


def build_combinations(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return auditable 2-leg and 3-leg structures from eligible distinct matches.

    This function does not size stakes.  Stake sizing remains a separate release
    gate and cannot be inferred from market prices or combination count.
    """
    eligible = [dict(row) for row in candidates if row.get("strategy_eligible") is True]
    combos = []
    for legs_count in (2, 3):
        for legs in itertools.combinations(eligible, legs_count):
            match_ids = [leg.get("match_id") for leg in legs]
            if None in match_ids or len(set(match_ids)) != legs_count:
                continue
            combos.append({
                "combo_id": "+".join(str(leg.get("candidate_id")) for leg in legs),
                "legs_count": legs_count,
                "legs": list(legs),
                "same_match_legs_forbidden": True,
                "stake_sizing_status": "NOT_RELEASED",
            })
    return combos


def _aware_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _recreational_candidates(
    market_audit: list[dict[str, Any]], *, as_of: datetime, policy: dict[str, Any]
) -> list[dict[str, Any]]:
    # Backward-compatible default: callers with the legacy production-only
    # policy still get the explicitly separate entertainment budget planner.
    if policy.get("recreational_strategy_enabled", True) is not True:
        return []
    allowed_pending = set(policy.get("recreational_allowed_markets_with_pending_lineup") or {"HAD", "TTG"})
    required = policy.get("recreational_required_evidence_statuses") or DEFAULT_RECREATIONAL_REQUIRED_EVIDENCE_STATUSES
    blocked = set(policy.get("recreational_block_reasons") or {"POST_KICKOFF_NOT_USABLE", "EVIDENCE_AUDIT_MISSING"})
    candidates = []
    for row in market_audit:
        market = str(row.get("market") or "")
        limits = RECREATIONAL_LIMITS.get(market)
        kickoff = _aware_time(row.get("kickoff"))
        if limits is None or kickoff is None or kickoff <= as_of:
            continue
        gate_reasons = []
        if row.get("evidence_gap") is True:
            # A pending official lineup is expected before kickoff.  Keep only
            # low-risk markets with verified team context and recent form;
            # HAFU/CRS remain closed until the evidence gap is resolved.
            if market not in allowed_pending:
                continue
            gap_reasons = set(row.get("evidence_gap_reasons") or [])
            if gap_reasons & blocked:
                continue
            entries = row.get("evidence_entries") or {}
            # An empty provider field is not proof of a cleared injury report.
            # Keep this ambiguity out of even the relaxed entertainment plan.
            if any(str((entries.get(field) or {}).get("status") or "").upper() == "EMPTY_UNCONFIRMED"
                   for field in ("injury", "suspensions")):
                continue
            for field, allowed_statuses in required.items():
                status = str((entries.get(field) or {}).get("status") or "").upper()
                if status not in {str(item).upper() for item in allowed_statuses}:
                    break
            else:
                gate_reasons.append("EVIDENCE_GAP_RELAXED_FOR_ENTERTAINMENT")
                gate_reasons.extend(sorted(gap_reasons))
            if not gate_reasons:
                continue
        probability = row.get("market_top_probability_pct")
        odds = row.get("market_top_odds")
        overround = row.get("market_overround_pct")
        if not all(isinstance(value, (int, float)) for value in (probability, odds, overround)):
            continue
        if float(probability) < limits["minimum_probability_pct"]:
            continue
        if not limits["minimum_odds"] <= float(odds) <= limits["maximum_odds"]:
            continue
        if float(overround) > limits["maximum_overround_pct"]:
            continue
        model_selection = row.get("model_top_selection")
        market_selection = row.get("market_top_selection")
        agreement = model_selection == market_selection if model_selection is not None else None
        if agreement is False:
            continue
        score = (
            float(probability)
            - max(0.0, float(overround)) * 0.5
            - abs(float(odds) - 2.0) * 2.0
            - (8.0 if agreement is None else 0.0)
        )
        candidates.append({
            **row,
            "selection": market_selection,
            "odds": float(odds),
            "consensus_probability_pct": float(probability),
            "model_market_agreement": agreement,
            "selection_basis": "market_and_model_agree" if agreement is True else "market_consensus_only_model_view_unavailable",
            "unfitted_independent_shadow_ignored": row.get("independent_selection") is not None,
            "recreational_risk_score": round(score, 4),
            "edge_claim": False,
            "expected_value_status": "NOT_VALIDATED",
            "purchase_basis": "market_consensus_plus_model_agreement_recreational_budget",
            "recreational_gate": "OPEN_RELAXED",
            "recreational_gate_reasons": gate_reasons or ["EVIDENCE_COMPLETE"],
            "production_authorized": False,
        })
    return sorted(
        candidates,
        key=lambda row: (-float(row["recreational_risk_score"]), str(row.get("kickoff") or ""), str(row.get("match_id") or "")),
    )


def build_budgeted_action_plan(
    market_audit: list[dict[str, Any]], *, bankroll: float, as_of: datetime,
    policy: dict[str, Any]
) -> dict[str, Any]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    candidates = _recreational_candidates(market_audit, as_of=as_of, policy=policy)
    singles = []
    used_matches: set[str] = set()
    for market, quota in RECREATIONAL_QUOTAS.items():
        market_rows = [
            row for row in candidates
            if row["market"] == market and str(row.get("match_id")) not in used_matches
        ]
        for row in market_rows[:quota]:
            match_id = str(row["match_id"])
            used_matches.add(match_id)
            singles.append({
                **row,
                "stake_amount": RECREATIONAL_SINGLE_STAKES[market],
                "maximum_loss_amount": RECREATIONAL_SINGLE_STAKES[market],
            })

    low_variance_legs = sorted(
        [row for row in singles if row["market"] in {"HAD", "TTG"}],
        key=lambda row: -float(row["recreational_risk_score"]),
    )
    combos = []
    for legs_count, stake in ((2, 16.0), (3, 8.0)):
        legs = []
        seen = set()
        for row in low_variance_legs:
            if row["match_id"] in seen:
                continue
            legs.append({
                "candidate_id": row["candidate_id"],
                "match_id": row["match_id"],
                "match_num": row.get("match_num"),
                "home": row.get("home"),
                "away": row.get("away"),
                "kickoff": row.get("kickoff"),
                "market": row["market"],
                "selection": row["selection"],
                "odds": row["odds"],
            })
            seen.add(row["match_id"])
            if len(legs) == legs_count:
                break
        if len(legs) == legs_count:
            combined_odds = 1.0
            for leg in legs:
                combined_odds *= float(leg["odds"])
            combos.append({
                "combo_id": "+".join(str(leg["candidate_id"]) for leg in legs),
                "legs_count": legs_count,
                "legs": legs,
                "combined_odds": round(combined_odds, 4),
                "stake_amount": stake,
                "maximum_loss_amount": stake,
                "edge_claim": False,
                "expected_value_status": "NOT_VALIDATED",
                "purchase_basis": "recreational_budget_distinct_match_combo",
                "same_match_legs_forbidden": True,
            })
    allocated = round(
        sum(float(row["stake_amount"]) for row in singles)
        + sum(float(row["stake_amount"]) for row in combos),
        2,
    )
    return {
        "candidates": candidates,
        "singles": singles,
        "combos": combos,
        "allocated": min(round(float(bankroll), 2), allocated),
    }


def build_daily_strategy(
    jobs: Iterable[dict[str, Any]],
    policy: dict[str, Any],
    *,
    bankroll: float = 100.0,
    execution_mode: str = "paper",
    independent_shadow: dict[str, Any] | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    if bankroll <= 0:
        raise ValueError("bankroll must be positive")
    if execution_mode not in {"paper", "production", "budgeted_action"}:
        raise ValueError("execution_mode must be paper, production or budgeted_action")
    enabled = policy.get("production_recommendations_enabled") is True
    if execution_mode == "production" and not enabled:
        raise StrategyGateError("production recommendations are disabled by policy")

    independent_index = {
        (str(row.get("match_id")), str(row.get("market"))): row
        for row in ((independent_shadow or {}).get("pending_paper_candidates") or [])
        if row.get("match_id") and row.get("market")
    }
    market_audit = [
        row
        for job in jobs
        for row in _market_rows(job, policy, independent_index)
    ]
    eligible = [row for row in market_audit if row.get("strategy_eligible") is True]
    gap_rows = [row for row in market_audit if row.get("evidence_gap") is True]
    reason_counts = Counter(
        reason
        for row in gap_rows
        for reason in (row.get("evidence_gap_reasons") or ["EVIDENCE_GAP"])
    )
    edge_values = [
        float(row["independent_raw_ev_pct"])
        for row in market_audit
        if isinstance(row.get("independent_raw_ev_pct"), (int, float))
        and row.get("independent_calibration_status") in {"VALID", "APPROVED"}
    ]
    evidence_gap_summary = {
        "total_market_rows": len(market_audit),
        "evidence_gap_market_rows": len(gap_rows),
        "evidence_gap_matches": len({str(row.get("match_id")) for row in gap_rows}),
        "reason_counts": dict(reason_counts),
        "status_counts": dict(Counter(str(row.get("evidence_status") or "UNKNOWN") for row in market_audit)),
    }
    edge_distribution = {
        "count": len(edge_values),
        "min_pct": min(edge_values) if edge_values else None,
        "max_pct": max(edge_values) if edge_values else None,
        "median_pct": sorted(edge_values)[len(edge_values) // 2] if edge_values else None,
        "research_only": True,
    }
    risk_tags = []
    if gap_rows:
        risk_tags.append("EVIDENCE_GAP")
    if market_audit and not edge_values:
        risk_tags.append("NO_INDEPENDENT_CALIBRATED_EDGE")
    if any(row.get("model_probability_source") == "market_conditioned_model" for row in market_audit):
        risk_tags.append("MARKET_DERIVED_ONLY")
    combos = build_combinations(eligible)
    if execution_mode == "budgeted_action":
        action = build_budgeted_action_plan(
            market_audit,
            bankroll=float(bankroll),
            as_of=as_of or datetime.now().astimezone(),
            policy=policy,
        )
        allocated = action["allocated"]
        preserved = round(float(bankroll) - allocated, 2)
        complete_budget = math.isclose(allocated, float(bankroll), abs_tol=1e-9)
        return {
            "schema": "daily-strategy-plan-1.1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "execution_mode": execution_mode,
            "production_authorized": False,
            "action_authorized_by_user_budget_mode": True,
            "decision": {
                "action": "purchase_recreational_budget" if allocated > 0 else "preserve_bankroll",
                "reason": "用户要求固定娱乐预算；本层按市场共识与模型同向度控制风险，不声明统计优势。"
                if allocated > 0 else "没有足够的未开赛低风险候选",
                "full_budget_allocated": complete_budget,
            },
            "budget": {
                "daily_budget_amount": round(float(bankroll), 2),
                "allocated_amount": allocated,
                "preserved_amount": preserved,
                "currency": "CNY",
            },
            "market_audit": market_audit,
            "evidence_gap_summary": evidence_gap_summary,
            "edge_distribution": edge_distribution,
            "risk_tags": risk_tags,
            "market_source_policy": {"HAD": "Sporttery official odds", "TTG": "Sporttery official odds", "HAFU": "Sporttery official odds", "CRS": "Sporttery official odds", "international_odds": "research_only"},
            "recreational_candidates": action["candidates"],
            "eligible_directional_candidates": eligible,
            "eligible_combo_structures": combos,
            "single_purchase_recommendations": action["singles"],
            "combo_purchase_recommendations": action["combos"],
            "release_gates": {
                "statistical_edge": "CLOSED",
                "production_recommendation": "CLOSED",
                "recreational_gate": "OPEN_RELAXED",
                "recreational_directional_recommendation": "OPEN",
                "fixed_budget_stake_sizing": "OPEN",
                "two_leg_combo": "OPEN" if any(row["legs_count"] == 2 for row in action["combos"]) else "CLOSED",
                "three_leg_combo": "OPEN" if any(row["legs_count"] == 3 for row in action["combos"]) else "CLOSED",
            },
            "risk_disclosure": {
                "edge_verified": False,
                "expected_value_status": "NOT_VALIDATED",
                "maximum_loss_amount": allocated,
                "bankroll_interpretation": "daily_discretionary_entertainment_loss_limit",
                "no_chasing_losses": True,
            },
        }
    # Stake sizing is intentionally unreleased.  Even an eligible directional
    # candidate is not a purchase recommendation until that separate gate opens.
    single_recommendations: list[dict[str, Any]] = []
    combo_recommendations: list[dict[str, Any]] = []
    allocated = 0.0
    preserved = round(float(bankroll) - allocated, 2)
    disabled_reason = policy.get("production_recommendations_disabled_reason")
    return {
        "schema": "daily-strategy-plan-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": execution_mode,
        "production_authorized": enabled,
        "decision": {
            "action": "preserve_bankroll",
            "reason": disabled_reason or "no candidate passed independent calibration and staking gates",
        },
        "budget": {
            "daily_budget_amount": round(float(bankroll), 2),
            "allocated_amount": allocated,
            "preserved_amount": preserved,
            "currency": "CNY",
        },
        "market_audit": market_audit,
        "evidence_gap_summary": evidence_gap_summary,
        "edge_distribution": edge_distribution,
        "risk_tags": risk_tags,
        "market_source_policy": {"HAD": "Sporttery official odds", "TTG": "Sporttery official odds", "HAFU": "Sporttery official odds", "CRS": "Sporttery official odds", "international_odds": "research_only"},
        "eligible_directional_candidates": eligible,
        "eligible_combo_structures": combos,
        "single_purchase_recommendations": single_recommendations,
        "combo_purchase_recommendations": combo_recommendations,
        "release_gates": {
            "directional_recommendation": "OPEN" if enabled else "CLOSED",
            "stake_sizing": "CLOSED",
            "two_leg_combo": "CLOSED",
            "three_leg_combo": "CLOSED",
        },
    }


def _load_jobs(jobs_dir: Path) -> list[dict[str, Any]]:
    if not jobs_dir.is_dir():
        raise FileNotFoundError(f"jobs directory not found: {jobs_dir}")
    jobs = []
    for path in sorted(jobs_dir.glob("sporttery-*.json")):
        jobs.append(json.loads(path.read_text(encoding="utf-8-sig")))
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-dir", required=True)
    parser.add_argument("--bankroll", type=float, default=100.0)
    parser.add_argument("--execution-mode", choices=("paper", "production", "budgeted_action"), default="paper")
    parser.add_argument("--as-of", help="带时区的决策时间；budgeted_action 用于排除已开赛比赛")
    parser.add_argument("--independent-shadow")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    independent_shadow = (
        json.loads(Path(args.independent_shadow).read_text(encoding="utf-8-sig"))
        if args.independent_shadow else None
    )
    plan = build_daily_strategy(
        _load_jobs(Path(args.jobs_dir)),
        load_policy(),
        bankroll=args.bankroll,
        execution_mode=args.execution_mode,
        independent_shadow=independent_shadow,
        as_of=_aware_time(args.as_of) if args.as_of else None,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

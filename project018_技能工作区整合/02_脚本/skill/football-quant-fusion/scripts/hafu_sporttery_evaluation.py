#!/usr/bin/env python3
"""Evaluate Sporttery HAFU closing probabilities with a chronological holdout.

The source must be ``fetch_sporttery_history_all.py`` output.  It deliberately
uses only the last quote before kickoff and the official HAFU settlement code;
it never derives half-time state from a full-time score.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path


STATES = ("HH", "HD", "HA", "DH", "DD", "DA", "AH", "AD", "AA")
ODDS_KEYS = tuple(x.lower() for x in STATES)
STATE_INDEX = {state: index for index, state in enumerate(STATES)}


def _closing_probabilities(raw: dict | None) -> list[float] | None:
    """Convert all nine closing decimal odds to a normalized implied vector."""
    if not isinstance(raw, dict):
        return None
    try:
        inverse = [1.0 / float(raw[key]) for key in ODDS_KEYS]
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not all(math.isfinite(value) and value > 0 for value in inverse):
        return None
    total = sum(inverse)
    return [round(value / total, 10) for value in inverse]


def _settled_state(results: list[dict] | None) -> int | None:
    for item in results or []:
        if str(item.get("code") or "").upper() != "HAFU":
            continue
        state = str(item.get("combination") or "").upper().replace(":", "")
        return STATE_INDEX.get(state)
    return None


def _closing_had_odds(raw: dict | None) -> list[float] | None:
    if not isinstance(raw, dict):
        return None
    try:
        odds = [float(raw[key]) for key in ("h", "d", "a")]
    except (KeyError, TypeError, ValueError):
        return None
    return odds if all(math.isfinite(value) and value > 1.0 for value in odds) else None


def extract_rows(matches: list[dict]) -> list[dict]:
    """Return auditable valid examples, ordered by caller on kickoff later."""
    extracted = []
    for match in matches or []:
        kickoff = match.get("kickoff_iso") or match.get("kickoff")
        probability = _closing_probabilities((match.get("closing_pre_match") or {}).get("hafu"))
        outcome = _settled_state(match.get("match_result_list"))
        if not kickoff or probability is None or outcome is None:
            continue
        extracted.append({
            "match_id": match.get("matchId") or match.get("match_id"),
            "kickoff": str(kickoff),
            "prob": probability,
            "outcome": outcome,
            "had_odds": _closing_had_odds((match.get("closing_pre_match") or {}).get("had")),
        })
    return extracted


def apply_temperature(probability: list[float], temperature: float) -> list[float]:
    values = [max(float(value), 1e-12) ** (1.0 / temperature) for value in probability]
    total = sum(values)
    return [value / total for value in values]


def metrics(rows: list[dict], temperature: float = 1.0) -> dict:
    if not rows:
        return {"n": 0}
    brier = log_loss = correct = 0.0
    for row in rows:
        probability = apply_temperature(row["prob"], temperature)
        outcome = int(row["outcome"])
        brier += sum((value - float(index == outcome)) ** 2 for index, value in enumerate(probability))
        log_loss -= math.log(max(probability[outcome], 1e-12))
        correct += int(max(range(len(probability)), key=probability.__getitem__) == outcome)
    n = len(rows)
    return {
        "n": n,
        "multiclass_brier": round(brier / n, 8),
        "log_loss": round(log_loss / n, 8),
        "top1_accuracy_pct": round(correct * 100.0 / n, 2),
    }


def _row_losses(row: dict, temperature: float) -> tuple[float, float]:
    probability = apply_temperature(row["prob"], temperature)
    outcome = int(row["outcome"])
    brier = sum((value - float(index == outcome)) ** 2 for index, value in enumerate(probability))
    log_loss = -math.log(max(probability[outcome], 1e-12))
    return brier, log_loss


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def paired_bootstrap(rows: list[dict], temperature: float, draws: int = 2000, seed: int = 20260821) -> dict:
    """Paired bootstrap CI for candidate-minus-raw metric deltas on same matches."""
    if not rows:
        return {}
    raw = [_row_losses(row, 1.0) for row in rows]
    candidate = [_row_losses(row, temperature) for row in rows]
    rng = random.Random(seed)
    indexes = range(len(rows))

    def summary(metric_index: int) -> dict:
        point = sum(candidate[i][metric_index] - raw[i][metric_index] for i in indexes) / len(rows)
        sampled = []
        for _ in range(draws):
            sampled.append(sum(
                candidate[index][metric_index] - raw[index][metric_index]
                for index in (rng.randrange(len(rows)) for _ in indexes)
            ) / len(rows))
        return {
            "delta_candidate_minus_raw": round(point, 8),
            "ci95_low": round(_quantile(sampled, 0.025), 8),
            "ci95_high": round(_quantile(sampled, 0.975), 8),
        }

    return {"draws": draws, "seed": seed, "brier": summary(0), "log_loss": summary(1)}


def candidate_admission_decision(paired_metrics: dict) -> dict:
    """Return the conservative publication decision for a HAFU candidate.

    A lower point estimate in one metric is not enough: the candidate must
    improve both proper scoring rules and both paired 95% intervals must stay
    below zero on the identical out-of-time matches.
    """
    required = ("brier", "log_loss")
    metrics = [paired_metrics.get(name) for name in required]
    if any(not isinstance(item, dict) for item in metrics):
        return {"decision": "hold", "reason_code": "MISSING_PAIRED_METRICS"}
    if not all(
        isinstance(item.get("delta_candidate_minus_baseline"), (int, float))
        and isinstance(item.get("ci95_high"), (int, float))
        and item["delta_candidate_minus_baseline"] < 0
        and item["ci95_high"] < 0
        for item in metrics
    ):
        return {"decision": "hold", "reason_code": "NO_DUAL_METRIC_IMPROVEMENT"}
    return {"decision": "eligible_for_review", "reason_code": "DUAL_METRIC_IMPROVEMENT"}


def hafu_from_had_odds(had_odds: list[float] | tuple[float, float, float]) -> list[float] | None:
    """Build an independent HAFU shadow vector from pre-match HAD only.

    The official HAFU quote is intentionally not an input.  This makes the
    resulting vector suitable for a paired comparison against the HAFU market,
    rather than an untraceable re-expression of that same nine-state quote.
    """
    try:
        odds = [float(value) for value in had_odds]
    except (TypeError, ValueError):
        return None
    if len(odds) != 3 or any(not math.isfinite(value) or value <= 1.0 for value in odds):
        return None
    core_scripts = Path(__file__).resolve().parents[3] / "core" / "zu-yu-dashi-3" / "scripts"
    if not core_scripts.is_dir():
        return None
    core_path = str(core_scripts)
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    try:
        import predict as core_predict  # type: ignore[import-not-found]
        from market_fit import hafu_probs  # type: ignore[import-not-found]

        market_prob, _ = core_predict.devig(odds, "power")
        lambdas = core_predict.solve_lam_from_probs(market_prob)
        if lambdas is None:
            return None
        probability = hafu_probs(*lambdas, core_predict.matrix, core_predict.RHO_DEFAULT)
    except (ArithmeticError, ImportError, TypeError, ValueError):
        return None
    if len(probability) != len(STATES) or any(not math.isfinite(value) or value < 0 for value in probability):
        return None
    total = sum(probability)
    return [value / total for value in probability] if total > 0 else None


def _vector_metrics(outcomes: list[int], probabilities: list[list[float]]) -> dict:
    if not outcomes:
        return {"n": 0}
    brier = log_loss = correct = 0.0
    for outcome, probability in zip(outcomes, probabilities):
        brier += sum((value - float(index == outcome)) ** 2 for index, value in enumerate(probability))
        log_loss -= math.log(max(probability[outcome], 1e-12))
        correct += int(max(range(len(probability)), key=probability.__getitem__) == outcome)
    n = len(outcomes)
    return {
        "n": n,
        "multiclass_brier": round(brier / n, 8),
        "log_loss": round(log_loss / n, 8),
        "top1_accuracy_pct": round(correct * 100.0 / n, 2),
    }


def _paired_vector_bootstrap(
    outcomes: list[int], baseline: list[list[float]], candidate: list[list[float]],
    draws: int, seed: int,
) -> dict:
    if not outcomes:
        return {}
    raw_losses = [
        (sum((value - float(index == outcome)) ** 2 for index, value in enumerate(probability)),
         -math.log(max(probability[outcome], 1e-12)))
        for outcome, probability in zip(outcomes, baseline)
    ]
    candidate_losses = [
        (sum((value - float(index == outcome)) ** 2 for index, value in enumerate(probability)),
         -math.log(max(probability[outcome], 1e-12)))
        for outcome, probability in zip(outcomes, candidate)
    ]
    rng = random.Random(seed)

    def summary(metric_index: int) -> dict:
        deltas = [candidate_losses[index][metric_index] - raw_losses[index][metric_index]
                  for index in range(len(outcomes))]
        sampled = [sum(deltas[rng.randrange(len(deltas))] for _ in range(len(deltas))) / len(deltas)
                   for _ in range(draws)]
        return {
            "delta_candidate_minus_baseline": round(sum(deltas) / len(deltas), 8),
            "ci95_low": round(_quantile(sampled, 0.025), 8),
            "ci95_high": round(_quantile(sampled, 0.975), 8),
        }

    return {"draws": draws, "seed": seed, "brier": summary(0), "log_loss": summary(1)}


def evaluate_had_derived_shadow(
    matches: list[dict], test_fraction: float = 0.30, draws: int = 2000, seed: int = 20260821,
) -> dict:
    """Compare HAD-only HAFU shadow probabilities against same-match HAFU odds.

    This remains research-only: HAFU is never used to build the candidate, and
    the baseline and candidate share exactly the same post-kickoff outcome.
    """
    rows = []
    for row in extract_rows(matches):
        candidate = hafu_from_had_odds(row.get("had_odds"))
        if candidate is not None:
            rows.append({**row, "candidate_prob": candidate})
    rows.sort(key=lambda row: row["kickoff"])
    if len(rows) < 2:
        raise ValueError("need at least two valid paired HAFU/HAD settlements")
    split = max(1, min(len(rows) - 1, int(len(rows) * (1.0 - test_fraction))))
    test_rows = rows[split:]
    outcomes = [int(row["outcome"]) for row in test_rows]
    baseline = [row["prob"] for row in test_rows]
    candidate = [row["candidate_prob"] for row in test_rows]
    paired = _paired_vector_bootstrap(outcomes, baseline, candidate, draws, seed)
    admission = candidate_admission_decision(paired)
    if len(test_rows) < 200:
        admission = {"decision": "hold", "reason_code": "INSUFFICIENT_OUT_OF_TIME_SAMPLE"}
    return {
        "schema_version": "sporttery-hafu-had-shadow-1.0",
        "research_only": True,
        "source_policy": {
            "baseline": "closing_pre_match.hafu: official nine-state quote",
            "candidate": "closing_pre_match.had only: power devig -> 1X2 lambda inverse -> HAFU convolution",
            "outcome": "match_result_list code=HAFU official settlement",
        },
        "split": {
            "method": "chronological",
            "train_n": split,
            "test_n": len(test_rows),
            "train_through": rows[split - 1]["kickoff"],
            "test_from": test_rows[0]["kickoff"],
        },
        "test": {"baseline": _vector_metrics(outcomes, baseline),
                 "candidate": _vector_metrics(outcomes, candidate)},
        "test_paired_bootstrap": paired,
        "admission": admission,
        "valid_sample_n": len(rows),
    }


def fit_temperature(train_rows: list[dict]) -> tuple[float, float]:
    candidates = [round(0.5 + index * 0.02, 2) for index in range(51)]
    ranked = [(metrics(train_rows, temperature)["log_loss"], temperature) for temperature in candidates]
    score, temperature = min(ranked)
    return temperature, score


def evaluate(matches: list[dict], test_fraction: float = 0.30) -> dict:
    rows = sorted(extract_rows(matches), key=lambda row: row["kickoff"])
    if len(rows) < 2:
        raise ValueError("need at least two valid closing-HAFU settlements")
    split = max(1, min(len(rows) - 1, int(len(rows) * (1.0 - test_fraction))))
    train_rows, test_rows = rows[:split], rows[split:]
    temperature, train_log_loss = fit_temperature(train_rows)
    return {
        "schema_version": "sporttery-hafu-chronological-evaluation-1.0",
        "source_policy": {
            "odds": "closing_pre_match.hafu: last official quote strictly before kickoff",
            "outcome": "match_result_list code=HAFU official settlement",
            "no_full_time_proxy": True,
        },
        "state_labels": list(STATES),
        "split": {
            "method": "chronological",
            "train_n": len(train_rows),
            "test_n": len(test_rows),
            "train_through": train_rows[-1]["kickoff"],
            "test_from": test_rows[0]["kickoff"],
        },
        "temperature": {
            "value": temperature,
            "selection_metric": "train_log_loss",
            "train_log_loss": train_log_loss,
        },
        "metrics": {
            "train_raw": metrics(train_rows),
            "train_temperature": metrics(train_rows, temperature),
            "test_raw": metrics(test_rows),
            "test_temperature": metrics(test_rows, temperature),
        },
        "test_paired_bootstrap": paired_bootstrap(test_rows, temperature),
        "valid_sample_n": len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="official fetch_sporttery_history_all JSON")
    parser.add_argument("--output", required=True)
    parser.add_argument("--test-fraction", type=float, default=0.30)
    parser.add_argument("--had-derived-shadow", action="store_true",
                        help="research-only: compare HAD-derived HAFU with same-match official HAFU baseline")
    parser.add_argument("--draws", type=int, default=2000,
                        help="paired bootstrap draws for --had-derived-shadow")
    args = parser.parse_args()
    if not 0.05 <= args.test_fraction < 0.50:
        parser.error("--test-fraction must be in [0.05, 0.50)")
    if args.draws < 100:
        parser.error("--draws must be >= 100")
    source = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    report = (evaluate_had_derived_shadow(source.get("matches") or [], args.test_fraction, args.draws)
              if args.had_derived_shadow else evaluate(source.get("matches") or [], args.test_fraction))
    report["source_file"] = args.input
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

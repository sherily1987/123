#!/usr/bin/env python3
"""Evaluate derivative football markets without inventing half-time outcomes.

This module is deliberately side-effect free.  The CLI/registry adapter may
prepare rows from prediction snapshots, while this layer makes the scoring
rules explicit and testable:

* over/under is scored from its own binary probability and 90-minute result;
* half/full-time is scored only when a separately verified half-time evidence
  record exists; and
* an ``UNFITTED`` HAFU prediction is excluded rather than reported as a model
  result.
"""

from __future__ import annotations

import math
import argparse
import json
from typing import Any, Iterable, Mapping


HAFU_STATES = ("HH", "HD", "HA", "DH", "DD", "DA", "AH", "AD", "AA")


def _outcome(home: int, away: int) -> str:
    if home > away:
        return "H"
    if home < away:
        return "A"
    return "D"


def hafu_state(score_ht: Mapping[str, Any], score_90: str) -> str:
    """Return the canonical nine-state HT/FT label from verified scores."""
    try:
        ht_home = int(score_ht["home"])
        ht_away = int(score_ht["away"])
        ft_home_text, ft_away_text = str(score_90).split("-", 1)
        ft_home, ft_away = int(ft_home_text), int(ft_away_text)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid half-time or 90-minute score") from exc
    return _outcome(ht_home, ht_away) + _outcome(ft_home, ft_away)


def _probabilities(values: Any, expected: int) -> list[float] | None:
    if not isinstance(values, (list, tuple)) or len(values) != expected:
        return None
    try:
        probs = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if any(value < 0.0 or value > 1.0 for value in probs):
        return None
    total = sum(probs)
    if total <= 0.0:
        return None
    # Some historical HAFU emitters expose relative weights.  Normalizing here
    # is valid for scoring only; it does not promote an UNFITTED output into a
    # production probability (that is handled by _hafu_summary's status gate).
    return [value / total for value in probs]


def _percent_probabilities(values: Any, expected: int) -> list[float] | None:
    """Convert explicit percentage output to probabilities without guessing units."""
    if not isinstance(values, (list, tuple)) or len(values) != expected:
        return None
    try:
        percent = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if any(value < 0.0 or value > 100.0 for value in percent):
        return None
    return [value / 100.0 for value in percent]


def row_from_prediction(prediction: Mapping[str, Any], settled: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract only derivative fields from a registered prediction and 90-minute result.

    A missing calibration state is deliberately represented as ``UNFITTED``.
    That makes historical HAFU output visible in the exclusion count but never
    silently turns it into a scored model result.
    """
    score = settled.get("score_90")
    if not isinstance(score, Mapping):
        return None
    try:
        home, away = int(score["home"]), int(score["away"])
    except (KeyError, TypeError, ValueError):
        return None
    output = prediction.get("output")
    if not isinstance(output, Mapping):
        return None
    core = output.get("core_output") if isinstance(output.get("core_output"), Mapping) else output
    forecast = output.get("forecast") if isinstance(output.get("forecast"), Mapping) else core.get("forecast", {})
    if not isinstance(forecast, Mapping):
        forecast = {}

    def derivative(name: str) -> Mapping[str, Any]:
        for container in (forecast, core, output):
            value = container.get(name) if isinstance(container, Mapping) else None
            if isinstance(value, Mapping):
                return value
        return {}

    hafu = derivative("hafu_model")
    row: dict[str, Any] = {
        "match_id": str(prediction.get("match_id") or ""),
        "actual_score": f"{home}-{away}",
    }
    hafu_probs = _percent_probabilities(hafu.get("prob_pct"), len(HAFU_STATES))
    if hafu_probs is not None:
        row["hafu_probs"] = hafu_probs
        row["hafu_status"] = str(hafu.get("calibration_status") or "UNFITTED")
    for field, key, threshold in (("ou_2_5", "ou25", 2.5), ("ou_3_5", "ou35", 3.5)):
        market = derivative(field)
        try:
            over = float(market["over_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 <= over <= 100.0:
            row[key] = {"over": over / 100.0, "actual": int(home + away > threshold)}
            calibration = market.get("calibration")
            raw = calibration.get("uncalibrated_over_pct") if isinstance(calibration, Mapping) else None
            try:
                raw = float(raw)
            except (TypeError, ValueError):
                raw = None
            if raw is not None and 0.0 <= raw <= 100.0:
                row[f"{key}_raw"] = {"over": raw / 100.0, "actual": int(home + away > threshold)}
    return row


def _binary_summary(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, float | int | None]:
    briers: list[float] = []
    hits: list[bool] = []
    for row in rows:
        market = row.get(key)
        if not isinstance(market, Mapping):
            continue
        try:
            probability = float(market["over"])
            actual = int(market["actual"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0.0 <= probability <= 1.0 or actual not in (0, 1):
            continue
        briers.append((probability - actual) ** 2)
        hits.append((probability >= 0.5) == bool(actual))
    if not briers:
        return {"n": 0, "brier": None, "accuracy_pct": None}
    return {
        "n": len(briers),
        "brier": round(sum(briers) / len(briers), 6),
        "accuracy_pct": round(100.0 * sum(hits) / len(hits), 2),
    }


def _hafu_summary(
    rows: Iterable[Mapping[str, Any]], evidence_by_match: Mapping[str, Mapping[str, Any]]
) -> dict[str, float | int | None]:
    briers: list[float] = []
    log_losses: list[float] = []
    hits: list[bool] = []
    excluded_unverified = 0
    excluded_unfitted = 0

    for row in rows:
        raw_probs = row.get("hafu_probs")
        if raw_probs is None:
            continue
        if str(row.get("hafu_status", "")).upper() == "UNFITTED":
            excluded_unfitted += 1
            continue
        probs = _probabilities(raw_probs, len(HAFU_STATES))
        if probs is None:
            excluded_unfitted += 1
            continue
        evidence = evidence_by_match.get(str(row.get("match_id")), {})
        if evidence.get("status") != "verified":
            excluded_unverified += 1
            continue
        try:
            actual_state = hafu_state(evidence["score_ht"], str(row["actual_score"]))
            actual_index = HAFU_STATES.index(actual_state)
        except (KeyError, TypeError, ValueError):
            excluded_unverified += 1
            continue
        briers.append(sum((probability - int(index == actual_index)) ** 2 for index, probability in enumerate(probs)))
        log_losses.append(-math.log(max(probs[actual_index], 1e-15)))
        hits.append(max(range(len(probs)), key=probs.__getitem__) == actual_index)

    if not briers:
        return {
            "n": 0,
            "accuracy_pct": None,
            "brier": None,
            "log_loss": None,
            "excluded_unverified_evidence": excluded_unverified,
            "excluded_unfitted_prediction": excluded_unfitted,
        }
    return {
        "n": len(briers),
        "accuracy_pct": round(100.0 * sum(hits) / len(hits), 2),
        "brier": round(sum(briers) / len(briers), 6),
        "log_loss": round(sum(log_losses) / len(log_losses), 6),
        "excluded_unverified_evidence": excluded_unverified,
        "excluded_unfitted_prediction": excluded_unfitted,
    }


def _temperature_scale(probs: list[float], temperature: float) -> list[float]:
    """Apply a probability temperature without changing the state ordering."""
    if temperature <= 0.0:
        raise ValueError("temperature must be > 0")
    weights = [max(probability, 1e-15) ** (1.0 / temperature) for probability in probs]
    total = sum(weights)
    return [weight / total for weight in weights]


def _hafu_metrics_for_labeled_rows(
    labeled_rows: Iterable[tuple[list[float], int]],
) -> dict[str, float | int | None]:
    """Score already-validated HAFU probabilities on one fixed sample set."""
    briers: list[float] = []
    log_losses: list[float] = []
    hits: list[bool] = []
    for probs, actual_index in labeled_rows:
        briers.append(sum((probability - int(index == actual_index)) ** 2
                          for index, probability in enumerate(probs)))
        log_losses.append(-math.log(max(probs[actual_index], 1e-15)))
        hits.append(max(range(len(probs)), key=probs.__getitem__) == actual_index)
    if not briers:
        return {"n": 0, "accuracy_pct": None, "brier": None, "log_loss": None}
    return {
        "n": len(briers),
        "accuracy_pct": round(100.0 * sum(hits) / len(hits), 2),
        "brier": round(sum(briers) / len(briers), 6),
        "log_loss": round(sum(log_losses) / len(log_losses), 6),
    }


def hafu_temperature_shadow(
    rows: Iterable[Mapping[str, Any]],
    evidence_by_match: Mapping[str, Mapping[str, Any]],
    *,
    temperature: float,
) -> dict[str, Any]:
    """Research-only temperature comparison on independently verified HAFU rows.

    This deliberately bypasses the production ``UNFITTED`` status *only for a
    named shadow experiment*.  It does not alter the formal HAFU denominator
    returned by :func:`evaluate_derivatives` or make the candidate eligible
    for production use.
    """
    if temperature <= 0.0:
        raise ValueError("temperature must be > 0")
    labeled: list[tuple[list[float], int]] = []
    for row in rows:
        probs = _probabilities(row.get("hafu_probs"), len(HAFU_STATES))
        if probs is None:
            continue
        evidence = evidence_by_match.get(str(row.get("match_id")), {})
        if evidence.get("status") != "verified":
            continue
        try:
            actual_state = hafu_state(evidence["score_ht"], str(row["actual_score"]))
            labeled.append((probs, HAFU_STATES.index(actual_state)))
        except (KeyError, TypeError, ValueError):
            continue
    raw = _hafu_metrics_for_labeled_rows(labeled)
    candidate = _hafu_metrics_for_labeled_rows(
        [(_temperature_scale(probs, temperature), actual_index) for probs, actual_index in labeled]
    )
    raw_brier, candidate_brier = raw["brier"], candidate["brier"]
    raw_loss, candidate_loss = raw["log_loss"], candidate["log_loss"]
    return {
        "research_only": True,
        "n": len(labeled),
        "temperature": temperature,
        "raw": raw,
        "candidate": candidate,
        "delta_candidate_minus_raw": {
            "brier": (round(float(candidate_brier) - float(raw_brier), 6)
                      if raw_brier is not None and candidate_brier is not None else None),
            "log_loss": (round(float(candidate_loss) - float(raw_loss), 6)
                         if raw_loss is not None and candidate_loss is not None else None),
        },
    }


def ou_calibration_comparison(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, float | int | None]:
    """Compare calibrated and raw O/U only where both came from one snapshot."""
    calibrated_losses: list[float] = []
    raw_losses: list[float] = []
    for row in rows:
        calibrated, raw = row.get(key), row.get(f"{key}_raw")
        if not isinstance(calibrated, Mapping) or not isinstance(raw, Mapping):
            continue
        try:
            c_prob, c_actual = float(calibrated["over"]), int(calibrated["actual"])
            r_prob, r_actual = float(raw["over"]), int(raw["actual"])
        except (KeyError, TypeError, ValueError):
            continue
        if (c_actual not in (0, 1) or r_actual != c_actual
                or not 0.0 <= c_prob <= 1.0 or not 0.0 <= r_prob <= 1.0):
            continue
        calibrated_losses.append((c_prob - c_actual) ** 2)
        raw_losses.append((r_prob - c_actual) ** 2)
    if not calibrated_losses:
        return {"n": 0, "calibrated_brier": None, "raw_brier": None,
                "delta_calibrated_minus_raw": None}
    calibrated_brier = sum(calibrated_losses) / len(calibrated_losses)
    raw_brier = sum(raw_losses) / len(raw_losses)
    return {"n": len(calibrated_losses), "calibrated_brier": round(calibrated_brier, 6),
            "raw_brier": round(raw_brier, 6),
            "delta_calibrated_minus_raw": round(calibrated_brier - raw_brier, 6)}


def evaluate_derivatives(
    rows: Iterable[Mapping[str, Any]], evidence_by_match: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, float | int | None]]:
    """Score O/U and HAFU with independent denominators and exclusions."""
    materialized = list(rows)
    return {
        "ou_2_5": _binary_summary(materialized, "ou25"),
        "ou_3_5": _binary_summary(materialized, "ou35"),
        "ou_calibration_comparison": {
            "ou_2_5": ou_calibration_comparison(materialized, "ou25"),
            "ou_3_5": ou_calibration_comparison(materialized, "ou35"),
        },
        "hafu": _hafu_summary(materialized, evidence_by_match),
    }


def _load_evidence(path: str | None) -> dict[str, Mapping[str, Any]]:
    if not path:
        return {}
    raw = json.loads(open(path, encoding="utf-8").read())
    rows = raw.get("rows", []) if isinstance(raw, Mapping) else raw
    if not isinstance(rows, list):
        raise ValueError("half-time evidence must be a JSON list or {rows: [...]}")
    return {str(row.get("match_id")): row for row in rows
            if isinstance(row, Mapping) and row.get("match_id") is not None}


def load_registered_rows(store: str, snapshot_policy: str) -> list[dict[str, Any]]:
    """Load one registered, scored snapshot per match from the authoritative store."""
    # Kept as a local import: this module remains importable for pure metric
    # tests without requiring the full production router and runtime paths.
    from fusion_backtest import (  # type: ignore[import-not-found]
        dedupe_snapshot_rows, load_jsonl, resolve_path, select_primary_rows,
    )
    from pathlib import Path

    root = Path(store)
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            continue
        try:
            prediction = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        match_id = str(prediction.get("match_id") or "")
        result_path = root / "results" / f"{match_id}.json"
        if not result_path.exists():
            continue
        try:
            settled = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if settled.get("status") != "finished" or settled.get("settlement_scope") != "90min":
            continue
        row = row_from_prediction(prediction, settled)
        if row is None:
            continue
        # Selection helpers need these common snapshot fields, while the
        # diagnostic does not expose them as metrics.
        row.update({"created_at": prediction.get("created_at") or "",
                    "snapshot_type": prediction.get("snapshot_type"),
                    "match_id": match_id})
        candidates.append((prediction, row))
    deduped, _ = dedupe_snapshot_rows([row for _, row in candidates])
    selected = select_primary_rows(deduped, snapshot_policy)
    return selected


def main() -> None:
    from runtime_paths import backtest_store  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser(description="独立评测大小球与半全场；半全场只接受已核验半场证据")
    parser.add_argument("--store", default=str(backtest_store()))
    parser.add_argument("--half-time-evidence", help="half_time_enrichment.py 写出的 JSON")
    parser.add_argument("--hafu-shadow-temperature", type=float,
                        help="研究用：在同一已核验样本上比较HAFU温度候选，不改变正式指标")
    parser.add_argument("--snapshot-policy", choices=("latest_before_kickoff", "prematch", "closing"),
                        default="latest_before_kickoff")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = load_registered_rows(args.store, args.snapshot_policy)
    evidence = _load_evidence(args.half_time_evidence)
    metrics = evaluate_derivatives(rows, evidence)
    if args.hafu_shadow_temperature is not None:
        metrics["hafu_temperature_shadow"] = hafu_temperature_shadow(
            rows, evidence, temperature=args.hafu_shadow_temperature
        )
    report = {
        "schema": "derivative-diagnostics-1.0",
        "research_only": True,
        "store": args.store,
        "snapshot_policy": args.snapshot_policy,
        "record_sample_size": len(rows),
        "metrics": metrics,
        "half_time_evidence_input": args.half_time_evidence,
        "note": "半全场只在status=verified的独立半场证据上评分；UNFITTED输出不进入分母。",
    }
    from pathlib import Path
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(target), "metrics": report["metrics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Research-only comparison of each Sporttery pool with a HAD-derived model.

The official closing odds for TTG, CRS and HAFU are evaluated on their own
settlement space.  The paired candidate uses only the same-match closing HAD
odds, inverted to a score matrix.  No production configuration is changed.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from runtime_paths import core_scripts_dir

CORE = str(core_scripts_dir())
if CORE not in sys.path:
    sys.path.insert(0, CORE)
import predict  # noqa: E402
from market_fit import hafu_probs, total_probs  # noqa: E402

HAFU_LABELS = ["H:H", "H:D", "H:A", "D:H", "D:D", "D:A", "A:H", "A:D", "A:A"]
CRS_OTHER_KEYS = {"s-1sh": "-1:-H", "s-1sd": "-1:-D", "s-1sa": "-1:-A"}


def result_for(match: dict, code: str) -> str | None:
    wanted = code.upper()
    for item in match.get("match_result_list") or []:
        if str(item.get("code") or "").upper() == wanted:
            return str(item.get("combination") or "") or None
    return None


def valid_odds(values: list[object]) -> list[float] | None:
    try:
        odds = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if not odds or any(not math.isfinite(value) or value <= 1.0 for value in odds):
        return None
    return odds


def devig(values: list[object]) -> tuple[list[float], float] | None:
    odds = valid_odds(values)
    if odds is None:
        return None
    try:
        probabilities, margin = predict.devig(odds, "power")
    except (ArithmeticError, TypeError, ValueError):
        return None
    if len(probabilities) != len(odds) or any(not math.isfinite(value) or value < 0 for value in probabilities):
        return None
    return [float(value) for value in probabilities], float(margin)


def had_matrix(match: dict) -> dict | None:
    had = (match.get("closing_pre_match") or {}).get("had") or {}
    converted = devig([had.get("h"), had.get("d"), had.get("a")])
    if converted is None:
        return None
    probability, _ = converted
    lambdas = predict.solve_lam_from_probs(probability)
    if lambdas is None:
        return None
    return predict.matrix(*lambdas, predict.RHO_DEFAULT)


def direct_had(match: dict) -> dict | None:
    had = (match.get("closing_pre_match") or {}).get("had") or {}
    converted = devig([had.get("h"), had.get("d"), had.get("a")])
    outcome = result_for(match, "HAD")
    if converted is None or outcome not in {"H", "D", "A"}:
        return None
    probability, margin = converted
    return {"labels": ["H", "D", "A"], "direct": probability,
            "actual": ["H", "D", "A"].index(outcome), "margin": margin}


def direct_ttg(match: dict, matrix: dict) -> dict | None:
    row = (match.get("closing_pre_match") or {}).get("ttg") or {}
    labels = [str(index) for index in range(7)] + ["7+"]
    converted = devig([row.get(f"s{index}") for index in range(8)])
    outcome = result_for(match, "TTG")
    if converted is None or outcome not in labels:
        return None
    direct, margin = converted
    return {"labels": labels, "direct": direct, "had_derived": total_probs(matrix),
            "actual": labels.index(outcome), "margin": margin}


def direct_hafu(match: dict, matrix: dict) -> dict | None:
    row = (match.get("closing_pre_match") or {}).get("hafu") or {}
    keys = [label.replace(":", "").lower() for label in HAFU_LABELS]
    converted = devig([row.get(key) for key in keys])
    outcome = result_for(match, "HAFU")
    if converted is None or outcome not in HAFU_LABELS:
        return None
    direct, margin = converted
    lambdas = predict.solve_lam_from_probs(
        devig([(match.get("closing_pre_match") or {}).get("had", {}).get(key) for key in ("h", "d", "a")])[0]
    )
    if lambdas is None:
        return None
    derived = hafu_probs(*lambdas, predict.matrix, predict.RHO_DEFAULT)
    total = sum(derived)
    if total <= 0:
        return None
    return {"labels": HAFU_LABELS, "direct": direct,
            "had_derived": [value / total for value in derived],
            "actual": HAFU_LABELS.index(outcome), "margin": margin}


def crs_market(row: dict) -> tuple[list[str], list[float], float] | None:
    values = {}
    for key, value in row.items():
        if len(key) == 6 and key[0] == "s" and key[3] == "s" and not key.endswith("f"):
            try:
                values[f"{int(key[1:3])}:{int(key[4:6])}"] = float(value)
            except (TypeError, ValueError):
                pass
    for key, label in CRS_OTHER_KEYS.items():
        try:
            values[label] = float(row[key])
        except (KeyError, TypeError, ValueError):
            pass
    labels = sorted(values)
    converted = devig([values[label] for label in labels])
    if converted is None or not all(label in labels for label in CRS_OTHER_KEYS.values()):
        return None
    probability, margin = converted
    return labels, probability, margin


def crs_bucket(home: int, away: int, labels: set[str]) -> str:
    exact = f"{home}:{away}"
    if exact in labels:
        return exact
    return "-1:-H" if home > away else ("-1:-D" if home == away else "-1:-A")


def direct_crs(match: dict, matrix: dict) -> dict | None:
    parsed = crs_market((match.get("closing_pre_match") or {}).get("crs") or {})
    outcome = result_for(match, "CRS")
    if parsed is None:
        return None
    labels, direct, margin = parsed
    if outcome not in labels:
        return None
    label_set = set(labels)
    derived_by_label = {label: 0.0 for label in labels}
    for (home, away), probability in matrix.items():
        derived_by_label[crs_bucket(int(home), int(away), label_set)] += float(probability)
    derived = [derived_by_label[label] for label in labels]
    total = sum(derived)
    if total <= 0:
        return None
    return {"labels": labels, "direct": direct,
            "had_derived": [value / total for value in derived],
            "actual": labels.index(outcome), "margin": margin}


def losses(row: dict, key: str) -> tuple[float, float]:
    probability = row[key]
    actual = int(row["actual"])
    return (sum((value - float(index == actual)) ** 2 for index, value in enumerate(probability)),
            -math.log(max(float(probability[actual]), 1e-12)))


def metrics(rows: list[dict], key: str) -> dict:
    if not rows:
        return {"n": 0}
    scored = [losses(row, key) for row in rows]
    correct = sum(max(range(len(row[key])), key=row[key].__getitem__) == int(row["actual"]) for row in rows)
    return {"n": len(rows), "multiclass_brier": round(sum(x[0] for x in scored) / len(rows), 8),
            "log_loss": round(sum(x[1] for x in scored) / len(rows), 8),
            "top1_accuracy_pct": round(correct * 100.0 / len(rows), 2)}


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lo, hi = int(position), math.ceil(position)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def paired_bootstrap(rows: list[dict], draws: int, seed: int) -> dict:
    deltas = []
    for row in rows:
        direct = losses(row, "direct")
        derived = losses(row, "had_derived")
        deltas.append((direct[0] - derived[0], direct[1] - derived[1]))
    rng = random.Random(seed)

    def summarize(index: int) -> dict:
        values = [delta[index] for delta in deltas]
        samples = [sum(values[rng.randrange(len(values))] for _ in values) / len(values) for _ in range(draws)]
        return {"delta_direct_minus_had": round(sum(values) / len(values), 8),
                "ci95_low": round(quantile(samples, 0.025), 8),
                "ci95_high": round(quantile(samples, 0.975), 8)}

    return {"n": len(rows), "draws": draws, "seed": seed,
            "brier": summarize(0), "log_loss": summarize(1)}


def temporal_holdout(rows: list[dict], fraction: float = 0.30) -> tuple[list[dict], dict]:
    days = sorted({row["day"] for row in rows})
    split = max(1, min(len(days) - 1, int(len(days) * (1.0 - fraction))))
    test_from = days[split]
    return [row for row in rows if row["day"] >= test_from], {
        "method": "last_30pct_kickoff_date_groups", "date_groups": len(days),
        "test_from": test_from,
    }


def compare(rows: list[dict], draws: int, seed: int) -> dict:
    test, split = temporal_holdout(rows)
    paired = paired_bootstrap(test, draws, seed)
    both_better = all(paired[name]["ci95_high"] < 0 for name in ("brier", "log_loss"))
    both_worse = all(paired[name]["ci95_low"] > 0 for name in ("brier", "log_loss"))
    decision = "direct_market_better" if both_better else ("had_derived_better" if both_worse else "inconclusive")
    if len(test) < 200:
        decision = "insufficient_holdout_sample"
    return {"full_n": len(rows), "average_direct_overround_pct": round(sum(row["margin"] for row in rows) / len(rows) * 100, 3),
            "holdout": {**split, "n": len(test), "direct_market": metrics(test, "direct"),
                        "had_derived": metrics(test, "had_derived"), "paired": paired,
                        "decision": decision}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap-draws", type=int, default=2000)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    families = {"had": [], "ttg": [], "crs": [], "hafu": []}
    for match in source.get("matches") or []:
        day = str(match.get("kickoff_iso") or "")[:10]
        if not day:
            continue
        had = direct_had(match)
        if had is not None:
            families["had"].append({**had, "day": day, "match_id": match.get("matchId")})
        matrix = had_matrix(match)
        if matrix is None:
            continue
        for name, builder in (("ttg", direct_ttg), ("crs", direct_crs), ("hafu", direct_hafu)):
            row = builder(match, matrix)
            if row is not None:
                families[name].append({**row, "day": day, "match_id": match.get("matchId")})
    had_test, had_split = temporal_holdout(families["had"])
    report = {
        "schema_version": "market-specific-odds-evaluation-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_config_changed": False,
        "source_policy": {
            "odds": "official Sporttery last quote strictly before kickoff",
            "outcome": "official pool-specific settlement",
            "candidate": "closing HAD only -> power devig -> lambda inversion -> matching pool state space",
            "delta_semantics": "negative direct_minus_had means the pool's own odds are better",
        },
        "had": {"full_n": len(families["had"]), "holdout": {**had_split, "n": len(had_test),
                 "direct_market": metrics(had_test, "direct")}},
        "ttg": compare(families["ttg"], args.bootstrap_draws, 20260824),
        "crs": compare(families["crs"], args.bootstrap_draws, 20260825),
        "hafu": compare(families["hafu"], args.bootstrap_draws, 20260826),
        "guardrails": [
            "This comparison tests direct pool odds against HAD-only derivation, not profitability.",
            "TTG and HAFU already enter the production multi-market lambda fit when fresh; CRS currently remains audit-only.",
            "A point estimate without paired dual-metric confidence intervals is not an admission decision.",
        ],
        "input": str(args.input),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

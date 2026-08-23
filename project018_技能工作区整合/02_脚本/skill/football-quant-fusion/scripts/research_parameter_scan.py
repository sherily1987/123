#!/usr/bin/env python3
"""Research-only K/T parameter scan over settled fusion predictions.

This script intentionally never edits production configuration, prediction
records, or the current cohort.  It selects one latest-before-kickoff settled
snapshot per match, uses chronological 70/30 train/test groups, and scans the
same draw-multiplier + exponent-temperature transform used by the core engine.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fusion_backtest as fb  # noqa: E402
from fusion_predict_core import build_identity  # noqa: E402


DEFAULT_STORE = fb.DEFAULT_STORE
DEFAULT_OUTPUT = (
    HERE.parents[3]
    / "06_复盘"
    / "2026-08-23_参数扫描"
    / "历史结算_KT扫描_research_only.json"
)


def calibrate_kt(probabilities: list[float], draw_k: float, temperature: float) -> list[float]:
    """Match core ``predict.calibrate_1x2``: draw multiplier then q**T."""
    if len(probabilities) != 3 or temperature <= 0:
        return list(probabilities)
    q = [float(probabilities[0]), float(probabilities[1]) * float(draw_k), float(probabilities[2])]
    total = sum(q)
    if total <= 0:
        return list(probabilities)
    q = [max(0.0, x / total) ** float(temperature) for x in q]
    total = sum(q)
    return [x / total for x in q] if total > 0 else list(probabilities)


def metric(probabilities: list[list[float]], actual: list[int]) -> dict:
    if not probabilities:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy_pct": None, "ece": None}
    brier = []
    log_loss = []
    hits = []
    observations = []
    for probs, idx in zip(probabilities, actual):
        brier.append(sum((p - (1.0 if i == idx else 0.0)) ** 2 for i, p in enumerate(probs)))
        log_loss.append(-math.log(max(1e-12, min(1.0 - 1e-12, probs[idx]))))
        hits.append(int(max(range(3), key=lambda i: probs[i]) == idx))
        observations.extend((p, int(i == idx)) for i, p in enumerate(probs))
    ece = 0.0
    for bucket in range(10):
        lo, hi = bucket / 10.0, (bucket + 1) / 10.0
        group = [(p, y) for p, y in observations if lo <= p < (hi if bucket < 9 else 1.000001)]
        if group:
            ece += len(group) / len(observations) * abs(
                sum(p for p, _ in group) / len(group) - sum(y for _, y in group) / len(group)
            )
    return {
        "n": len(probabilities),
        "brier": round(sum(brier) / len(brier), 8),
        "log_loss": round(sum(log_loss) / len(log_loss), 8),
        "accuracy_pct": round(sum(hits) / len(hits) * 100.0, 3),
        "ece": round(ece, 8),
    }


def _date_key(row: dict) -> str:
    return str(row.get("kickoff") or "")[:10]


def _split_chronological(rows: list[dict], ratio: float = 0.7) -> tuple[list[dict], list[dict], dict]:
    ordered = sorted(rows, key=lambda r: (str(r.get("kickoff") or ""), str(r.get("match_id") or "")))
    dates = sorted({_date_key(row) for row in ordered if _date_key(row)})
    split = max(1, min(len(dates) - 1, int(len(dates) * ratio))) if len(dates) > 1 else len(dates)
    train_dates, test_dates = set(dates[:split]), set(dates[split:])
    train = [row for row in ordered if _date_key(row) in train_dates]
    test = [row for row in ordered if _date_key(row) in test_dates]
    return train, test, {
        "date_groups": len(dates),
        "train_date_groups": len(train_dates),
        "test_date_groups": len(test_dates),
        "train_date_range": [min(train_dates), max(train_dates)] if train_dates else [],
        "test_date_range": [min(test_dates), max(test_dates)] if test_dates else [],
    }


def _apply(rows: list[dict], draw_k: float, temperature: float, source: str) -> tuple[list[list[float]], list[int]]:
    probs, actual = [], []
    for row in rows:
        p = row.get(source)
        if isinstance(p, list) and len(p) == 3:
            probs.append(calibrate_kt(p, draw_k, temperature))
            actual.append(int(row["actual_idx"]))
    return probs, actual


def _scan(rows: list[dict], grid: list[tuple[float, float]], source: str) -> dict:
    train, test, split = _split_chronological(rows)
    candidates = []
    for draw_k, temperature in grid:
        train_p, train_y = _apply(train, draw_k, temperature, source)
        test_p, test_y = _apply(test, draw_k, temperature, source)
        train_metrics = metric(train_p, train_y)
        test_metrics = metric(test_p, test_y)
        candidates.append({
            "draw_k": draw_k,
            "temperature": temperature,
            "train": train_metrics,
            "test": test_metrics,
        })
    selected = {}
    for objective in ("brier", "log_loss", "ece"):
        selected[objective] = min(
            candidates,
            key=lambda x: (x["train"][objective] if x["train"][objective] is not None else float("inf"), x["draw_k"], x["temperature"]),
        )
    default = next(x for x in candidates if x["draw_k"] == 1.14 and x["temperature"] == 0.96)
    no_cal = next(x for x in candidates if x["draw_k"] == 1.0 and x["temperature"] == 1.0)
    return {
        "source": source,
        "n": len(rows),
        "eligible_n": sum(isinstance(row.get(source), list) and len(row.get(source)) == 3 for row in rows),
        "split": split,
        "default_1.14_0.96": default,
        "no_calibration_1.0_1.0": no_cal,
        "selected_by_train_objective": selected,
        "grid_size": len(candidates),
        "grid": candidates,
    }


def _route_from_record(record: dict) -> str:
    output = record.get("output") or {}
    core = output.get("core_output") or output
    return str(core.get("mode") or output.get("mode") or (record.get("model") or {}).get("mode") or "unknown")


def load_rows(store: Path) -> tuple[list[dict], dict]:
    raw_rows = []
    records_by_prediction = {}
    registry = store / "registry.jsonl"
    for line in registry.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        path = fb.resolve_path(entry.get("path", ""), store)
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        row, error = fb.score_record(record, store)
        if row is None:
            continue
        row["route"] = _route_from_record(record)
        records_by_prediction[row.get("prediction_id")] = record
        raw_rows.append(row)
    snapshots, dropped = fb.dedupe_snapshot_rows(raw_rows)
    snapshots = fb.attach_clv(snapshots)
    rows = fb.select_primary_rows(snapshots, "latest_before_kickoff")
    identity = build_identity()
    for row in rows:
        row["version_cohort"] = fb.version_cohort(row, identity)
    return rows, {
        "registry_readable_scored_records": len(raw_rows),
        "snapshot_records": len(snapshots),
        "primary_unique_matches": len(rows),
        "deduped_duplicates": len(dropped),
        "current_identity": identity,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="research-only historical K/T scan")
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    store = Path(args.store)
    rows, load_meta = load_rows(store)
    grid = [(k / 100.0, t / 100.0) for k in range(85, 141, 5) for t in range(85, 121, 5)]
    # The production point and the no-calibration point are explicit anchors;
    # neither is guaranteed to fall on the 0.05 grid.
    grid.extend([(1.14, 0.96), (1.0, 1.0)])
    grid = sorted(set(grid))
    independent = [row for row in rows if row.get("route") in {"model_first", "hybrid"}]
    market_only = [row for row in rows if row.get("route") == "market_only"]
    report = {
        "schema_version": "research-parameter-scan-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_config_changed": False,
        "scope": {
            "store": str(store),
            "selection": "latest_before_kickoff; one settled 90-minute result per match",
            "time_split": "chronological 70/30 by kickoff date groups",
            "transform": "draw multiplier K followed by q**T, matching core calibrate_1x2",
            "grid": {"draw_k": [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40], "temperature": [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]},
        },
        "load": load_meta,
        "route_counts": dict(Counter(row.get("route", "unknown") for row in rows)),
        "cohort_counts": dict(Counter(row.get("version_cohort", "unknown") for row in rows)),
        "full_sample": fb.summarize(rows),
        "full_sample_paired_market": fb.paired_market_comparison(rows, iterations=2000, seed=20260823),
        "independent_routes": {
            "n": len(independent),
            "summary": fb.summarize(independent),
            "paired_market": fb.paired_market_comparison(independent, iterations=2000, seed=20260823),
        },
        "market_only": {
            "n": len(market_only),
            "summary": fb.summarize(market_only),
            "paired_market": fb.paired_market_comparison(market_only, iterations=2000, seed=20260823),
        },
        "kt_scan_on_market_anchor": _scan([r for r in rows if isinstance(r.get("market_probs"), list)], grid, "market_probs"),
        "guardrails": [
            "研究结果不得写入生产配置、正式预测登记或 current cohort。",
            "market_only 样本是市场校准诊断，不证明独立模型增益。",
            "参数选择只在训练日期组进行，测试日期组只作样本外观察；本报告不能直接发布参数。",
            "当前 m4 cohort 的已结算样本仍为0，不能据此解锁生产校准。",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selected = report["kt_scan_on_market_anchor"]["selected_by_train_objective"]
    print(json.dumps({
        "status": "ok",
        "research_only": True,
        "n": len(rows),
        "route_counts": report["route_counts"],
        "independent_n": len(independent),
        "selected": {k: {"draw_k": v["draw_k"], "temperature": v["temperature"], "test": v["test"]} for k, v in selected.items()},
        "output": str(output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

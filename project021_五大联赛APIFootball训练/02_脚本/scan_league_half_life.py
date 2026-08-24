#!/usr/bin/env python3
"""Strict rolling half-life scan for leagues with closing odds."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


strength = _load("team_strength_scan", ROOT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts" / "team_strength.py")
training = _load("train_scan", HERE / "train_five_leagues.py")


def summarize(rep: dict) -> dict:
    model = rep.get("model") or {}
    market = rep.get("closing_market") or {}
    return {
        "n": rep.get("n"),
        "skip": rep.get("skip"),
        "brier": model.get("brier_mean"),
        "log_loss": model.get("log_loss"),
        "accuracy_pct": model.get("accuracy_pct"),
        "market_brier": market.get("brier_mean"),
        "frequency_brier": (rep.get("frequency_baseline") or {}).get("brier_mean"),
    }


def scan_one(project: Path, slug: str, league_id: str, name: str, half_lives: list[float]) -> dict:
    src = project / "04_素材" / "标准化" / f"{slug}_events.jsonl"
    raw = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    first, second = training.time_cutoffs(raw)
    matches = strength.load_matches(src, league_id=league_id, require_odds=False)
    validation, test = {}, {}
    for hl in half_lives:
        val = strength.walk_forward_validate(matches, first, to_day=second, step_days=30,
                                             half_life=hl, baseline_key="closing_market",
                                             baseline_label="closing_market", min_train=200)
        tst = strength.walk_forward_validate(matches, second, to_day=None, step_days=30,
                                             half_life=hl, baseline_key="closing_market",
                                             baseline_label="closing_market", min_train=200)
        validation[str(hl)] = summarize(val)
        test[str(hl)] = summarize(tst)
    scored = [(float(k), v) for k, v in validation.items()
              if isinstance(v.get("brier"), float) and isinstance(v.get("log_loss"), float)]
    best = min(scored, key=lambda item: (item[1]["brier"], item[1]["log_loss"]))[0] if scored else None
    return {"league": {"slug": slug, "id": league_id, "name": name},
            "cutoffs": {"validation_from": first, "test_from": second},
            "half_lives": half_lives, "validation": validation, "validation_best": best,
            "test": test, "xg_status": "UNAVAILABLE"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--half-lives", nargs="*", type=float, default=[120, 240, 365, 500])
    args = ap.parse_args()
    leagues = [("fd_usa", "USA", "美职联"), ("fd_bra", "BRA", "巴甲")]
    results = [scan_one(args.project, *league, args.half_lives) for league in leagues]
    payload = {"protocol": "rolling walk-forward; validation selects half-life; test is held out",
               "baseline": "football-data.co.uk closing odds", "results": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()

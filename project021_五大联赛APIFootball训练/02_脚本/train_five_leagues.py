#!/usr/bin/env python3
"""Train candidate per-league Dixon-Coles models from prematch-safe event results."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


strength = _load("team_strength", ROOT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts" / "team_strength.py")
audit = _load("league_training_audit", ROOT / "project007_APIFootball数据接入" / "02_脚本" / "league_training_audit.py")


def time_cutoffs(rows: list[dict]) -> tuple[int, int]:
    days = sorted(strength.parse_day(row.get("kickoff")) for row in rows if strength.parse_day(row.get("kickoff")) is not None)
    if len(days) < 5:
        raise ValueError("insufficient_completed_rows_for_time_split")

    def boundary(fraction: float) -> int:
        index = int(len(days) * fraction)
        while index < len(days) and index > 0 and days[index] == days[index - 1]:
            index += 1
        if index >= len(days):
            raise ValueError("cannot_create_nonempty_time_split")
        return days[index]

    first, second = boundary(0.6), boundary(0.8)
    if first >= second:
        raise ValueError("time_split_boundaries_not_increasing")
    return first, second


def train_one_league(input_path: Path, league: dict, output_dir: Path, baseline_key: str = "market", baseline_label: str = "market") -> dict:
    raw_rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in raw_rows:
        audit.validate_prematch_record(row)
    # kind 由 catalog 提供：洲际赛事（UCL/UEL）不是国内联赛，审计会判 excluded。
    # 硬编码 "domestic_league" 会把洲际赛事误当联赛训练，绕过该规则。
    eligibility = audit.classify(raw_rows, league.get("kind", "domestic_league"))
    # lifecycle 反映"是否实际训练出了模型"，不代表单场质量判断——弱联赛（未跑赢频率
    # 基线等）仍标 production，因为质量分级是 predict_no_odds.py 的分档裁决（tier
    # A/B/C/D + 可用/降级/拒绝）的职责，两套机制不重叠，不在这里重复编码。
    result = {"league": league, "eligibility": eligibility, "lifecycle": "candidate"}
    if eligibility["tier"] != "independent":
        result["status"] = "not_trained"
        return result
    first, second = time_cutoffs(raw_rows)
    matches = strength.load_matches(input_path, league_id=league["id"], require_odds=False)
    validation_model = strength.fit_model([m for m in matches if m["day"] < first])
    final_model = strength.fit_model([m for m in matches if m["day"] < second])
    final_model.update({
        "schema_version": "team-strength-apifootball-1.0",
        "source": "apifootball.com_event_results",
        "lifecycle": "production",
        "league_id": league["id"],
        "league_name": league["name"],
        "split": {"validation_from_day": first, "test_from_day": second},
    })
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"{league['slug']}_candidate.json"
    model_path.write_text(json.dumps(final_model, ensure_ascii=False, indent=2), encoding="utf-8")
    result.update({
        "status": "trained",
        "model_path": str(model_path),
        "validation": strength.validate(matches, validation_model, first, to_day=second, baseline_key=baseline_key, baseline_label=baseline_label),
        "test": strength.validate(matches, final_model, second, baseline_key=baseline_key, baseline_label=baseline_label),
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = train_one_league(args.input, {"id": args.league_id, "slug": args.slug, "name": args.name}, args.output_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download, audit, and train five candidate league models without leakage."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


history = _load("apifootball_history", ROOT / "project007_APIFootball数据接入" / "02_脚本" / "download_apifootball_com_history.py")
odds_history = _load("apifootball_odds_history", ROOT / "project007_APIFootball数据接入" / "02_脚本" / "download_apifootball_com_odds.py")
training = _load("five_league_training", HERE / "train_five_leagues.py")
download_history = history.download_history
download_odds_for_dates = odds_history.download_odds_for_dates
attach_provider_market = odds_history.attach_provider_market


def catalog() -> dict:
    return json.loads((HERE / "five_league_catalog.json").read_text(encoding="utf-8"))


def run_pipeline(project: Path, refresh: bool = False) -> dict:
    config = catalog()
    start, end = date.fromisoformat(config["window"]["from"]), date.fromisoformat(config["window"]["to"])
    project = project.resolve()
    delivery = project / "05_交付"
    delivery.mkdir(parents=True, exist_ok=True)
    result, failures, downloaded = {"leagues": {}}, [], {}
    for league in config["leagues"]:
        report = download_history(league["id"], start, end, project, league["slug"], refresh)
        entry = {
            "download": {
                "rows": len(report["rows"]), "months_reused": report.get("months_reused", []),
                "months_downloaded": report.get("months_downloaded", []), "failures": report.get("failures", []),
                "output": report.get("output"),
            }
        }
        downloaded[league["slug"]] = (league, report)
        if report["failures"]:
            entry.update({"status": "download_failed", "training": {"status": "skipped", "reason": "download_failures"}})
            failures.extend({"league": league["slug"], **failure} for failure in report["failures"])
        result["leagues"][league["slug"]] = entry
    event_sets = {slug: [json.loads(line) for line in Path(report["output"]).read_text(encoding="utf-8").splitlines() if line.strip()] for slug, (_, report) in downloaded.items() if not report["failures"]}
    dates = {date.fromisoformat(row["kickoff"][:10]) for rows in event_sets.values() for row in rows if row.get("kickoff")}
    odds_report = download_odds_for_dates(dates, project)
    result["provider_market_coverage"] = {k: v for k, v in odds_report.items() if k != "rows"}
    (delivery / "provider_market_coverage_report.json").write_text(
        json.dumps({"event_dates": len(dates), **result["provider_market_coverage"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failures.extend({"provider_market": True, **failure} for failure in odds_report["failures"])
    for slug, (league, report) in downloaded.items():
        if report["failures"]:
            continue
        enriched, coverage = attach_provider_market(event_sets[slug], odds_report["rows"])
        enriched_path = project / "04_素材" / "标准化" / f"{slug}_events_provider_market.jsonl"
        enriched_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in enriched), encoding="utf-8")
        trained = training.train_one_league(enriched_path, league, project / "03_模型", baseline_key="provider_market", baseline_label="provider_market")
        trained["provider_market_coverage"] = coverage
        result["leagues"][slug].update({"status": trained["status"], "training": trained})
        (delivery / f"{slug}_training_report.json").write_text(json.dumps(trained, ensure_ascii=False, indent=2), encoding="utf-8")
    result["status"] = "partial" if failures else "ok"
    result["download_failures"] = failures
    (delivery / "download_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    (delivery / "five_league_pipeline_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    result = run_pipeline(args.project, args.refresh)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "partial":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

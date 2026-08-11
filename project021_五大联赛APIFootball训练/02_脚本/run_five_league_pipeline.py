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
training = _load("five_league_training", HERE / "train_five_leagues.py")
download_history = history.download_history


def catalog() -> dict:
    return json.loads((HERE / "five_league_catalog.json").read_text(encoding="utf-8"))


def run_pipeline(project: Path, refresh: bool = False) -> dict:
    config = catalog()
    start, end = date.fromisoformat(config["window"]["from"]), date.fromisoformat(config["window"]["to"])
    project = project.resolve()
    delivery = project / "05_交付"
    delivery.mkdir(parents=True, exist_ok=True)
    result, failures = {"leagues": {}}, []
    for league in config["leagues"]:
        report = download_history(league["id"], start, end, project, league["slug"], refresh)
        entry = {
            "download": {
                "rows": len(report["rows"]), "months_reused": report.get("months_reused", []),
                "months_downloaded": report.get("months_downloaded", []), "failures": report.get("failures", []),
                "output": report.get("output"),
            }
        }
        if report["failures"]:
            entry.update({"status": "download_failed", "training": {"status": "skipped", "reason": "download_failures"}})
            failures.extend({"league": league["slug"], **failure} for failure in report["failures"])
        else:
            trained = training.train_one_league(Path(report["output"]), league, project / "03_模型")
            entry.update({"status": trained["status"], "training": trained})
            (delivery / f"{league['slug']}_training_report.json").write_text(
                json.dumps(trained, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        result["leagues"][league["slug"]] = entry
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

#!/usr/bin/env python3
"""Settle unresolved Champions League predictions from APIFootball safely."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from apifootball_matcher import match_record
from apifootball_settlement import normalize_event
from runtime_paths import core_scripts_dir, workspace_root

ALIASES_PATH = HERE.parent / "config" / "apifootball_team_aliases.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def adapter_path() -> Path:
    return (workspace_root() / "project007_APIFootball数据接入" / "02_脚本"
            / "apifootball_com_adapter.py")


def default_output_dir() -> Path:
    return (workspace_root() / "project022_APIFootball欧冠回测结算"
            / "05_交付" / "settlement_runs")


def redact(text: Any) -> str:
    return re.sub(r"(?i)(APIkey=)[^&\s]+", r"\1[REDACTED]", str(text))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def load_records(store: Path) -> list[dict[str, Any]]:
    records, seen = [], set()
    for entry in _read_jsonl(store / "registry.jsonl"):
        match_id = str(entry.get("match_id") or "")
        path = Path(str(entry.get("path") or ""))
        if not match_id or match_id in seen or not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        record.setdefault("match_id", match_id)
        records.append(record)
        seen.add(match_id)
    return records


def decide_existing(result_path: Path, score_90: dict[str, int]) -> str:
    if not result_path.exists():
        return "write"
    current = json.loads(result_path.read_text(encoding="utf-8"))
    old = current.get("score_90")
    wanted = {"home": score_90["home"], "away": score_90["away"]}
    return "existing_same" if old == wanted else "source_conflict"


def run_settlement(
    store: Path,
    raw_events: list[dict[str, Any]],
    aliases: dict[str, str],
    dry_run: bool,
    settle_writer: Callable[[dict[str, Any]], Any],
    only_date: str | None = None,
) -> dict[str, Any]:
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidates = [normalize_event(event, collected_at) for event in raw_events]
    report: list[dict[str, Any]] = []
    records = load_records(Path(store))
    if only_date:
        records = [
            record for record in records
            if str(((record.get("match") or {}).get("kickoff") or ""))[:10] == only_date
        ]

    for record in records:
        match_id = str(record["match_id"])
        matched = match_record(record, candidates, aliases)
        if matched["status"] != "matched":
            report.append({"match_id": match_id, "status": matched["status"],
                           "candidate_count": matched.get("candidates", 0)})
            continue

        candidate = matched["candidate"]
        score_status = candidate["score_90_status"]
        if score_status == "not_finished":
            report.append({"match_id": match_id, "status": "not_finished",
                           "provider_match_id": candidate["provider_match_id"]})
            continue
        if score_status != "verified":
            report.append({"match_id": match_id, "status": "needs_review",
                           "reason": score_status,
                           "provider_match_id": candidate["provider_match_id"]})
            continue

        score_90 = candidate["score_90"]
        result_path = Path(store) / "results" / f"{match_id}.json"
        existing = decide_existing(result_path, score_90)
        if existing != "write":
            report.append({"match_id": match_id, "status": existing,
                           "provider_match_id": candidate["provider_match_id"],
                           "score_90": score_90})
            continue

        payload = {
            "match_id": match_id,
            "score_90": f"{score_90['home']}-{score_90['away']}",
            "provider_match_id": candidate["provider_match_id"],
            "matched_by": matched["matched_by"],
        }
        if dry_run:
            status = "would_settle"
        else:
            try:
                settle_writer(payload)
                status = "settled"
            except Exception as exc:
                report.append({"match_id": match_id, "status": "failed",
                               "error": redact(exc)})
                continue
        report.append({**payload, "status": status})

    return {
        "schema": "apifootball-settlement-run-1.0",
        "pending": len(records),
        "settled": sum(row["status"] == "settled" for row in report),
        "would_settle": sum(row["status"] == "would_settle" for row in report),
        "needs_review": sum(row["status"] == "needs_review" for row in report),
        "conflicts": sum(row["status"] == "source_conflict" for row in report),
        "report": report,
        "_candidates": candidates,
    }


def load_aliases(path: Path = ALIASES_PATH) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("aliases", {})


def fetch_events(records: list[dict[str, Any]], only_date: str | None) -> list[dict[str, Any]]:
    adapter = _load_module("apifootball_com_adapter", adapter_path())
    dates = sorted({str(((record.get("match") or {}).get("kickoff") or ""))[:10]
                    for record in records})
    if only_date:
        dates = [date for date in dates if date == only_date]
    rows: list[dict[str, Any]] = []
    for date in dates:
        if not date:
            continue
        payload = adapter.request("get_events", {
            "league_id": 3,
            "from": date,
            "to": date,
            "timezone": "Asia/Shanghai",
        })
        rows.extend(adapter._result(payload))
    return rows


def make_writer(store: Path) -> Callable[[dict[str, Any]], None]:
    def write(payload: dict[str, Any]) -> None:
        proc = subprocess.run([
            sys.executable,
            str(core_scripts_dir() / "settle_result.py"),
            "--match-id", payload["match_id"],
            "--score-90", payload["score_90"],
            "--source", "APIFootball get_events fallback",
            "--source-url", "https://apifootball.com/",
            "--store", str(store),
        ], text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or f"settle_result rc={proc.returncode}")
    return write


def archive_run(output_dir: Path, result: dict[str, Any], argv: list[str]) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = output_dir / f".{timestamp}.tmp"
    final = output_dir / timestamp
    temporary.mkdir(parents=False, exist_ok=False)
    candidates = result.get("_candidates", [])
    public = {key: value for key, value in result.items() if not key.startswith("_")}
    (temporary / "candidates.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates),
        encoding="utf-8",
    )
    (temporary / "settlement_audit.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    (temporary / "settled.json").write_text(json.dumps(
        [row for row in public["report"] if row["status"] in {"settled", "would_settle"}],
        ensure_ascii=False, indent=2), encoding="utf-8")
    (temporary / "conflicts.json").write_text(json.dumps(
        [row for row in public["report"] if row["status"] in {"source_conflict", "ambiguous_match"}],
        ensure_ascii=False, indent=2), encoding="utf-8")
    (temporary / "run_metadata.json").write_text(json.dumps({
        "schema": "apifootball-settlement-metadata-1.0",
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "argv": argv,
        "provider": "apifootball.com",
        "league_id": 3,
        "timezone": "Asia/Shanghai",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="APIFootball 欧冠赛果 fallback")
    parser.add_argument("--store", required=True)
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    args = parser.parse_args()
    store = Path(args.store)
    if not os.environ.get("APIFOOTBALL_COM_KEY", "").strip():
        result = {"schema": "apifootball-settlement-run-1.0",
                  "status": "missing_credential", "settled": 0,
                  "report": []}
        print(json.dumps(result, ensure_ascii=False))
        return
    try:
        raw_events = fetch_events(load_records(store), args.date)
        result = run_settlement(store, raw_events, load_aliases(), args.dry_run,
                                make_writer(store), only_date=args.date)
        archive = archive_run(args.output_dir, result, sys.argv)
        public = {key: value for key, value in result.items() if not key.startswith("_")}
        public["archive"] = str(archive)
    except Exception as exc:
        public = {"schema": "apifootball-settlement-run-1.0",
                  "status": "provider_unavailable", "settled": 0,
                  "error": redact(exc), "report": []}
    print(json.dumps(public, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

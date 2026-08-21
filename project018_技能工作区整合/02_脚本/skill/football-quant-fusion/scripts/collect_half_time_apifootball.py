#!/usr/bin/env python3
"""Capture apifootball.com fixture payloads for offline half-time research.

This deliberately does not touch ``backtest/results``.  Captured provider
payloads are later matched by team aliases, kickoff and the already-official
90-minute score by ``half_time_enrichment.py``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import data_root
from half_time_enrichment import load_settled_records


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[4]
ADAPTER = WORKSPACE / "project007_APIFootball数据接入" / "02_脚本" / "apifootball_com_adapter.py"
DEFAULT_STORE = data_root() / "backtest"
DEFAULT_OUTPUT_DIR = data_root() / "research" / "half-time-fixtures" / "apifootball"


def kickoff_dates(records: Iterable[tuple[dict[str, Any], dict[str, Any]]]) -> list[str]:
    """Return unique local kickoff dates for formally settled 90-minute rows."""
    dates = set()
    for record, result in records:
        kickoff = ((record.get("match") or {}).get("kickoff"))
        if (result.get("status") == "finished" and result.get("settlement_scope") == "90min"
                and isinstance(kickoff, str) and len(kickoff) >= 10
                and kickoff[:10].count("-") == 2):
            dates.add(kickoff[:10])
    return sorted(dates)


def payload_rows(payload: Any) -> list[dict[str, Any]]:
    return payload if isinstance(payload, list) else []


def _adapter_request(action: str, params: dict[str, Any]) -> Any:
    spec = importlib.util.spec_from_file_location("apifootball_com_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 apifootball.com adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.request(action, params)


def capture(store: Path, dates: list[str], output_dir: Path, *, refresh: bool = False,
            dry_run: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest: dict[str, Any] = {
        "schema": "half-time-provider-capture-1.0", "provider": "apifootball.com",
        "research_only": True, "store": str(store), "dates": [],
        "note": "Provider fixture data is research evidence only and cannot overwrite formal 90-minute results.",
    }
    combined: list[dict[str, Any]] = []
    for day in dates:
        path = output_dir / f"events_{day}.json"
        if path.exists() and not refresh:
            payload = json.loads(path.read_text(encoding="utf-8"))
            source = "cached"
        elif dry_run:
            manifest["dates"].append({"date": day, "status": "planned"})
            continue
        else:
            try:
                payload = _adapter_request("get_events", {"from": day, "to": day, "timezone": "Asia/Shanghai"})
                output_dir.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                source = "captured"
            except Exception as exc:
                manifest["dates"].append({"date": day, "status": "error", "error": str(exc)})
                continue
        rows = payload_rows(payload)
        combined.extend(rows)
        manifest["dates"].append({"date": day, "status": "ok", "source": source,
                                  "raw_path": str(path), "provider_rows": len(rows)})
    manifest["provider_rows"] = len(combined)
    return manifest, combined


def main() -> None:
    parser = argparse.ArgumentParser(description="按已结算开球日抓取半场研究证据，不改正式赛果")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--date", action="append", help="可重复；省略时取所有正式已结算比赛的开球日")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--fixtures-output", type=Path)
    parser.add_argument("--refresh", action="store_true", help="明确允许重抓并覆盖同日原始响应")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dates = sorted(set(args.date or kickoff_dates(load_settled_records(args.store))))
    manifest, rows = capture(args.store, dates, args.output_dir, refresh=args.refresh, dry_run=args.dry_run)
    manifest_path = args.manifest or args.output_dir / "capture_manifest.json"
    fixtures_path = args.fixtures_output or args.output_dir / "fixtures.json"
    if not args.dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fixtures_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "dry_run" if args.dry_run else "ok", "dates": len(dates),
                      "provider_rows": len(rows), "manifest": str(manifest_path),
                      "fixtures": str(fixtures_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

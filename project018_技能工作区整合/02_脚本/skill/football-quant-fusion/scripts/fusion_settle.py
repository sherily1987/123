#!/usr/bin/env python3
"""Orchestrate official settlement with an explicit APIFootball fallback."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from runtime_paths import core_scripts_dir, data_root


def build_commands(
    store: Path,
    date: str | None,
    dry_run: bool,
    apifootball_fallback: bool,
) -> list[dict[str, Any]]:
    common = ["--store", str(store)]
    if date:
        common.extend(["--date", date])
    if dry_run:
        common.append("--dry-run")
    commands = [{
        "source": "official",
        "cmd": [sys.executable, str(core_scripts_dir() / "settle_from_sporttery.py"), *common],
    }]
    if apifootball_fallback:
        commands.append({
            "source": "apifootball",
            "cmd": [sys.executable, str(HERE / "settle_from_apifootball.py"), *common],
        })
    return commands


def combine_reports(
    official: dict[str, Any],
    apifootball: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": "fusion-settlement-1.0",
        "official": official,
        "apifootball_fallback": apifootball,
        "settled": int(official.get("settled") or 0)
                   + int((apifootball or {}).get("settled") or 0),
    }


def run_command(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, text=True, capture_output=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "failed",
            "settled": 0,
            "returncode": proc.returncode,
            "error": (proc.stderr or proc.stdout)[-1000:],
        }
    if proc.returncode != 0:
        payload.setdefault("status", "failed")
        payload.setdefault("settled", 0)
        payload["returncode"] = proc.returncode
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="融合赛果结算")
    parser.add_argument("--store", type=Path, default=data_root() / "backtest")
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apifootball-fallback", action="store_true")
    args = parser.parse_args()
    commands = build_commands(args.store, args.date, args.dry_run,
                              args.apifootball_fallback)
    official = run_command(commands[0]["cmd"])
    provider = run_command(commands[1]["cmd"]) if len(commands) == 2 else None
    print(json.dumps(combine_reports(official, provider), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

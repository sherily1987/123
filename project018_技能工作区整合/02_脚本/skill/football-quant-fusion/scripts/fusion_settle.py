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
    include_llm_jobs: bool = False,
) -> list[dict[str, Any]]:
    common = ["--store", str(store)]
    if date:
        common.extend(["--date", date])
    if dry_run:
        common.append("--dry-run")
    if include_llm_jobs:
        common.append("--include-llm-jobs")
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


def parse_command_output(stdout: str, returncode: int = 0) -> dict[str, Any]:
    """Parse a JSON payload even when the child emits human logs first."""
    raw = stdout or ""
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append((index + end, value))
    if candidates:
        # Nested report entries also decode successfully; the outer payload
        # consumes the longest suffix and is the actual command result.
        return max(candidates, key=lambda item: item[0])[1]
    return {
        "status": "failed",
        "settled": 0,
        "returncode": returncode,
        "error": raw[-1000:],
    }


def run_command(command: list[str]) -> dict[str, Any]:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    chunks = []
    for line in proc.stdout:
        chunks.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()
    proc.wait()
    stdout = "".join(chunks)
    payload = parse_command_output(stdout, proc.returncode)
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
    parser.add_argument("--include-llm-jobs", action="store_true",
                        help="为 LLM 研究工单查询官方赛果，用于独立校准")
    args = parser.parse_args()
    commands = build_commands(args.store, args.date, args.dry_run,
                              args.apifootball_fallback, args.include_llm_jobs)
    official = run_command(commands[0]["cmd"])
    provider = run_command(commands[1]["cmd"]) if len(commands) == 2 else None
    print(json.dumps(combine_reports(official, provider), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

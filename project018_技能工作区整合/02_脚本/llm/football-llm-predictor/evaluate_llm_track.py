#!/usr/bin/env python3
"""Evaluate registered K3 research predictions against verified 90-minute results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_track_evaluation import evaluate_llm_records


def _read(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_records(path: str | Path) -> list[dict]:
    payload = _read(path)
    if isinstance(payload, list):
        return payload
    for key in ("records", "predictions"):
        if isinstance(payload.get(key), list):
            return payload[key]
    raise ValueError("预测文件必须是数组或包含 records/predictions 数组")


def load_results(path: str | Path) -> dict[str, dict]:
    payload = _read(path)
    if isinstance(payload, dict) and isinstance(payload.get("results"), dict):
        return payload["results"]
    if isinstance(payload, dict) and all(isinstance(v, dict) for v in payload.values()):
        return payload
    if isinstance(payload, list):
        result = {}
        for row in payload:
            if isinstance(row, dict) and row.get("match_id"):
                result[str(row["match_id"])] = row
        return result
    raise ValueError("赛果文件必须是结果映射、数组或包含 results 映射")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, help="LLM 预测记录 JSON")
    parser.add_argument("--results", required=True, help="含 score_90_status=verified 的赛果 JSON")
    parser.add_argument("--output", type=Path, help="可选评测报告输出路径")
    args = parser.parse_args()
    report = evaluate_llm_records(load_records(args.predictions), load_results(args.results))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()


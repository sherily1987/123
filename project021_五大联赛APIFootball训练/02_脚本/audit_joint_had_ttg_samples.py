#!/usr/bin/env python3
"""审计HAD+TTG联合拟合所需的可结算样本量。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def _settled(row: dict) -> bool:
    actual = row.get("actual") or row.get("score_90")
    return isinstance(actual, (list, tuple)) and len(actual) >= 2 and all(x is not None for x in actual[:2])


def summarize(rows: list[dict]) -> dict:
    had = [r for r in rows if isinstance(r.get("odds"), (list, tuple)) and len(r["odds"]) >= 3]
    joint = [r for r in had if isinstance(r.get("ttg"), dict)
             and isinstance(r["ttg"].get("odds"), (list, tuple))
             and len(r["ttg"]["odds"]) == 8]
    return {"had_rows": len(had), "ttg_rows": sum(bool(r.get("ttg")) for r in rows),
            "joint_rows": len(joint), "joint_settled_rows": sum(_settled(r) for r in joint)}


def load_store_rows(root: Path) -> list[dict]:
    """从登记库读取预测输入，并按同一match_id附加独立赛果文件。"""
    registry = root / "registry.jsonl"
    if not registry.exists():
        return []
    rows = []
    for line in registry.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            path = Path(entry["path"])
            if not path.is_absolute():
                path = root / path
            record = json.loads(path.read_text(encoding="utf-8"))
            row = dict(record.get("input") or record)
            result_path = root / "results" / f"{entry['match_id']}.json"
            if result_path.exists():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                score = result.get("score_90") or {}
                if isinstance(score, dict) and score.get("home") is not None and score.get("away") is not None:
                    row["actual"] = [score["home"], score["away"]]
            rows.append(row)
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("project021_五大联赛APIFootball训练/05_交付"))
    ap.add_argument("--store", type=Path, help="backtest登记库；提供后优先按registry+results核验赛果")
    args = ap.parse_args()
    rows = load_store_rows(args.store.resolve()) if args.store else []
    source = "store_registry_results" if args.store else "forward_input_files"
    for path in args.root.rglob("*_input.json") if not args.store else []:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    summary = summarize(rows)
    summary.update({"schema": "joint-had-ttg-sample-audit-1.0",
                    "research_only": True,
                    "ran_at": datetime.now().isoformat(timespec="seconds"),
                    "source_root": str(args.store or args.root),
                    "source": source,
                    "minimum_for_oos": 120,
                    "gate": "BLOCKED" if summary["joint_settled_rows"] < 120 else "READY_FOR_OOS"})
    out = args.root / "joint_had_ttg_sample_audit.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

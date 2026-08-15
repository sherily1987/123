#!/usr/bin/env python3
"""独立入口：生成按开球日期分组的扩展窗口walk-forward评估报告。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from runtime_paths import backtest_store

HERE = Path(__file__).resolve().parent
BACKTEST = HERE / "fusion_backtest.py"
# 2026-08-16：默认值原指向外部套件（物理拷贝、比仓库内旧），改走仓库内唯一事实源
DEFAULT_STORE = str(backtest_store())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=DEFAULT_STORE)
    ap.add_argument("--output", required=True)
    ap.add_argument("--snapshot-policy", choices=("latest_before_kickoff", "prematch", "closing"),
                    default="latest_before_kickoff")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--bootstrap-iterations", type=int, default=2000)
    args = ap.parse_args()

    tmp = tempfile.NamedTemporaryFile(prefix="fusion-walk-forward-", suffix=".json", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        proc = subprocess.run([
            sys.executable, str(BACKTEST), "--store", args.store,
            "--snapshot-policy", args.snapshot_policy,
            "--walk-forward-folds", str(args.folds),
            "--bootstrap-iterations", str(args.bootstrap_iterations),
            "--output", str(tmp_path),
        ], text=True, capture_output=True)
        if proc.returncode != 0:
            raise SystemExit(proc.stderr or proc.stdout)
        full = json.loads(tmp_path.read_text(encoding="utf-8-sig"))
        report = {
            "schema_version": "fusion-walk-forward-1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "store": args.store,
            "evaluation_unit": full.get("evaluation_unit"),
            "snapshot_policy": full.get("snapshot_policy"),
            "record_sample_size": full.get("record_sample_size"),
            "unique_match_n": full.get("unique_match_n"),
            "current_identity": full.get("current_identity"),
            "by_version_cohort": full.get("by_version_cohort"),
            "paired_market": full.get("paired_market"),
            "walk_forward": full.get("walk_forward"),
            "warning": full.get("warning"),
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "output": str(output),
                          "fold_count": (report.get("walk_forward") or {}).get("fold_count")},
                         ensure_ascii=False, indent=2))
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

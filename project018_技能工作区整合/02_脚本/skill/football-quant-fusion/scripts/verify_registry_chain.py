#!/usr/bin/env python3
"""verify_registry_chain — 登记哈希链完整性校验（只读）。

三项校验：
  1. previous_hash 链式连续（每条的 previous_hash == 上一条的 entry_hash）
  2. entry_hash 可重算（sha(previous_hash + record_hash)）
  3. record_hash 与预测产物文件内容对账（sha(预测JSON) == record_hash）

登记里的 path 是历史容器/旧机绝对路径，按 predictions/... 之后的相对段落回本机 store。
本脚本不修改任何文件；发现问题只报告，不自动修复——修链必须重算整条，禁止手动 append。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from runtime_paths import data_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from backtest_lib import sha
except ImportError:  # 核心不可用时退回等价实现（与 backtest_lib.canonical 口径一致）
    import hashlib

    def sha(x):
        if isinstance(x, bytes):
            return hashlib.sha256(x).hexdigest()
        blob = json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def local_prediction_path(stored_path, store):
    m = re.search(r"(predictions/.*)$", str(stored_path).replace("\\", "/"))
    return (Path(store) / m.group(1)) if m else None


def verify(store):
    store = Path(store)
    reg = store / "registry.jsonl"
    if not reg.exists():
        return {"status": "error", "detail": f"registry 不存在: {reg}"}
    rows = [json.loads(x) for x in reg.read_text(encoding="utf-8").splitlines() if x.strip()]

    chain_breaks, entry_bad, content_bad, missing = [], [], [], []
    prev = ""
    for i, e in enumerate(rows):
        pid = str(e.get("prediction_id") or "")
        if str(e.get("previous_hash") or "") != prev:
            chain_breaks.append({"index": i, "prediction_id": pid})
        if sha(prev + str(e.get("record_hash") or "")) != e.get("entry_hash"):
            entry_bad.append({"index": i, "prediction_id": pid})
        prev = str(e.get("entry_hash") or "")

        lp = local_prediction_path(e.get("path"), store)
        if lp is None or not lp.exists():
            missing.append({"index": i, "prediction_id": pid, "path": str(e.get("path"))})
        elif sha(json.loads(lp.read_text(encoding="utf-8"))) != e.get("record_hash"):
            content_bad.append({"index": i, "prediction_id": pid})

    ok = not (chain_breaks or entry_bad or content_bad or missing)
    return {
        "status": "ok" if ok else "broken",
        "store": str(store),
        "entries": len(rows),
        "chain_breaks": chain_breaks,
        "entry_hash_mismatches": entry_bad,
        "record_hash_mismatches": content_bad,
        "missing_prediction_files": missing,
        "counts": {
            "chain_breaks": len(chain_breaks),
            "entry_hash_mismatches": len(entry_bad),
            "record_hash_mismatches": len(content_bad),
            "missing_prediction_files": len(missing),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=str(data_root() / "backtest"))
    ap.add_argument("--output")
    a = ap.parse_args()
    report = verify(a.store)
    detail_keys = ("chain_breaks", "entry_hash_mismatches",
                   "record_hash_mismatches", "missing_prediction_files")
    if a.output:
        Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in detail_keys}
    for key in detail_keys:
        summary.setdefault("samples", {})[key] = report.get(key, [])[:5]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

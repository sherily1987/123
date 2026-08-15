#!/usr/bin/env python3
"""audit_version_consistency — 检测「概率签名变了但 model_version 未 bump」的违规。

对比 config/release_lock.json（发布快照）与当前计算的 probability_signature：
- 概率文件已改、但 manifest 的 model_version 没 bump → VIOLATION（exit 1）
- 签名与锁一致 → ok（exit 0）

用法：
  python audit_version_consistency.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fusion_predict_core import build_identity  # noqa: E402

LOCK_FILE = HERE.parent / "config" / "release_lock.json"


def main() -> None:
    ident = build_identity()
    model_version = str(ident.get("model_version") or "unknown")
    prob_sig = str(ident.get("probability_signature") or "")

    if not LOCK_FILE.exists():
        print(json.dumps({"status": "no_lock",
                          "note": "无发布锁，先跑 release_lock.py 锁定"},
                         ensure_ascii=False))
        sys.exit(1)

    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    locked_mv = lock.get("model_version")
    locked_ps = lock.get("probability_signature")
    drifted = locked_ps != prob_sig
    version_bumped = locked_mv != model_version

    if drifted and not version_bumped:
        verdict = "VIOLATION"
        note = ("概率文件已改但 model_version 未 bump："
                "要么 bump config/version_manifest.json 的 model_version 并重新 release_lock，"
                "要么撤销概率文件改动。")
    elif drifted and version_bumped:
        verdict = "ok_but_lock_stale"
        note = "概率文件已改且版本已 bump，但 release_lock.json 仍是旧快照，需重新 lock。"
    else:
        verdict = "ok"
        note = "概率签名与发布锁一致，版本未漂移。"

    print(json.dumps({
        "status": verdict,
        "model_version": model_version,
        "locked_model_version": locked_mv,
        "current_probability_signature": (prob_sig or "")[:12],
        "locked_probability_signature": (locked_ps or "")[:12],
        "note": note,
    }, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "ok" else 1)


if __name__ == "__main__":
    main()

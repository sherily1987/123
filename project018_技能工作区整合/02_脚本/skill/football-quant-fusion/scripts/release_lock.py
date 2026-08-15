#!/usr/bin/env python3
"""release_lock — 发布前锁定 model_version + probability_signature。

把「语义版本 + 概率签名」冻结为一个发布快照（config/release_lock.json），
作为 audit_version_consistency.py 审计「概率文件已改但版本未 bump」的基准。

用法：
  python release_lock.py            锁定：写/更新 config/release_lock.json
  python release_lock.py --check    校验：当前签名 vs 锁文件（exit 0=一致，1=漂移/无锁）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fusion_predict_core import build_identity  # noqa: E402

LOCK_FILE = HERE.parent / "config" / "release_lock.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验不写")
    a = ap.parse_args()

    ident = build_identity()
    model_version = str(ident.get("model_version") or "unknown")
    prob_sig = str(ident.get("probability_signature") or "")

    if a.check:
        if not LOCK_FILE.exists():
            print(json.dumps({"status": "no_lock",
                              "note": "无发布锁，先跑 release_lock.py 锁定"},
                             ensure_ascii=False))
            sys.exit(1)
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        locked_ps = lock.get("probability_signature")
        locked_mv = lock.get("model_version")
        drifted = locked_ps != prob_sig
        if drifted and locked_mv == model_version:
            verdict, note = "DRIFT", "概率文件已改但 model_version 未 bump，属违规"
        elif drifted:
            verdict, note = "version_bumped", "概率文件已改且版本已 bump，需重新 lock"
        else:
            verdict, note = "ok", ""
        print(json.dumps({
            "status": verdict,
            "locked_model_version": locked_mv,
            "current_model_version": model_version,
            "locked_probability_signature": (locked_ps or "")[:12],
            "current_probability_signature": (prob_sig or "")[:12],
            "note": note,
        }, ensure_ascii=False, indent=2))
        sys.exit(0 if verdict == "ok" else 1)

    payload = {
        "model_version": model_version,
        "probability_signature": prob_sig,
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "note": ("发布快照；发布窗口内禁止改概率文件。"
                 "改概率文件前先 bump config/version_manifest.json 的 model_version，再重新 lock。"),
    }
    LOCK_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "locked", "lock_file": str(LOCK_FILE), **payload},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

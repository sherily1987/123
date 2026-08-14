# -*- coding: utf-8 -*-
"""P0-1 修复：占位预测重建（2026-08-12，一次性工具，不进入生产套件）。

根因（已定位）：8月2日旧引擎（core 3.4.1）批量登记历史快照时 devig 失败，
802/1550 条预测输出对称占位 [37.4,25.3,37.4]（core.mode=model_first / UNFITTED_NO_VALUE），
被回测当作"无脑押主胜"计入，污染 459 场结算（主记录 67/463 占位）。
当前引擎（3.4.4）对同一 input 重算 100% 正常（multi_market_fit，市场一致）。

约束：不改 registry.jsonl 哈希链、不覆盖原 predictions 文件。
产物：rebuilt/ 目录（重算后的完整预测记录）+ rebuilt_map.json（原 prediction_id → 修复文件）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
from predict import predict  # noqa: E402

BASE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
OUT_DIR = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\06_复盘\2026-08-12_预测数据整合\rebuilt")


def is_placeholder(rec: dict) -> bool:
    core = (rec.get("output") or {}).get("core_output") or {}
    fd = ((rec.get("output") or {}).get("fusion_decision") or {}).get("status")
    probs = core.get("final_1x2_pct")
    if not (isinstance(probs, list) and len(probs) == 3):
        return False
    return (abs(probs[0] - 37.4) < 0.1 and abs(probs[2] - 37.4) < 0.1
            and fd == "UNFITTED_NO_VALUE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只重建前 N 条（测试用）")
    ap.add_argument("--match-id", default=None, help="只重建指定 match_id")
    args = ap.parse_args()

    reg_path = BASE / "registry.jsonl"
    reg = [json.loads(l) for l in reg_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    mapping = {}
    rebuilt = []
    skipped_no_odds = 0
    failed = []

    for e in reg:
        mid = e.get("match_id")
        if args.match_id and mid != args.match_id:
            continue
        p = Path(e.get("path", ""))
        if not p.exists():
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not is_placeholder(rec):
            continue
        inp = rec.get("input") or {}
        if not (inp.get("odds") or inp.get("hhad") or inp.get("ttg") or inp.get("hafu")):
            skipped_no_odds += 1
            continue
        try:
            res = predict(dict(inp))
        except Exception as exc:
            failed.append({"match_id": mid, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not (isinstance(res, dict) and res.get("status") == "ok"):
            failed.append({"match_id": mid, "error": f"status={res.get('status') if isinstance(res, dict) else res}"})
            continue
        new_core = res
        # 用重算结果替换 output.core_output / forecast，保留原记录外壳
        old_out = rec.get("output") or {}
        new_out = dict(old_out)
        new_out["core_output"] = new_core
        # 重建 forecast/fusion_decision 由 core_output 派生（保持与生产一致的最小改动：
        # 只替换 core_output 与顶层 final 字段，fusion 决策层由回测重新解析）
        new_rec = dict(rec)
        new_rec["output"] = new_out
        new_rec["rebuilt_at"] = datetime.now(timezone.utc).isoformat()
        new_rec["rebuilt_from"] = str(p)
        new_rec["rebuilt_reason"] = "placeholder_fix_p0_1_20260812"

        pid = e.get("prediction_id") or p.stem
        # 修复文件名：原 prediction_id + _rebuilt
        fname = pid + "_rebuilt.json"
        out_path = out_dir / fname
        out_path.write_text(json.dumps(new_rec, ensure_ascii=False, indent=1), encoding="utf-8")
        mapping[pid] = {"match_id": mid, "rebuilt_file": str(out_path), "path": str(p)}
        rebuilt.append(pid)
        if args.limit and len(rebuilt) >= args.limit:
            break

    # 写映射
    map_path = out_dir.parent / "rebuilt_map.json"
    map_path.write_text(json.dumps({
        "schema": "placeholder-rebuild-map-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": new_core.get("engine_version") if rebuilt else None,
        "count": len(rebuilt),
        "skipped_no_odds": skipped_no_odds,
        "failed": failed,
        "mapping": mapping,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "rebuilt": len(rebuilt), "skipped_no_odds": skipped_no_odds,
        "failed": len(failed), "map": str(map_path),
    }, ensure_ascii=False, indent=1))
    if failed:
        print("FAILED_SAMPLE=", json.dumps(failed[:5], ensure_ascii=False))


if __name__ == "__main__":
    main()

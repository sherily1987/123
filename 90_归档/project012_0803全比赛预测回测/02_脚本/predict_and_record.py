#!/usr/bin/env python3
"""预测 2026-08-03 体彩全部在售比赛并生成待回测记录。

流程（每场）：
  1) fusion_predict.py 生成完整融合输出（胜平负+比分+衍生市场）
  2) fusion_record.py --snapshot prematch 登记进引擎回测库
     （kickoff 已过的场次会被引擎拒绝，属预期保护）
  3) 把登记记录复制到 04_素材/待回测记录/20260803/ 并生成 index

用法:
  python predict_and_record.py
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts")
STORE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
INPUT = PROJ / "04_素材" / "input_20260803.json"
OUT_DIR = PROJ / "04_素材" / "待回测记录" / "20260803"
SNAPSHOT = "prematch"


def run(cmd):
    return subprocess.run([sys.executable, *map(str, cmd)], text=True, capture_output=True)


def main():
    batch = json.loads(INPUT.read_text(encoding="utf-8"))
    matches = batch.get("matches", [])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, m in enumerate(matches, 1):
        sm = m.get("sporttery_meta") or {}
        num = sm.get("match_num", f"match{i:02d}")
        mid = f"sporttery-{sm.get('match_id')}"
        print(f"[{i}/{len(matches)}] {num} {m.get('home')} vs {m.get('away')}", flush=True)
        ip = OUT_DIR / f"{num}_input.json"
        op = OUT_DIR / f"{num}_output.json"
        ip.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        pr = run([ENGINE / "fusion_predict.py", ip, "--output", op])
        if pr.returncode != 0:
            print("  predict 失败:", (pr.stderr or pr.stdout)[-200:])
            continue
        out = json.loads(op.read_text(encoding="utf-8"))
        if out.get("fusion_status") != "ok":
            print(f"  blocked: {out.get('fusion_status')}")
            continue
        rr = run([ENGINE / "fusion_record.py", "--input", ip, "--output", op,
                  "--store", STORE, "--snapshot", SNAPSHOT])
        if rr.returncode != 0:
            print("  record 拒绝:", (rr.stderr or rr.stdout)[-200:].strip().replace("\n", " "))
            continue
        rec = json.loads(rr.stdout)
        pred_path = Path(rec["path"])
        rec_json = json.loads(pred_path.read_text(encoding="utf-8"))
        rec_file = OUT_DIR / f"{num}_{rec_json['prediction_id']}.json"
        shutil.copy2(pred_path, rec_file)
        core = (rec_json.get("output") or {}).get("core_output") or {}
        forecast = (rec_json.get("output") or {}).get("forecast") or {}
        pct = core.get("final_1x2_pct") or forecast.get("final_1x2_pct") or []
        tops = core.get("top_scores") or forecast.get("top_scores") or []
        rows.append({
            "match_num": num, "match_id": mid, "league": m.get("competition"),
            "home": m.get("home"), "away": m.get("away"), "kickoff": m.get("kickoff"),
            "final_1x2_pct": pct, "top_score_1": tops[0]["score"] if tops else None,
            "top_score_2": tops[1]["score"] if len(tops) > 1 else None,
            "top_score_3": tops[2]["score"] if len(tops) > 2 else None,
            "record_file": rec_file.name, "prediction_id": rec_json["prediction_id"],
            "snapshot": SNAPSHOT, "created_at": rec_json["created_at"],
        })
        print(f"  已登记: {rec['status']} -> {rec_file.name}")

    with open(OUT_DIR / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["match_num"])
        w.writeheader()
        w.writerows(rows)
    (OUT_DIR / "index.json").write_text(
        json.dumps({"schema": "pending-backtest-1.0", "kickoff_date": "2026-08-03",
                    "snapshot": SNAPSHOT, "generated_at": datetime.now().isoformat(),
                    "records": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n待回测记录: {len(rows)}/{len(matches)} 场 -> {OUT_DIR}")


if __name__ == "__main__":
    main()

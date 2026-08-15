#!/usr/bin/env python3
"""回填 5 场待回测赛果（08-14 沙职/解放者杯 4 场 + 1 月汉堡场历史遗留）。

用 settle_from_sporttery.fetch_fixed_by_id 直查体彩固定奖金接口，settle_result.py 写入。
用法：python settle_pending_5.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

CORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
sys.path.insert(0, str(CORE))
from settle_from_sporttery import fetch_fixed_by_id  # noqa: E402

MATCHES = [
    ("sporttery-2036932", "2036932", "汉堡 vs 勒沃库森"),
    ("sporttery-2040832", "2040832", "艾卜哈 vs 拉斯决心"),
    ("sporttery-2040823", "2040823", "利雅青年 vs 胡巴卡德"),
    ("sporttery-2040827", "2040827", "米拉索尔 vs 基多体大"),
    ("sporttery-2040828", "2040828", "罗萨里奥 vs 科林蒂安"),
]

SOURCE = "中国体彩网移动端官方赛果"
SOURCE_URL = "https://m.sporttery.cn/mjc/zqsj/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    report = []
    for result_mid, sid, note in MATCHES:
        rp = STORE / "results" / f"{result_mid}.json"
        if rp.exists():
            report.append({"match_id": result_mid, "status": "exists", "note": note})
            print(f"[exists] {result_mid}  {note}", flush=True)
            continue
        try:
            row = fetch_fixed_by_id(sid)
        except Exception as exc:
            report.append({"match_id": result_mid, "status": "fetch_error", "note": note, "err": str(exc)[:120]})
            print(f"[fetch_error] {result_mid}  {note}  {str(exc)[:120]}", flush=True)
            continue
        if not row.get("finished") or not row.get("score_90"):
            report.append({"match_id": result_mid, "status": "not_finished",
                           "note": note, "status_name": row.get("status_name")})
            print(f"[not_finished] {result_mid}  {note}  status={row.get('status_name')}", flush=True)
            continue
        score_90 = row["score_90"]
        score_ht = row.get("score_ht")
        if a.dry_run:
            report.append({"match_id": result_mid, "status": "would_settle", "note": note,
                           "score_90": score_90, "score_ht": score_ht})
            print(f"[dry] {result_mid}  {note}  score_90={score_90}  ht={score_ht}", flush=True)
            continue
        cmd = [sys.executable, str(CORE / "settle_result.py"),
               "--match-id", result_mid, "--score-90", score_90,
               *(["--score-ht", score_ht] if score_ht else []),
               "--source", SOURCE, "--source-url", SOURCE_URL, "--store", str(STORE)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            report.append({"match_id": result_mid, "status": "settled", "note": note, "score_90": score_90})
            print(f"[settled] {result_mid}  {note}  score_90={score_90}", flush=True)
        else:
            report.append({"match_id": result_mid, "status": "failed", "note": note,
                           "err": (r.stderr or r.stdout).strip()[:160]})
            print(f"[failed] {result_mid}  {note}  {(r.stderr or r.stdout).strip()[:160]}", flush=True)
        time.sleep(0.35)

    print(json.dumps({"total": len(report),
                      "settled": sum(1 for x in report if x["status"] == "settled"),
                      "report": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

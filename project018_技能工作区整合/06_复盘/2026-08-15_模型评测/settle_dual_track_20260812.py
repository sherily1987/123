#!/usr/bin/env python3
"""聚焦回填 08-12 双轨预测的 9 场官方赛果（量化 3 + LLM 6）。

量化场 results 文件名 = "sporttery-<matchId>"；LLM 场 = 纯数字 "<matchId>"。
用 settle_from_sporttery.fetch_fixed_by_id 直查体彩固定奖金接口拿 90 分钟比分，
确认 finished 后调 settle_result.py 写入共享 results/（不覆盖已存在文件）。

用法：
  python settle_dual_track_20260812.py [--dry-run]
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

# (results 文件名 match_id, 体彩数字 matchId, 说明)
MATCHES = [
    ("sporttery-2040819", "2040819", "量化 周三002 普拉滕斯vs科金博联"),
    ("sporttery-2040820", "2040820", "量化 周三003 帕梅拉斯vs波特诺"),
    ("sporttery-2040831", "2040831", "量化 周三001 巴黎圣曼vs维拉"),
    ("2040821", "2040821", "LLM 周四002 克拉约瓦vs库奥皮奥"),
    ("2040822", "2040822", "LLM 周四003 帕福斯vs萨尔茨堡"),
    ("2040824", "2040824", "LLM 周四006 流浪者vs比亚韦斯托克"),
    ("2040825", "2040825", "LLM 周四007 安德莱赫特vsPAOK"),
    ("2040826", "2040826", "LLM 周四008 哈茨vs本菲卡"),
    ("2040833", "2040833", "LLM 周四004 雷克维京vs图恩"),
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
        entry = {"match_id": result_mid, "status": "settled", "note": note,
                 "score_90": score_90, "score_ht": score_ht}
        if a.dry_run:
            entry["status"] = "would_settle"
            report.append(entry)
            print(f"[dry] {result_mid}  {note}  score_90={score_90}  ht={score_ht}", flush=True)
            continue
        cmd = [sys.executable, str(CORE / "settle_result.py"),
               "--match-id", result_mid, "--score-90", score_90,
               *(["--score-ht", score_ht] if score_ht else []),
               "--source", SOURCE, "--source-url", SOURCE_URL, "--store", str(STORE)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            report.append(entry)
            print(f"[settled] {result_mid}  {note}  score_90={score_90}", flush=True)
        else:
            entry["status"] = "failed"
            entry["err"] = (r.stderr or r.stdout).strip()[:160]
            report.append(entry)
            print(f"[failed] {result_mid}  {note}  {(r.stderr or r.stdout).strip()[:160]}", flush=True)
        time.sleep(0.35)

    print(json.dumps({"total": len(report),
                      "settled": sum(1 for x in report if x["status"] == "settled"),
                      "report": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

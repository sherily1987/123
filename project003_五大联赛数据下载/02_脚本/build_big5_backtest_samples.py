#!/usr/bin/env python3
"""把五大联赛 2025/26 已结算竞彩快照批量登记为融合回测样本。

输入: 引擎 backtest/snapshots/by_league/{英超,西甲,意甲,德甲,法甲}.jsonl
      （体彩官方 closing HAD 赔率 + 90 分钟赛果）
每场流程:
  1) 用 closing 官方HAD 构造 market_only 输入（UTF-8 无 BOM）
  2) fusion_predict.py 生成模型输出（fusion_status=ok 才继续）
  3) fusion_record.py --allow-past --snapshot closing 登记（幂等，重复自动跳过）
  4) 写 results/<match_id>.json（score_90 来自快照），供 sample_audit 统计已结算

用法:
  python build_big5_backtest_samples.py                # 全部 5 联赛
  python build_big5_backtest_samples.py --leagues 英超 意甲
  python build_big5_backtest_samples.py --limit 3      # 冒烟测试
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts")
STORE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest")
SNAP_DIR = STORE / "snapshots" / "by_league"
WORK = Path(r"H:\claude AI自媒体\project003_五大联赛数据下载\04_素材\_big5_backtest_work")

LEAGUES = ["英超", "西甲", "意甲", "德甲", "法甲"]
SNAPSHOTS = ["opening", "t_minus_24h", "t_minus_6h", "closing"]


def load_registered():
    reg = STORE / "registry.jsonl"
    seen = set()
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            p = Path(e.get("path", ""))
            if not p.exists():
                continue
            r = json.loads(p.read_text(encoding="utf-8"))
            seen.add((r.get("match_id"), r.get("snapshot_type")))
    return seen


def build_input(row, snap):
    snap_data = (row.get("snapshots") or {}).get(snap) or {}
    if not snap_data.get("odds"):
        return None
    return {
        "home": row["home"],
        "away": row["away"],
        "competition": row["competition"],
        "stage": row["competition"],
        "kickoff": row["kickoff"],
        "mode": "market_only",
        "odds": snap_data["odds"],
        "context_confirmed": True,
        "field_meta": {"odds": {
            "reliability": 100, "freshness": 100,
            "source": row["source"], "observed_at": snap_data["observed_at"],
        }},
        "assumptions": [f"2026 历史快照登记回测：{snap} 官方HAD"],
        "sporttery_meta": {"match_id": row["sporttery_match_id"],
                           "match_num": row.get("match_num")},
    }


def run(cmd):
    return subprocess.run([sys.executable, *map(str, cmd)],
                          text=True, capture_output=True)


def write_results(mid, row):
    score = row.get("score_90") or []
    if len(score) < 2 or score[0] is None or score[1] is None:
        return False
    rec = {
        "schema_version": "1.0",
        "match_id": mid,
        "status": "finished",
        "score_90": {"home": int(score[0]), "away": int(score[1])},
        "score_et": None, "penalty_winner": None, "advanced": None,
        "source": {"name": row["source"], "url": "https://m.sporttery.cn/mjc/zqsj/",
                   "observed_at": datetime.now(timezone.utc).isoformat()},
        "revision": 1,
    }
    out = STORE / "results" / f"{mid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def process_row(row, registered, snap):
    mid = f"sporttery-{row['sporttery_match_id']}"
    if (mid, snap) in registered:
        return "skipped_existing"
    inp = build_input(row, snap)
    if inp is None:
        return "no_odds"
    ip = WORK / f"{mid}_input.json"
    op = WORK / f"{mid}_output.json"
    ip.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")

    pr = run([ENGINE / "fusion_predict.py", ip, "--output", op])
    if pr.returncode != 0:
        return "predict_error:" + (pr.stderr or pr.stdout)[-150:].strip().replace("\n", " ")
    out = json.loads(op.read_text(encoding="utf-8"))
    if out.get("fusion_status") != "ok":
        return f"blocked:{out.get('fusion_status')}"

    rr = run([ENGINE / "fusion_record.py", "--input", ip, "--output", op,
              "--store", STORE, "--snapshot", snap, "--allow-past"])
    if rr.returncode != 0:
        return "record_error:" + (rr.stderr or rr.stdout)[-150:].strip().replace("\n", " ")
    try:
        st = json.loads(rr.stdout).get("status")
    except Exception:
        st = "unknown"
    if st == "recorded":
        registered.add((mid, snap))
        return "recorded" if write_results(mid, row) else "recorded_no_score"
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", nargs="*", default=LEAGUES)
    ap.add_argument("--snapshots", nargs="*", default=SNAPSHOTS)
    ap.add_argument("--limit", type=int, default=0, help="每联赛最多处理条数（冒烟测试）")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    registered = load_registered()
    stats = {lg: {sn: {"total": 0, "recorded": 0, "skipped_existing": 0,
                       "no_odds": 0, "no_score": 0, "errors": []}
                  for sn in a.snapshots} for lg in a.leagues}

    for lg in a.leagues:
        f = SNAP_DIR / f"{lg}.jsonl"
        if not f.exists():
            print(f"缺少快照文件: {f}")
            continue
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        if a.limit:
            rows = rows[:a.limit]
        for sn in a.snapshots:
            s = stats[lg][sn]
            s["total"] = len(rows)
            for i, row in enumerate(rows, 1):
                st = process_row(row, registered, sn)
                if st == "recorded":
                    s["recorded"] += 1
                elif st == "skipped_existing":
                    s["skipped_existing"] += 1
                elif st == "no_odds":
                    s["no_odds"] += 1
                elif st == "recorded_no_score":
                    s["no_score"] += 1
                else:
                    s["errors"].append(f"{row.get('match_num', '?')}:{st}")
                if i % 40 == 0 or i == len(rows):
                    print(f"{lg} {sn} {i}/{len(rows)} | recorded={s['recorded']} "
                          f"skip={s['skipped_existing']} no_odds={s['no_odds']} "
                          f"err={len(s['errors'])}", flush=True)

    print("\n===== 汇总 =====")
    for lg, snaps in stats.items():
        for sn, s in snaps.items():
            print(f"{lg} {sn}: 共 {s['total']} | 新登记 {s['recorded']} "
                  f"| 已存在跳过 {s['skipped_existing']} | 无赔率 {s['no_odds']} "
                  f"| 无比分 {s['no_score']} | 错误 {len(s['errors'])}")
            for e in s["errors"][:5]:
                print(f"  - {e}")


if __name__ == "__main__":
    main()

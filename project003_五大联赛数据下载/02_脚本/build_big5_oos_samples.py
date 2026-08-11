#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 big5_odds_full.csv 拆成两类研究样本：

1) OOS 回测样本（backtest_selected_leagues_oos.py 格式）：
   {联赛}.jsonl，每行含 kickoff/score_90/snapshots.opening|closing.odds
   opening = Bet365 开盘 1X2（缺则 MarketAvg 开盘）；closing = Pinnacle 收盘 1X2（缺则 MarketAvg 收盘）
2) 校准样本 big5_clean.jsonl（calibrate 用）：
   每行含 league/date/ft/pinnacle_close(1X2)/pinnacle_close_ou25/pinnacle_close_ah
   （Pinnacle 收盘 1X2 必在；AH/OU 缺失的行保留但标记）

用法：python build_big5_oos_samples.py
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

CSV = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\datasets\big5_odds_full.csv"
)
WORK = Path(r"H:\claude AI自媒体\project003_五大联赛数据下载\04_素材")
OOS_DIR = WORK / "oos_big5"
OUT_CLEAN = WORK / "big5_clean.jsonl"

LEAGUE_ABBR = {"英超": "ENG", "西甲": "ESP", "意甲": "ITA", "德甲": "GER", "法甲": "FRA"}


def num(v):
    """空值转 None，否则 float。"""
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def main() -> None:
    OOS_DIR.mkdir(parents=True, exist_ok=True)
    oos = {lg: [] for lg in LEAGUE_ABBR}
    clean = []
    stats = Counter()
    with io.open(CSV, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            lg = row.get("league")
            abbr = LEAGUE_ABBR.get(lg)
            if not abbr:
                continue
            uid = row.get("match_uid")
            date = row.get("match_date") or ""
            ft = (num(row.get("hg")), num(row.get("ag")))
            if ft[0] is None or ft[1] is None:
                stats["no_ft"] += 1
                continue
            score_90 = [int(ft[0]), int(ft[1])]

            # 1X2 开盘/收盘
            open_odds = [num(row.get("x2_Bet365_h")), num(row.get("x2_Bet365_d")), num(row.get("x2_Bet365_a"))]
            if any(x is None or x <= 1.0 for x in open_odds):
                open_odds = [num(row.get("x2_MarketAvg_h")), num(row.get("x2_MarketAvg_d")), num(row.get("x2_MarketAvg_a"))]
            close_odds = [num(row.get("x2_PinnacleClose_h")), num(row.get("x2_PinnacleClose_d")), num(row.get("x2_PinnacleClose_a"))]
            if any(x is None or x <= 1.0 for x in close_odds):
                close_odds = [num(row.get("x2_MarketAvgClose_h")), num(row.get("x2_MarketAvgClose_d")), num(row.get("x2_MarketAvgClose_a"))]

            snapshots = {}
            if all(x is not None and x > 1.0 for x in open_odds):
                snapshots["opening"] = {"odds": open_odds}
            if all(x is not None and x > 1.0 for x in close_odds):
                snapshots["closing"] = {"odds": close_odds}
            if snapshots:
                oos[lg].append({
                    "match_uid": uid, "kickoff": date, "league": lg,
                    "score_90": score_90, "snapshots": snapshots,
                })
                stats["oos_rows"] += 1

            # 校准样本：Pinnacle 收盘 1X2 必在
            pin = [num(row.get("x2_PinnacleClose_h")), num(row.get("x2_PinnacleClose_d")), num(row.get("x2_PinnacleClose_a"))]
            if any(x is None or x <= 1.0 for x in pin):
                stats["no_pin_1x2"] += 1
                continue
            rec = {
                "league": abbr, "league_cn": lg, "date": date, "match_uid": uid,
                "ft": score_90,
                "pinnacle_close": pin,
            }
            ou_over = num(row.get("ou25_PinnacleClose_over"))
            ou_under = num(row.get("ou25_PinnacleClose_under"))
            if ou_over is not None and ou_under is not None and ou_over > 1.0 and ou_under > 1.0:
                rec["pinnacle_close_ou25"] = [ou_over, ou_under]
            ah_line = num(row.get("ah_PinnacleClose_line"))
            ah_h = num(row.get("ah_PinnacleClose_home"))
            ah_a = num(row.get("ah_PinnacleClose_away"))
            if ah_line is not None and ah_h is not None and ah_a is not None and ah_h > 1.0 and ah_a > 1.0:
                # 只用 0.5 步长整半盘（四分之一盘留待后续拆分处理）
                if abs(ah_line * 2 - round(ah_line * 2)) < 1e-9:
                    rec["pinnacle_close_ah"] = {"line": ah_line, "home": ah_h, "away": ah_a}
            clean.append(rec)
            stats["clean_rows"] += 1

    for lg, rows in oos.items():
        rows.sort(key=lambda r: r.get("kickoff") or "")
        p = OOS_DIR / f"{lg}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"OOS {lg}: {len(rows)} 行 -> {p}")

    clean.sort(key=lambda r: (r.get("date") or "", r.get("league_cn") or ""))
    with OUT_CLEAN.open("w", encoding="utf-8") as f:
        for r in clean:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"clean 样本: {len(clean)} 行 -> {OUT_CLEAN}")
    print("stats:", dict(stats))


if __name__ == "__main__":
    main()

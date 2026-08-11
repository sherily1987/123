#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 football_data_big5/*_all_fields.json 提取五大联赛全量赔率，生成 big5_odds_full.csv。

背景：compact CSV 只保留了 1X2 收盘三项；merged_big5 只有 1X2。
本脚本从已解析好的 all_fields JSON（match_uid 已与 46696 场体系对齐）中
把 1X2（27 个开盘/收盘来源）、大小球 2.5（10 个）、亚盘（10 个）全部拍平成宽表。

输出：
  shared/football-quant-fusion/datasets/big5_odds_full.csv   （宽表，utf-8-sig）
  shared/football-quant-fusion/datasets/big5_odds_full_summary.json
  project003/05_交付/big5_odds_full_说明.md

用法：python build_big5_odds_full.py
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter, OrderedDict
from pathlib import Path

SHARED = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\datasets"
)
FD_DIR = SHARED / "football_data_big5"
OUT_CSV = SHARED / "big5_odds_full.csv"
OUT_SUMMARY = SHARED / "big5_odds_full_summary.json"
PROJ_DOC = Path(r"H:\claude AI自媒体\project003_五大联赛数据下载\05_交付\big5_odds_full_说明.md")

FILES = [
    ("英超", "eng_premier_league"),
    ("西甲", "esp_la_liga"),
    ("意甲", "ita_serie_a"),
    ("德甲", "ger_bundesliga"),
    ("法甲", "fra_ligue_1"),
]


def clean(key: str) -> str:
    """来源键转列名前缀：保留字母数字，其余转下划线。"""
    return "".join(ch if ch.isalnum() else "_" for ch in key)


def score_str(v):
    if v is None:
        return ""
    return str(v)


def main() -> None:
    order = OrderedDict()  # 列名 -> 顺序
    order["match_uid"] = None
    order["league"] = None
    order["season"] = None
    order["div"] = None
    order["match_date"] = None
    order["home"] = None
    order["away"] = None
    order["FTR"] = None
    order["hg"] = None
    order["ag"] = None

    srcs_1x2: list[str] = []
    srcs_ou: list[str] = []
    srcs_ah: list[str] = []
    seen1: set[str] = set()
    seen2: set[str] = set()
    seen3: set[str] = set()
    rows: list[dict] = []
    coverage = Counter()

    for abbr, folder in FILES:
        p = FD_DIR / f"{folder}_all_fields.json"
        data = json.load(io.open(p, encoding="utf-8"))
        for m in data["matches"]:
            o1 = m.get("odds_1x2") or {}
            o2 = m.get("odds_ou25") or {}
            o3 = m.get("odds_ah") or {}
            seen1.update(o1.keys())
            seen2.update(o2.keys())
            seen3.update(o3.keys())
            row = {
                "match_uid": m.get("match_uid"),
                "league": abbr,
                "season": m.get("season"),
                "div": m.get("div"),
                "match_date": m.get("matchDate"),
                "home": m.get("home"),
                "away": m.get("away"),
                "FTR": m.get("FTR"),
                "hg": m.get("score_90", [None, None])[0] if m.get("score_90") else None,
                "ag": m.get("score_90", [None, None])[1] if m.get("score_90") else None,
            }
            for key, odds in o1.items():
                for suf, k in (("h", "h"), ("d", "d"), ("a", "a")):
                    row[f"x2_{clean(key)}_{suf}"] = odds.get(k)
            for key, odds in o2.items():
                row[f"ou25_{clean(key)}_over"] = odds.get("over")
                row[f"ou25_{clean(key)}_under"] = odds.get("under")
            for key, odds in o3.items():
                row[f"ah_{clean(key)}_line"] = odds.get("line")
                row[f"ah_{clean(key)}_home"] = odds.get("home")
                row[f"ah_{clean(key)}_away"] = odds.get("away")
            rows.append(row)

            # 覆盖统计：以 Pinnacle 收盘 1X2 / OU25 收盘 / 亚盘收盘 为准
            if o1.get("PinnacleClose", {}).get("h") is not None:
                coverage["x1x2_pinnacle_close"] += 1
            if o2.get("PinnacleClose", {}).get("over") is not None:
                coverage["ou25_pinnacle_close"] += 1
            if o3.get("PinnacleClose", {}).get("home") is not None:
                coverage["ah_pinnacle_close"] += 1
            if o3.get("B365Close", {}).get("home") is not None:
                coverage["ah_b365_close"] += 1
            if o2.get("B365Close", {}).get("over") is not None:
                coverage["ou25_b365_close"] += 1

    srcs_1x2 = sorted(seen1)
    srcs_ou = sorted(seen2)
    srcs_ah = sorted(seen3)
    for k in srcs_1x2:
        for suf in ("h", "d", "a"):
            order[f"x2_{clean(k)}_{suf}"] = None
    for k in srcs_ou:
        order[f"ou25_{clean(k)}_over"] = None
        order[f"ou25_{clean(k)}_under"] = None
    for k in srcs_ah:
        order[f"ah_{clean(k)}_line"] = None
        order[f"ah_{clean(k)}_home"] = None
        order[f"ah_{clean(k)}_away"] = None

    fields = list(order.keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    summary = {
        "schema": "big5-odds-full-1.0",
        "source": "football-data.co.uk mmz4281 CSV（经 football_data_big5/*_all_fields.json）",
        "total_matches": len(rows),
        "by_league": dict(Counter(r["league"] for r in rows)),
        "season_span": {"min": min(r["season"] for r in rows), "max": max(r["season"] for r in rows)},
        "sources": {
            "x1x2": srcs_1x2,
            "ou25": srcs_ou,
            "ah": srcs_ah,
        },
        "coverage": dict(coverage),
        "columns": len(fields),
        "out_csv": str(OUT_CSV),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    doc = f"""# big5_odds_full.csv 数据说明

- 来源：football-data.co.uk（五大联赛 mmz4281 全历史 CSV，93/94–25/26）
- 生成：`project003/02_脚本/build_big5_odds_full.py`（2026-08-03）
- 行数：{len(rows)}（{summary['by_league']}）
- 覆盖：{summary['season_span']}
- 列数：{len(fields)}

## 列结构

- 基础列：match_uid（与 merged_big5/46696 场体系同一 uid）、league、season、div、match_date、home、away、FTR、hg、ag
- 1X2：`x2_<来源>_h/d/a`，来源 {len(srcs_1x2)} 个（含开盘+收盘：Bet365、Pinnacle、MarketMax、MarketAvg、BetfairExchange、WilliamHill、Ladbrokes、VCBet、CL、BMG、BV、BFE 等）
- 大小球2.5：`ou25_<来源>_over/_under`，来源 {len(srcs_ou)} 个（B365、Pinnacle、MarketMax、MarketAvg、BFE × 开盘/收盘）
- 亚盘：`ah_<来源>_line/_home/_away`，来源 {len(srcs_ah)} 个

## 覆盖统计

{json.dumps(dict(coverage), ensure_ascii=False, indent=2)}

> 注：老赛季（如 93/94–2004/05）多数公司只有 1X2，亚盘/大小球/收盘盘口自 2005/06 前后才逐步齐全；缺失单元格为空。
"""
    PROJ_DOC.parent.mkdir(parents=True, exist_ok=True)
    PROJ_DOC.write_text(doc, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

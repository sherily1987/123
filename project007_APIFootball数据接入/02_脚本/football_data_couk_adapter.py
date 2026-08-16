#!/usr/bin/env python3
"""football-data.co.uk 适配器（免费历史 CSV，自带赔率）。

⚠️ 与本仓库已有的 `football_data_adapter.py` **不是同一个源**：
   那个是 football-data.**org** 的 v4 API，认证、字段、联赛体系都不同，不要混用。

覆盖两种格式：
  new      `new/<CODE>.csv`          25 列，2012 年起，**只有收盘赔率**，无射门统计
  mmz4281  `mmz4281/<赛季>/<DIV>.csv` 120 列，分赛季文件，含射门/射正/角球与多档赔率

## 两条必须坚持的口径

1. **收盘赔率 ≠ 赛前快照**。new 格式的赔率列名都带 C（PSCH/AvgCH...），是收盘均价。
   apifootball 管线的基线是"开赛前最后一条报价取中位数"。收盘价是市场最强形态，
   比赛前快照更难被击败，**两者不得并表比较**。故本适配器输出的字段名为
   `closing_market_1x2`，与 `provider_market_1x2` 明确区分。
2. **本源没有 team_id**，只有队名。这里由归一化队名派生稳定 id（`fd:<CODE>:<slug>`），
   并在每行标 `team_id_basis: "name_derived"`——它只和队名一样稳定，
   若上游改名仍会分裂身份，不能当作供应商主键看待。

用法：
  python football_data_couk_adapter.py --league BRA --output-dir <标准化目录>
  python football_data_couk_adapter.py --league E1 --seasons 2122 2223 2324 2425 2526 --output-dir ...
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://www.football-data.co.uk"
UA = {"User-Agent": "Mozilla/5.0 (compatible; football-quant-fusion/football-data-couk)"}

# code -> 展示名。new 格式一个文件含全部年份；mmz4281 按赛季分文件。
NEW_FORMAT = {
    "BRA": "Brazil Serie A", "ARG": "Argentina Liga Profesional",
    "JPN": "Japan J1 League", "KOR": "South Korea K League 1",
    "USA": "Major League Soccer",
}
MMZ_FORMAT = {"E1": "England Championship", "E0": "England Premier League",
              "F2": "France Ligue 2", "D2": "Germany 2. Bundesliga"}


def fetch_csv(url: str, retries: int = 2, delay: float = 1.0) -> list[dict[str, str]]:
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                text = r.read().decode("utf-8", "ignore")
            rows = list(csv.DictReader(io.StringIO(text)))
            # 去掉 BOM 键，并丢弃全空行（源文件末尾常有）
            out = []
            for row in rows:
                clean = {(k or "").lstrip("﻿").strip(): (v or "").strip() for k, v in row.items()}
                if any(clean.values()):
                    out.append(clean)
            return out
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"football-data.co.uk 下载失败（{url}）：{last}")


def team_slug(name: str) -> str:
    """归一化队名。实测源里存在 'Colon Santa FE'/'Colon Santa Fe'、
    'Ham-Kam'/'HamKam' 这类异写，归一化后合并为同一支球队。"""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def stable_match_id(code: str, date: str, home: str, away: str) -> int:
    """确定性合成 match_id：本源无比赛 id，但重跑必须得到同一个值。"""
    key = f"{code}|{date}|{team_slug(home)}|{team_slug(away)}"
    return int.from_bytes(hashlib.blake2b(key.encode("utf-8"), digest_size=7).digest(), "big")


def parse_date(value: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    return None


def _f(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def devig(odds: list[float]) -> list[float] | None:
    """比例去水。三项俱全且均 >1 才认。"""
    if len(odds) != 3 or any(o is None or o <= 1 for o in odds):
        return None
    inv = [1.0 / o for o in odds]
    total = sum(inv)
    probs = [round(x / total, 6) for x in inv]
    # 逐项舍入后三项之和可能偏离 1 约 1e-6。引擎有「概率守恒」强制审计，
    # 故把舍入残差并入最大的一项，保证三项精确相加为 1。
    biggest = max(range(3), key=lambda i: probs[i])
    probs[biggest] = round(probs[biggest] + (1.0 - sum(probs)), 6)
    return probs


# 收盘赔率优先级：Pinnacle 收盘 > 市场均值收盘 > Bet365 收盘 > 最高价收盘
NEW_ODDS_PRIORITY = [("PSCH", "PSCD", "PSCA"), ("AvgCH", "AvgCD", "AvgCA"),
                     ("B365CH", "B365CD", "B365CA"), ("MaxCH", "MaxCD", "MaxCA")]
# mmz4281 同时有赛前与收盘列；这里只取**收盘**以保持与 new 格式同口径
MMZ_ODDS_PRIORITY = [("PSCH", "PSCD", "PSCA"), ("AvgCH", "AvgCD", "AvgCA"),
                     ("B365CH", "B365CD", "B365CA"), ("MaxCH", "MaxCD", "MaxCA")]


def pick_closing(row: dict[str, str], priority) -> tuple[list[float] | None, str | None]:
    for cols in priority:
        odds = [_f(row.get(c)) for c in cols]
        probs = devig(odds)
        if probs:
            return probs, cols[0][:-1]  # 去掉末尾 H，留下来源前缀
    return None, None


def normalize_new(row: dict[str, str], code: str, collected_at: str) -> dict[str, Any] | None:
    date = parse_date(row.get("Date", ""))
    hg, ag = _f(row.get("HG")), _f(row.get("AG"))
    home, away = row.get("Home"), row.get("Away")
    if not (date and home and away) or hg is None or ag is None:
        return None
    probs, source = pick_closing(row, NEW_ODDS_PRIORITY)
    out = {
        "provider": "football-data.co.uk", "source_type": "event_result",
        "match_id": stable_match_id(code, date, home, away),
        "league_id": code, "league_name": NEW_FORMAT.get(code, code), "season": row.get("Season"),
        "kickoff": f"{date}T{row.get('Time') or '00:00'}:00",
        "home_id": f"fd:{code}:{team_slug(home)}", "home": home,
        "away_id": f"fd:{code}:{team_slug(away)}", "away": away,
        "actual": [int(hg), int(ag)], "status": "Finished",
        "team_id_basis": "name_derived", "collected_at": collected_at,
        "field_availability": {"statistics": "UNAVAILABLE", "lineup": "UNAVAILABLE"},
    }
    if probs:
        out["closing_market_1x2"] = probs
        out["closing_market_meta"] = {"source": source, "basis": "closing_line",
                                      "note": "收盘均价去水，非赛前快照，不得与 provider_market 并表"}
    return out


def normalize_mmz(row: dict[str, str], code: str, season: str, collected_at: str) -> dict[str, Any] | None:
    date = parse_date(row.get("Date", ""))
    hg, ag = _f(row.get("FTHG")), _f(row.get("FTAG"))
    home, away = row.get("HomeTeam"), row.get("AwayTeam")
    if not (date and home and away) or hg is None or ag is None:
        return None
    probs, source = pick_closing(row, MMZ_ODDS_PRIORITY)
    out = {
        "provider": "football-data.co.uk", "source_type": "event_result",
        "match_id": stable_match_id(code, date, home, away),
        "league_id": code, "league_name": MMZ_FORMAT.get(code, code), "season": season,
        "kickoff": f"{date}T{row.get('Time') or '00:00'}:00",
        "home_id": f"fd:{code}:{team_slug(home)}", "home": home,
        "away_id": f"fd:{code}:{team_slug(away)}", "away": away,
        "actual": [int(hg), int(ag)], "status": "Finished",
        "team_id_basis": "name_derived", "collected_at": collected_at,
        "field_availability": {"statistics": "POST_MATCH", "lineup": "UNAVAILABLE"},
    }
    if probs:
        out["closing_market_1x2"] = probs
        out["closing_market_meta"] = {"source": source, "basis": "closing_line",
                                      "note": "收盘均价去水，非赛前快照，不得与 provider_market 并表"}
    return out


def normalize_mmz_stats(row: dict[str, str], code: str, collected_at: str) -> dict[str, Any] | None:
    """mmz4281 的射门统计。⚠️ 只有总射门与射正，**没有禁区内/外切分**，
    因此代理 xG 公式与五大联赛不同口径，系数必须单独拟合、单独标注。"""
    date = parse_date(row.get("Date", ""))
    home, away = row.get("HomeTeam"), row.get("AwayTeam")
    hs, aas = _f(row.get("HS")), _f(row.get("AS"))
    if not (date and home and away) or hs is None or aas is None:
        return None
    hst, ast = _f(row.get("HST")), _f(row.get("AST"))
    return {
        "provider": "football-data.co.uk", "source_type": "match_statistics",
        "match_id": stable_match_id(code, date, home, away), "league_id": code,
        "kickoff": f"{date}T{row.get('Time') or '00:00'}:00",
        "shots_total": [hs, aas], "shots_on_target": [hst, ast],
        "corners": [_f(row.get("HC")), _f(row.get("AC"))],
        "split_available": False,   # 本源无禁区内外切分
        "xg_usable": hst is not None and ast is not None,
        "xg_basis": "shots_on_target",
        "collected_at": collected_at, "data_class": "POST_MATCH",
    }


def deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for row in rows:
        key = (row.get("provider"), row.get("match_id"))
        if key in seen or key[1] is None:
            continue
        seen.add(key)
        out.append(row)
    return out


def download_league(code: str, output_dir: Path, seasons: list[str] | None = None,
                    raw_dir: Path | None = None) -> dict[str, Any]:
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    events, stats = [], []
    if code in NEW_FORMAT:
        url = f"{BASE}/new/{code}.csv"
        rows = fetch_csv(url)
        if raw_dir:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{code}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        events = [x for x in (normalize_new(r, code, collected_at) for r in rows) if x]
    elif code in MMZ_FORMAT:
        for season in seasons or []:
            rows = fetch_csv(f"{BASE}/mmz4281/{season}/{code}.csv")
            if raw_dir:
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{code}_{season}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            events.extend(x for x in (normalize_mmz(r, code, season, collected_at) for r in rows) if x)
            stats.extend(x for x in (normalize_mmz_stats(r, code, collected_at) for r in rows) if x)
            time.sleep(0.5)
    else:
        raise SystemExit(f"未知联赛代码 {code}；new 格式支持 {sorted(NEW_FORMAT)}，分赛季格式支持 {sorted(MMZ_FORMAT)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    events = sorted(deduplicate(events), key=lambda x: (x["kickoff"], x["match_id"]))
    slug = code.lower()
    ev_path = output_dir / f"fd_{slug}_events.jsonl"
    ev_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in events), encoding="utf-8")
    report = {
        "code": code, "events": len(events), "output": str(ev_path),
        "with_closing_market": sum(1 for x in events if x.get("closing_market_1x2")),
        "teams": len({x["home_id"] for x in events} | {x["away_id"] for x in events}),
        "seasons": sorted({x.get("season") for x in events if x.get("season")}),
    }
    report["closing_coverage_pct"] = round(report["with_closing_market"] / len(events) * 100, 2) if events else None
    if stats:
        stats = sorted(deduplicate(stats), key=lambda x: (x["kickoff"], x["match_id"]))
        st_path = output_dir / f"fd_{slug}_match_stats.jsonl"
        st_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in stats), encoding="utf-8")
        report["statistics"] = {"output": str(st_path), "count": len(stats),
                                "xg_usable": sum(1 for x in stats if x["xg_usable"]),
                                "xg_basis": "shots_on_target"}
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, help=f"{sorted(NEW_FORMAT)} 或 {sorted(MMZ_FORMAT)}")
    ap.add_argument("--seasons", nargs="*", help="分赛季格式必填，如 2122 2223 2324 2425 2526")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path)
    a = ap.parse_args()
    print(json.dumps(download_league(a.league, a.output_dir, a.seasons, a.raw_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""日职完整数据校准：api-sports xG + football-data 收盘线对齐全后回测。

两套源不得当成同一市场：
  - apisports_japan_j1_league：有队 ID 与代理 xG，无赛前赔率
  - fd_jpn：有收盘线，无射门/xG

本脚本只把 fd 收盘挂到对得上的 api-sports 场次上，字段名仍是
closing_market_1x2，不写进 provider_market。生产 market_only 不改。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJ = ROOT / "project021_五大联赛APIFootball训练"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

JAPAN = {
    "id": 98,
    "slug": "apisports_japan_j1_league",
    "name": "J1 League",
    "country": "Japan",
    "kind": "domestic_league",
    "source": "api-sports.io",
}

# api-sports 短名 -> football-data.co.uk 队名 slug
FD_SLUG_ALIASES = {
    "consadolesapporo": "hokkaidoconsadolesapporo",
    "jubiloiwata": "iwata",
    "kashima": "kashimaantlers",
    "kyotosanga": "kyoto",
    "machidazelvia": "machida",
    "urawa": "urawareds",
    "tokyoverdy": "verdy",
}


def team_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def fd_slug(name: str) -> str:
    raw = team_slug(name)
    return FD_SLUG_ALIASES.get(raw, raw)


def kickoff_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")[:19]).date()
    except ValueError:
        return None


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def attach_closing(api_rows: list[dict], fd_rows: list[dict]) -> tuple[list[dict], dict]:
    """按开球日 ±1 天 + 主客 slug 把收盘线挂到 api-sports 场次。"""
    index: dict[tuple[date, str, str], list[dict]] = {}
    for row in fd_rows:
        day = kickoff_day(row.get("kickoff"))
        if day is None or not row.get("closing_market_1x2"):
            continue
        key = (day, team_slug(row.get("home")), team_slug(row.get("away")))
        index.setdefault(key, []).append(row)

    attached = unmatched = ambiguous = 0
    out = []
    for row in api_rows:
        rec = dict(row)
        day = kickoff_day(row.get("kickoff"))
        home, away = fd_slug(row.get("home")), fd_slug(row.get("away"))
        hits = []
        if day is not None:
            for delta in (0, -1, 1):
                hits.extend(index.get((day + timedelta(days=delta), home, away), []))
        uniq = []
        seen = set()
        for hit in hits:
            mid = hit.get("match_id")
            if mid in seen:
                continue
            seen.add(mid)
            uniq.append(hit)
        if len(uniq) == 1:
            rec["closing_market_1x2"] = uniq[0]["closing_market_1x2"]
            rec["closing_market_meta"] = {
                "source": "football-data.co.uk",
                "fd_match_id": uniq[0].get("match_id"),
                "fd_kickoff": uniq[0].get("kickoff"),
                "note": "收盘线，不得与 provider_market 并表",
            }
            attached += 1
        elif len(uniq) > 1:
            ambiguous += 1
        else:
            unmatched += 1
        out.append(rec)
    audit = {
        "api_n": len(api_rows),
        "fd_n": len(fd_rows),
        "attached": attached,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "attach_pct": round(100.0 * attached / len(api_rows), 1) if api_rows else 0.0,
    }
    return out, audit


def main() -> None:
    ap = argparse.ArgumentParser(description="日职完整数据校准（xG + 收盘线）")
    ap.add_argument("--project", type=Path, default=PROJ)
    args = ap.parse_args()
    project = args.project.resolve()
    norm = project / "04_素材" / "标准化"
    models = project / "03_模型"
    delivery = project / "05_交付"

    api_path = norm / "apisports_japan_j1_league_events.jsonl"
    fd_path = norm / "fd_jpn_events.jsonl"
    xg_path = norm / "apisports_japan_j1_league_xg.jsonl"
    attached_path = norm / "apisports_japan_j1_league_events_closing_attached.jsonl"

    import run_full_backtest as rfb
    import train_five_leagues as training

    api_rows = load_jsonl(api_path)
    fd_rows = load_jsonl(fd_path)
    attached, join_audit = attach_closing(api_rows, fd_rows)
    attached_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in attached),
        encoding="utf-8",
    )

    trained = training.train_one_league(api_path, JAPAN, models, baseline_key="frequency_baseline",
                                        baseline_label="frequency")
    (delivery / "apisports_japan_j1_league_training_report.json").write_text(
        json.dumps(trained, ensure_ascii=False, indent=2), encoding="utf-8")

    goals_close = rfb.backtest_league(project, "JPN", "fd_jpn_events.jsonl", None, "closing_market")
    xg_freq = rfb.backtest_league(project, 98, "apisports_japan_j1_league_events.jsonl",
                                  "apisports_japan_j1_league_xg.jsonl", "provider_market")
    xg_close = rfb.backtest_league(project, 98, attached_path.name,
                                   "apisports_japan_j1_league_xg.jsonl", "closing_market")

    def gap(row: dict) -> float | None:
        if isinstance(row.get("model_subset"), float) and isinstance(row.get("market"), float):
            return round(row["model_subset"] - row["market"], 4)
        if isinstance(row.get("model_subset"), float) and isinstance(row.get("frequency"), float):
            return round(row["model_subset"] - row["frequency"], 4)
        return None

    report = {
        "schema": "japan-j1-complete-calibration-1.0",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "production_unchanged": "MARKET_BASELINE / market_only，未改权重、未 bump m3",
        "join": join_audit,
        "attached_path": str(attached_path),
        "xg_path": str(xg_path),
        "training": {
            "status": trained.get("status"),
            "eligibility": trained.get("eligibility"),
            "model_path": trained.get("model_path"),
        },
        "backtests": {
            "fd_jpn_goals_vs_closing": {**goals_close, "gap": gap(goals_close)},
            "apisports_xg_vs_frequency": {**xg_freq, "gap": gap(xg_freq)},
            "apisports_xg_vs_closing_joined": {**xg_close, "gap": gap(xg_close)},
        },
        "note": [
            "fd_jpn 与 apisports 队名字段不同，只按 slug 别名对齐，不对齐的场次不加收盘。",
            "收盘线组与 provider_market 组不得并表。",
            "日职与欧洲联赛无共同欧战样本，不能并入 cross_league_calibration 的 s_L。",
        ],
    }
    out = delivery / "japan_j1_calibration.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

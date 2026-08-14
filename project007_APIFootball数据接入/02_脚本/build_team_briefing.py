#!/usr/bin/env python3
"""赛前球队信息包：从 api-sports.io 拉伤停/近况/积分榜/交锋，
渲染成 LLM 轨现有的 evidence_XXX.md 格式（6 节：伤停/阵容、战意/动机、
近况/状态、主客/旅行/天气、赔率、身份核验），同时落一份结构化 briefing.json。

## 设计边界（明确写清楚，避免误用）

1. **只提供事实，不产出权重**。量化轨要用这些信息调整 λ（attack_absence_home
   这类 adjustment_ledger 字段），数值本身不在这里生成——那需要专门的历史回测
   校准，不能顺手编。本脚本只负责把原始数据整理成证据，怎么变成数值留给
   之后的校准工作或 LLM 定性判断。
2. **主客场天气、赔率两节 api-sports.io 完全没有**，渲染时明确标"证据缺口"，
   不留空也不编造，跟现有 evidence_XXX.md 的证据缺口写法一致。
3. **伤停覆盖率因联赛/赛季而异**（沙职2022-2024是False，2025才True），
   拿不到就如实写"未取得该联赛该赛季的伤停数据"，不能假装没有伤病。

用法：
  python build_team_briefing.py \
    --home-id 2929 --away-id 2945 --home-name "Al-Ahli Jeddah" --away-name "Al-Hazm" \
    --league-id 307 --season 2025 --match-num "周三001" \
    --kickoff "2026-08-13T21:00:00+08:00" \
    --output-dir <evidence目录>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("api_football_adapter", HERE / "api_football_adapter.py")
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(adapter)

SRC = "api-sports.io"


def recent_fixtures(team_id: int, league_id: int, season: int, n: int = 5) -> list[dict]:
    # 必须锁定 league+season，否则 team+last 会把季前热身赛、其它赛事的比赛
    # 也算进"近况"（实测踩过：Al-Ahli 的近况混进了对阵 Fulham 的季前热身赛）。
    data = adapter.get("/fixtures", {"team": team_id, "league": league_id, "season": season, "last": n})
    out = []
    for f in data.get("response", []):
        if f["fixture"]["status"].get("short") != "FT":
            continue
        goals = f.get("goals") or {}
        home = f["teams"]["home"]
        away = f["teams"]["away"]
        is_home = home.get("id") == team_id
        gf, ga = (goals.get("home"), goals.get("away")) if is_home else (goals.get("away"), goals.get("home"))
        opp = away.get("name") if is_home else home.get("name")
        result = "胜" if (gf or 0) > (ga or 0) else ("负" if (gf or 0) < (ga or 0) else "平")
        out.append({"date": f["fixture"]["date"][:10], "opponent": opp, "venue": "主" if is_home else "客",
                     "score": f"{gf}-{ga}", "result": result})
    return out


def standings_row(league_id: int, season: int, team_id: int) -> dict | None:
    data = adapter.get("/standings", {"league": league_id, "season": season})
    for grp in data.get("response", []):
        for table in grp.get("league", {}).get("standings", []):
            for row in table:
                if row["team"]["id"] == team_id:
                    total = len(table)
                    return {"rank": row.get("rank"), "total_teams": total, "points": row.get("points"),
                            "played": (row.get("all") or {}).get("played"), "goal_diff": row.get("goalsDiff"),
                            "form": row.get("form")}
    return None


def injuries_for_team(league_id: int, season: int, team_id: int) -> list[dict] | None:
    try:
        data = adapter.get("/injuries", {"league": league_id, "season": season, "team": team_id})
    except Exception:
        return None
    rows = [{"player": x.get("player", {}).get("name"), "type": x.get("player", {}).get("type"),
             "reason": x.get("player", {}).get("reason")}
            for x in data.get("response", [])]
    return rows


def h2h(home_id: int, away_id: int, n: int = 5) -> list[dict]:
    data = adapter.get("/fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": n})
    out = []
    for f in data.get("response", []):
        if f["fixture"]["status"].get("short") != "FT":
            continue
        goals = f.get("goals") or {}
        out.append({"date": f["fixture"]["date"][:10], "home": f["teams"]["home"]["name"],
                     "away": f["teams"]["away"]["name"], "score": f"{goals.get('home')}-{goals.get('away')}"})
    return out


def _bullet(fact: str, note: str, ts: str) -> str:
    return f"- {fact} | source({SRC}) | collected_at({ts})"


def render_section_absence(label: str, rows: list[dict] | None, ts: str) -> list[str]:
    if rows is None:
        return [_bullet(f"{label}：未取得该联赛该赛季的伤停数据（api-sports.io 该联赛/赛季 injuries 覆盖为空）",
                         "coverage_gap", ts)]
    if not rows:
        return [_bullet(f"{label}：api-sports.io 伤停接口无返回记录，不代表确认无伤病，可能是该接口未覆盖", "empty", ts)]
    names = "、".join(f"{r['player']}（{r['reason'] or r['type']}）" for r in rows[:10])
    return [_bullet(f"{label}缺阵：{names}", "injuries", ts)]


def render_section_form(label: str, fixtures: list[dict], ts: str) -> list[str]:
    if not fixtures:
        return [_bullet(f"{label}：未取得可用的近期赛果", "empty", ts)]
    seq = "、".join(f"{f['date']} {f['venue']}战{f['opponent']} {f['score']}{f['result']}" for f in fixtures)
    return [_bullet(f"{label}近{len(fixtures)}场：{seq}", "recent_form", ts)]


def render_section_motive(label: str, row: dict | None, ts: str) -> list[str]:
    if row is None:
        return [_bullet(f"{label}：未取得积分榜数据", "empty", ts)]
    return [_bullet(f"{label}联赛排名第{row['rank']}/{row['total_teams']}，{row['points']}分"
                     f"（{row['played']}场，净胜球{row['goal_diff']}），近况{row['form'] or '未知'}",
                     "standings", ts)]


def build_markdown(home: str, away: str, match_num: str, kickoff: str,
                    home_form, away_form, home_absence, away_absence,
                    home_standing, away_standing, h2h_rows, ts: str) -> str:
    lines = [f"# {match_num} {home} vs {away}｜赛前证据（api-sports.io）", "",
              f"> 数据源：api-sports.io，非网页检索证据；仅覆盖该源实际提供的字段，"
              f"缺口如实标注不编造。开球时间 {kickoff}。", ""]
    lines += ["## 1. 伤停/阵容"] + render_section_absence(f"{home}(主)", home_absence, ts) \
              + render_section_absence(f"{away}(客)", away_absence, ts) + [""]
    lines += ["## 2. 战意/动机（积分榜位置推断，非战意本身的直接证据）"] \
              + render_section_motive(f"{home}(主)", home_standing, ts) \
              + render_section_motive(f"{away}(客)", away_standing, ts) + [""]
    lines += ["## 3. 近况/状态"] + render_section_form(f"{home}(主)", home_form, ts) \
              + render_section_form(f"{away}(客)", away_form, ts) + [""]
    lines += ["## 4. 主客/旅行/天气",
              _bullet("证据缺口：api-sports.io 不提供天气/差旅数据，本节留空，不得由 LLM 臆测填补", "unavailable", ts), ""]
    lines += ["## 5. 赔率",
              _bullet("证据缺口：api-sports.io 当前账号 odds 接口对历史数据返回为空，赔率请用体彩/apifootball.com 原有数据源",
                       "unavailable", ts), ""]
    lines += ["## 6. 身份核验",
              _bullet(f"{home} vs {away}，api-sports.io team_id 已在调用参数中锁定，不依赖名称模糊匹配", "identity", ts)]
    if h2h_rows:
        h2h_txt = "；".join(f"{r['date']} {r['home']} {r['score']} {r['away']}" for r in h2h_rows)
        lines += ["", "## 7. 交锋历史", _bullet(f"近{len(h2h_rows)}次交锋：{h2h_txt}", "h2h", ts)]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home-id", type=int, required=True)
    ap.add_argument("--away-id", type=int, required=True)
    ap.add_argument("--home-name", required=True)
    ap.add_argument("--away-name", required=True)
    ap.add_argument("--league-id", type=int, required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--match-num", required=True)
    ap.add_argument("--kickoff", required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    a = ap.parse_args()

    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    home_form = recent_fixtures(a.home_id, a.league_id, a.season)
    away_form = recent_fixtures(a.away_id, a.league_id, a.season)
    home_standing = standings_row(a.league_id, a.season, a.home_id)
    away_standing = standings_row(a.league_id, a.season, a.away_id)
    home_absence = injuries_for_team(a.league_id, a.season, a.home_id)
    away_absence = injuries_for_team(a.league_id, a.season, a.away_id)
    h2h_rows = h2h(a.home_id, a.away_id)

    md = build_markdown(a.home_name, a.away_name, a.match_num, a.kickoff,
                         home_form, away_form, home_absence, away_absence,
                         home_standing, away_standing, h2h_rows, ts)

    briefing = {
        "match_num": a.match_num, "home": a.home_name, "away": a.away_name, "kickoff": a.kickoff,
        "source": SRC, "collected_at": ts, "home_id": a.home_id, "away_id": a.away_id,
        "league_id": a.league_id, "season": a.season,
        "home_recent_form": home_form, "away_recent_form": away_form,
        "home_standing": home_standing, "away_standing": away_standing,
        "home_injuries": home_absence, "away_injuries": away_absence, "h2h": h2h_rows,
        # 明确不生成的字段，留给专门的校准工作，防止被误以为"已经算好了"
        "adjustment_suggestions": None,
        "note": "本文件只含原始事实，不含任何数值化的模型调整建议；量化轨权重需专门回测校准后才能生效。",
    }

    a.output_dir.mkdir(parents=True, exist_ok=True)
    slug = f"{a.home_name}_{a.away_name}".replace(" ", "_")
    md_path = a.output_dir / f"evidence_{a.match_num}_{slug}.md"
    json_path = a.output_dir / f"briefing_{a.match_num}_{slug}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "markdown": str(md_path), "json": str(json_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

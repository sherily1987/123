#!/usr/bin/env python3
"""体彩开售监控：一旦比赛转为「已开售」，立即采集赔率并出预测。

## 为什么需要

体彩场次**开售即有赔率**；显示无赔率的是「待开售」，只是时间没到。
所以对体彩比赛不该退化成纯模型预测——等开售即可拿到完整
HAD / 让球 / TTG / 正确比分，走市场基线这条最强路径。

本脚本轮询体彩赛程，检测「待开售 -> 已开售」的跃迁，对新开售的比赛：
  1. 采集完整赔率并去水，给出市场概率（总是可得）
  2. 若两队都能**经已验证的别名**映射到本地模型，附上模型概率与分歧

## 队名映射的纪律

`apifootball_team_aliases.json` 定下的规矩是
「Only verified aliases may be added; fuzzy names never auto-settle」。
本脚本严格遵守：**中文队名一律不做模糊匹配**（"流浪者"既可能是苏超 Rangers
也可能是 QPR），映射不上就如实报出待人工核验，绝不猜。

用法：
  python watch_sporttery_sale.py --project <project021> --once          # 单次轮询
  python watch_sporttery_sale.py --project <project021>                 # 循环（配合 Monitor）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
COLLECTOR = ROOT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts" / "fetch_sporttery_full.py"
ALIAS_VERIFIED = ROOT / "project018_技能工作区整合" / "02_脚本" / "skill" / "football-quant-fusion" / "config" / "apifootball_team_aliases.json"
ALIAS_BIG5 = ROOT / "project003_五大联赛数据下载" / "04_素材" / "合并数据集" / "team_alias.json"

LIST_API = ("https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry"
            "?isFix=0&pageSize=200&pageNo=1&isForceSort=1")
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36",
      "Referer": "https://m.sporttery.cn/mjc/zqsj/", "Accept": "application/json,text/plain,*/*"}
ON_SALE = "已开售"

# 单场制中立场决赛：固定名单，不做规则推断。
# 双回合赛事（欧冠正赛淘汰赛、欧联/欧协联淘汰赛）两回合都在各自主场，不属中立场；
# 只有下面这几项是一场定胜负、且赛制规定在中立场地举行。
NEUTRAL_COMPETITIONS = {"欧超杯", "欧冠决赛", "欧联决赛", "欧协联决赛", "世俱杯决赛"}


def is_neutral_venue(league_name: str) -> bool:
    return (league_name or "").strip() in NEUTRAL_COMPETITIONS


def _load(name: str, path: Path):
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


pno = _load("predict_no_odds", HERE / "predict_no_odds.py")
strength = pno.strength


def load_aliases() -> dict:
    """中文队名 -> 本地模型显示名。只收已验证条目，不做模糊匹配。"""
    out: dict[str, str] = {}
    if ALIAS_BIG5.exists():
        # 该文件是「英文 slug -> 中文」，反转即得；来源是五大联赛人工对照表
        for league in json.loads(ALIAS_BIG5.read_text(encoding="utf-8")).values():
            if isinstance(league, dict):
                for slug, zh in league.items():
                    out.setdefault(zh, slug)
    if ALIAS_VERIFIED.exists():
        data = json.loads(ALIAS_VERIFIED.read_text(encoding="utf-8"))
        out.update(data.get("aliases") or {})
    return out


def fetch_list() -> list[dict]:
    req = urllib.request.Request(LIST_API, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return [m for g in (data["value"].get("matchInfoList") or [])
            for m in (g.get("subMatchList") or [])]


def collect_odds(match_id: int, workdir: Path) -> dict | None:
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"m_{match_id}.json"
    res = subprocess.run([sys.executable, str(COLLECTOR), "--match-id", str(match_id),
                          "--output", str(out)], capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0 or not out.exists():
        return None
    payload = json.loads(out.read_text(encoding="utf-8"))
    return (payload.get("matches") or [None])[0]


def devig(odds):
    if not odds or len(odds) != 3 or any(o is None or o <= 1 for o in odds):
        return None
    inv = [1 / o for o in odds]
    s = sum(inv)
    probs = [round(x / s, 6) for x in inv]
    big = max(range(3), key=lambda i: probs[i])
    probs[big] = round(probs[big] + (1.0 - sum(probs)), 6)
    return probs


def normal(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def build_norm_index(index: dict) -> dict:
    """模型显示名的归一化索引。别名表存的是 slug（astonvilla），
    模型里是显示名（Aston Villa）——归一化后精确相等才算命中，仍不是模糊匹配。"""
    out: dict[str, list] = {}
    for name, entries in index.items():
        out.setdefault(normal(name), []).extend(entries)
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def model_probs(project: Path, index: dict, norm_index: dict, home_en: str, away_en: str, neutral: bool):
    """两队都能解析时给模型概率，否则 None。复用 predict_no_odds 的两套构造纪律。"""
    hs = index.get(home_en) or norm_index.get(normal(home_en)) or []
    aws = index.get(away_en) or norm_index.get(normal(away_en)) or []
    if len(hs) != 1 or len(aws) != 1:
        return None, f"解析失败（命中 {len(hs)}/{len(aws)} 支）"
    (h_slug, h_id, h_key), (a_slug, a_id, a_key) = hs[0], aws[0]
    cross = h_slug != a_slug
    if cross:
        cal = json.loads((project / "05_交付" / "cross_league_calibration_all.json").read_text(encoding="utf-8"))
        k = float(cal.get("shrinkage_k") or 0.0)
        off = cal["calibrated"]["offsets"]
        adv = 0.0 if neutral else float(cal["calibrated"]["home_adv"])
        mh = pno.fit_league(project, h_slug, h_id, use_xg=False, shrinkage_k=k)
        ma = pno.fit_league(project, a_slug, a_id, use_xg=False, shrinkage_k=k)
        ih, ia = strength.team_index(mh)[h_key], strength.team_index(ma)[a_key]
        sh, sa = off.get(h_slug, 0.0), off.get(a_slug, 0.0)
        lam_h = math.exp(adv + (mh["alpha"][ih] + sh) + (ma["beta"][ia] - sa))
        lam_a = math.exp((ma["alpha"][ia] + sa) + (mh["beta"][ih] - sh))
    else:
        mdl = pno.fit_league(project, h_slug, h_id, use_xg=pno.xg_enabled(project, h_slug), shrinkage_k=0.0)
        idx = strength.team_index(mdl)
        ih, ia = idx[h_key], idx[a_key]
        adv = 0.0 if neutral else mdl["home_adv"]
        lam_h = math.exp(adv + mdl["alpha"][ih] + mdl["beta"][ia])
        lam_a = math.exp(mdl["alpha"][ia] + mdl["beta"][ih])
    return pno.summarize(lam_h, lam_a, strength.RHO), ("跨联赛" if cross else h_slug)


def poll_once(project: Path, state_path: Path, aliases: dict, index: dict,
              norm_index: dict, workdir: Path) -> list[str]:
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    seen = set(state.get("reported", []))
    events = []
    records = state.get("records") or {}
    for m in fetch_list():
        if m.get("matchStatusName") != ON_SALE:
            continue
        key = str(m.get("matchId"))
        if key in seen:
            continue
        full = collect_odds(int(key), workdir)
        had = devig((full or {}).get("model_odds"))
        num = m.get("matchNumStr")
        home_zh, away_zh = m.get("homeTeamAbbName"), m.get("awayTeamAbbName")
        line = (f"{num} 开售 {m.get('leagueAbbName')} {home_zh} vs {away_zh}"
                + (" [中立场]" if is_neutral_venue(m.get("leagueAbbName")) else ""))
        rec = {"match_id": key, "num": num, "league": m.get("leagueAbbName"),
               "home_zh": home_zh, "away_zh": away_zh,
               "kickoff": f"{m.get('matchDate')} {m.get('matchTime')}",
               "market_1x2": had, "raw_odds": (full or {}).get("model_odds"),
               "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if had:
            line += f" | 市场 {had[0]*100:.1f}/{had[1]*100:.1f}/{had[2]*100:.1f}"
        else:
            line += " | 赔率未取到"
        # 体彩列表给简称（"巴黎圣曼"），别名表存的是全称（"巴黎圣日尔曼"）。
        # 采集器的 team_ids 带全称，用它做**确定性**补全——仍是精确查表，不是模糊匹配。
        tid = (full or {}).get("team_ids") or {}
        home_en = aliases.get(home_zh) or aliases.get(tid.get("home_full"))
        away_en = aliases.get(away_zh) or aliases.get(tid.get("away_full"))
        rec["home_full"], rec["away_full"] = tid.get("home_full"), tid.get("away_full")
        neutral = is_neutral_venue(m.get("leagueAbbName"))
        rec["neutral_venue"] = neutral
        if home_en and away_en:
            try:
                pred, where = model_probs(project, index, norm_index, home_en, away_en, neutral=neutral)
            except Exception as exc:
                pred, where = None, f"{type(exc).__name__}"
            if pred:
                p = pred["probs_1x2"]
                rec["model_1x2"] = p
                rec["model_scope"] = where
                line += f" | 模型 {p[0]*100:.1f}/{p[1]*100:.1f}/{p[2]*100:.1f}"
                if had:
                    gap = max(abs(p[i] - had[i]) for i in range(3))
                    rec["max_gap_pp"] = round(gap * 100, 1)
                    line += f" | 最大分歧 {gap*100:.1f}pp"
                    if gap > 0.15:
                        line += " ⚠分歧过大，以市场为准"
            else:
                rec["model_note"] = where
                line += f" | 模型不可用（{where}）"
        else:
            miss = [f"{z}({tid.get(k) or '?'})" for z, e, k in
                    ((home_zh, home_en, "home_full"), (away_zh, away_en, "away_full")) if not e]
            rec["unmapped"] = miss
            line += f" | 队名未映射待核验：{miss}"
        records[key] = rec
        seen.add(key)
        events.append(line)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"reported": sorted(seen), "records": records,
                                      "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--state", type=Path)
    ap.add_argument("--workdir", type=Path)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=600, help="轮询间隔秒，默认 600")
    a = ap.parse_args()
    state = a.state or a.project / "05_交付" / "sale_watch_state.json"
    workdir = a.workdir or a.project / "04_素材" / "sporttery_on_sale"

    aliases = load_aliases()
    index = pno.index_teams(a.project)
    norm_index = build_norm_index(index)
    print(f"已加载队名映射 {len(aliases)} 条，本地模型球队 {len(index)} 支", flush=True)

    while True:
        try:
            for line in poll_once(a.project, state, aliases, index, norm_index, workdir):
                print(line, flush=True)
        except Exception as exc:   # 单次失败不终止监控
            print(f"轮询失败 {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        if a.once:
            return
        time.sleep(a.interval)


if __name__ == "__main__":
    main()

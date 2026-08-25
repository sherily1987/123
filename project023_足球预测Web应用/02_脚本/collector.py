# -*- coding: utf-8 -*-
"""project023 — 体彩采集模块：拉取当前在售场次全盘口 + 量化档位标注，生成 predict.py 兼容 raw JSON。

复用 project015 的 fetch_sporttery_full.py（subprocess），不复制采集逻辑。
量化档位：读 project021 的 full_backtest.json，复刻 league_tiers 分档规则。
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FETCH_SCRIPT = Path(r"F:/HM足球比赛预测/project015_足彩移动采集接口导出/02_脚本/fetch_sporttery_full.py")
PROJECT021 = Path(r"F:/HM足球比赛预测/project021_五大联赛APIFootball训练")
FULL_BT = PROJECT021 / "05_交付" / "full_backtest.json"
# 2026-08-16：LLM 工程已迁入仓库内唯一事实源。
LLM_DATA = Path(os.environ.get("FOOTBALL_LLM_ROOT") or (
    HERE.parents[1] / "project018_技能工作区整合" / "02_脚本" / "llm" / "football-llm-predictor")) / "data"

LIST_API = "https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14)",
      "Referer": "https://m.sporttery.cn/mjc/zqsj/?tab=concern"}

# 体彩联赛名 → project021 slug（与 08-15 已验证映射一致）
LEAGUE_SLUG = {
    "荷甲": "eredivisie", "瑞超": "sweden_allsvenskan", "挪超": "norway_eliteserien",
    "英冠": "fd_e1", "葡超": "portugal_primeira_liga", "日职": "apisports_japan_j1_league",
    "沙职": "saudi_pro_league", "西甲": "la_liga", "芬超": "finland_veikkausliiga",
    "巴甲": "fd_bra", "韩职": "apisports_korea_k_league_1",
}
NO_MODEL = {"日乙", "德乙", "美职", "英社区盾"}
TIER_BOUNDS = ((0.010, "A"), (0.018, "B"), (0.030, "C"))
# 频率基线分档阈值（与 predict_no_odds.league_tiers 保持一致：更严）
FREQ_TIER_BOUNDS = ((-0.050, "A"), (-0.020, "B"), (0.0, "C"))
MIN_TEST_N = 120


def league_tiers() -> dict:
    """复刻 predict_no_odds.league_tiers：市场 gap 分档，无市场用频率基线 + F- 前缀。"""
    if not FULL_BT.exists():
        return {}
    fb = json.loads(FULL_BT.read_text(encoding="utf-8"))
    out = {}
    for slug, v in fb.get("leagues", {}).items():
        if not isinstance(v.get("model_subset"), float):
            continue
        if isinstance(v.get("market"), float):
            gap = v["model_subset"] - v["market"]
            basis = "market"
        elif isinstance(v.get("frequency"), float):
            gap = v["model_subset"] - v["frequency"]
            basis = "frequency"
        else:
            continue
        tier = "D"
        if v["n_subset"] >= MIN_TEST_N:
            bounds = TIER_BOUNDS if basis == "market" else FREQ_TIER_BOUNDS
            for bound, label in bounds:
                if gap < bound:
                    tier = label
                    break
        if basis == "frequency":
            tier = f"F-{tier}"
        out[slug] = {"tier": tier, "gap": round(gap, 4), "n": v["n_subset"], "basis": basis}
    return out


def quant_annotation(league_cn: str, tiers: dict) -> str:
    if league_cn in NO_MODEL:
        return "无模型"
    slug = LEAGUE_SLUG.get(league_cn)
    if not slug:
        return "无模型"
    t = tiers.get(slug)
    if not t:
        return "未接入"
    return f"{t['tier']} ({t['basis']})"


def list_pending(sales_day: str) -> list[dict]:
    """体彩列表接口：销售日前后 2 天 × all/concern 全遍历，返回未开球有赔率场次（matchNum 前缀过滤）。"""
    labels = ("周六", "周日") if sales_day >= "2026-08-15" else ("周五", "周六")
    seen = {}
    for d in (sales_day, (date.fromisoformat(sales_day) + timedelta(days=1)).isoformat()):
        for method in ("all", "concern"):
            url = LIST_API + "?" + urllib.parse.urlencode({"method": method, "matchDate": d})
            req = urllib.request.Request(url, headers=UA)
            try:
                data = json.load(urllib.request.urlopen(req, timeout=30))
            except Exception:
                continue
            for day in data.get("value", {}).get("matchInfoList", []):
                for r in day.get("subMatchList", []):
                    st = str(r.get("matchStatusName") or "")
                    if "完成" in st or "取消" in st:
                        continue
                    if r.get("matchStatus") in (0, None):
                        continue
                    num = r.get("matchNumStr") or ""
                    if not any(num.startswith(x) for x in labels):
                        continue
                    seen[num] = {
                        "match_num": num,
                        "match_id": r.get("matchId"),
                        "league": r.get("leagueAllName"),
                        "home": r.get("homeTeamAllName"),
                        "away": r.get("awayTeamAllName"),
                        "kickoff": f"{r.get('matchDate')}T{(r.get('matchTime') or '00:00')[:5]}:00+08:00",
                        "odds_1x2": [r.get("h"), r.get("d"), r.get("a")],
                        "status_name": st,
                    }
    return sorted(seen.values(), key=lambda x: (x["kickoff"], x["match_num"]))


def fetch_raw(sales_day: str, out_raw: Path) -> dict:
    """调 fetch_sporttery_full.py 拉 2 天全盘口，合并生成 raw JSON（predict.py 输入格式）。"""
    parts = []
    for d in (sales_day, (date.fromisoformat(sales_day) + timedelta(days=1)).isoformat()):
        tmp = LLM_DATA / f"raw_part_{d.replace('-', '')}.json"
        r = subprocess.run([sys.executable, str(FETCH_SCRIPT), "--output", str(tmp), "--date", d, "--delay", "0.8"],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not tmp.exists():
            continue
        parts.extend(json.loads(tmp.read_text(encoding="utf-8")).get("matches", []))
    labels = ("周六", "周日") if sales_day >= "2026-08-15" else ("周五", "周六")
    seen, rows = set(), []
    for m in parts:
        mid = m.get("match_id")
        num = m.get("match_num") or ""
        st = str(m.get("status_name") or "")
        if mid in seen or not any(num.startswith(x) for x in labels):
            continue
        if "完成" in st or "取消" in st:
            continue
        seen.add(mid)
        rows.append(m)
    rows.sort(key=lambda m: m.get("kickoff_iso") or "")
    from datetime import datetime, timezone
    out = {
        "schema_version": "1.0", "collector_version": "mobile-3.5.0",
        "source": "中国体彩网移动端官方固定奖金接口",
        "source_urls": ["getMatchDataPageListV1.qry"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sales_day": sales_day, "sales_label": "周六" if sales_day >= "2026-08-15" else "周五",
        "count": len(rows), "matches": rows,
        "notes": [f"project023 自动采集，{len(rows)} 场未开球"],
    }
    out_raw.parent.mkdir(parents=True, exist_ok=True)
    out_raw.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def collect(sales_day: str) -> dict:
    """完整采集流程：列表 + 全盘口 raw + 量化标注。返回 {sales_day, n, matches}。"""
    raw_path = LLM_DATA / f"raw_{sales_day}.json"
    raw = fetch_raw(sales_day, raw_path)
    tiers = league_tiers()
    matches = []
    for m in raw["matches"]:
        odds = m.get("model_odds") or []
        if m.get("hhad") is None and not m.get("model_odds"):
            odds = None
        matches.append({
            "match_num": m.get("match_num"),
            "match_id": m.get("match_id"),
            "league": m.get("league"),
            "home": m.get("home"),
            "away": m.get("away"),
            "kickoff": m.get("kickoff_iso") or m.get("kickoff_local"),
            "odds_1x2": list(odds[:3]) if odds else None,
            "quant_tier": quant_annotation(m.get("league", ""), tiers),
            "status_name": m.get("status_name", "已开售"),
        })
    return {"sales_day": sales_day, "n": len(matches), "raw_path": str(raw_path), "matches": matches}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    print(json.dumps(collect(d), ensure_ascii=False, indent=2))

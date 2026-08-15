#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apifootball MCP 数据证据块生成器 (2026-08-07)
为 predict.py 的六类证据补充结构化硬数据: 国际盘赔率 / 官方数学模型 / 联赛积分榜 / 历史交锋 / 首发阵容(get_lineups)。
生成 evidence_XXX_<队>_mcp.md 放入证据目录, predict.py 会自动拼接进 LLM prompt。

用法:
  python mcp_evidence.py --input data/raw_2026-08-08.json --out-dir data/evidence_2026-08-08
  python mcp_evidence.py --input data/raw_2026-08-08.json --out-dir ... --limit 2        # 只处理前2场
  python mcp_evidence.py --match-id 718665 --home SJK --away Gnistan --league 芬超 --seq 1 --out-dir ...

流程:
  1. 读 raw JSON(体彩采集器) 场次列表 (或 --match-id 手动单场)
  2. get_football_matches 拉比赛日前后 apifootball 比赛 -> 候选池
  3. 按 开球时间(±3h) + 联赛关键词 匹配, 拿到 apifootball match_id
  4. 并发拉: odds / predictions / standings / h2h / lineups(REST get_lineups)
  5. 生成 *_mcp.md 数据块 (UTF-8 无BOM, predict.py 可直接读)

依赖: mcp_query.py 调用内核（project001_足球预测/02_脚本, import 不重复实现）
环境变量: MCP_APIFOOTBALL_API_KEY (MCP) + API_FOOTBALL_KEY (REST lineups)
注意: apifootball MCP 服务器慢(20-60s), odds 批量接口截断50条, 必须单场查。
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _p in (r"F:\HM足球比赛预测\project001_足球预测\02_脚本",):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)

import mcp_query  # noqa: E402  (call/parse 内核, 唯一实现)
import llm_evidence_enrichment as lee

# ---- REST lineups (MCP 无 get_lineups; 用 apiv3 直连) ----
APIV3_BASE = "https://apiv3.apifootball.com/"


def _api_football_key():
    """优先 API_FOOTBALL_KEY, 其次 MCP_APIFOOTBALL_API_KEY。"""
    return (os.environ.get("API_FOOTBALL_KEY") or os.environ.get("MCP_APIFOOTBALL_API_KEY") or "").strip()


def fetch_lineups_rest(match_id, retries=4):
    """GET apiv3 get_lineups?match_id=... 返回原始 dict 或 None。"""
    import time
    import urllib.parse
    import urllib.request

    key = _api_football_key()
    if not key or not match_id:
        return None
    qs = urllib.parse.urlencode({"action": "get_lineups", "APIkey": key, "match_id": str(match_id)})
    url = APIV3_BASE + "?" + qs
    for n in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and data.get("error") is not None:
                return None
            return data
        except Exception:
            time.sleep(2 * (n + 1))
    return None


def _side_lineup(lineup_obj, side):
    side_data = (lineup_obj or {}).get(side) or {}
    if not isinstance(side_data, dict):
        return {"starting": [], "subs": [], "missing": [], "coach": None}
    return {
        "starting": side_data.get("starting_lineups") or [],
        "subs": side_data.get("substitutes") or [],
        "missing": side_data.get("missing_players") or [],
        "coach": side_data.get("coach") or side_data.get("coach_name"),
    }


def parse_lineups_payload(data, match_id):
    """规范化 get_lineups 响应 -> {home, away, available}。"""
    if not data:
        return None
    obj = data
    if isinstance(data, dict):
        obj = data.get(str(match_id)) or data.get(match_id) or data
    if not isinstance(obj, dict):
        return None
    lineup = obj.get("lineup") if "lineup" in obj else obj
    if not isinstance(lineup, dict):
        return None
    home = _side_lineup(lineup, "home")
    away = _side_lineup(lineup, "away")
    avail = bool(home["starting"] or away["starting"] or home["missing"] or away["missing"])
    if not avail:
        return None
    return {"home": home, "away": away, "available": True}


def _fmt_players(rows, limit=11):
    out = []
    for r in (rows or [])[:limit]:
        if not isinstance(r, dict):
            continue
        name = r.get("lineup_player") or r.get("player") or r.get("name") or "?"
        num = r.get("lineup_number") or r.get("number") or ""
        pos = r.get("lineup_position") or r.get("position") or ""
        reason = r.get("lineup_time") or r.get("reason") or r.get("type") or ""
        bit = name
        if num not in ("", None, "0"):
            bit = f"#{num} {name}"
        if pos not in ("", None, "0"):
            bit += f" (pos{pos})"
        if reason and str(reason) not in ("0", ""):
            bit += f" [{reason}]"
        out.append(bit)
    return out


def fmt_lineups_block(lineups, home_en, away_en):
    """首发/替补/缺阵 -> 证据 markdown，供 LLM 阵容/伤停类引用。"""
    if not lineups or not lineups.get("available"):
        return None
    lines = ["## 1c. 首发阵容 / 缺阵 (apifootball get_lineups)", ""]
    lines.append("> 来源: apiv3.apifootball.com/?action=get_lineups | 赛前有名单才写入")
    lines.append("> LLM: 优先引用首发完整度与 missing_players；禁止编造未列出的伤员")
    lines.append("")
    for tag, en, side in (("主队", home_en, "home"), ("客队", away_en, "away")):
        s = lineups.get(side) or {}
        starters = _fmt_players(s.get("starting") or [], 11)
        missing_rows = s.get("missing") or []
        # 缺阵球员按影响等级打 [HIGH]/[MEDIUM]/[LOW] 标签 (Layer 1 结构化分级)
        missing_tagged = []
        for r in missing_rows[:15]:
            base = (_fmt_players([r], 1) or ["缺阵球员"])[0]
            lvl, detail = classify_injury_impact(r)
            if lvl != IMPACT_LOW:
                suffix = f" | impact: {detail}" if detail else ""
                missing_tagged.append(f"{lvl} {base}{suffix}")
            else:
                missing_tagged.append(base)
        subs_n = len(s.get("subs") or [])
        label = f"{tag}({en})" if en else tag
        lines.append(f"### {label}")
        if starters:
            lines.append(f"- 首发({len(starters)}): " + " / ".join(starters))
        else:
            lines.append("- 首发: 暂无公布")
        if missing_tagged:
            lines.append(f"- 缺阵/不可用({len(missing_rows)}): " + " / ".join(missing_tagged))
            n_hi = sum(1 for r in missing_rows if classify_injury_impact(r)[0] == IMPACT_HIGH)
            if n_hi:
                lines.append(f"- ⚠️ {IMPACT_HIGH} 核心缺阵 {n_hi} 人 → 战力折损显著, 方向判断须重点权衡")
        else:
            lines.append("- 缺阵名单: 无或未提供")
        if subs_n:
            lines.append(f"- 替补席人数: {subs_n}")
        coach = s.get("coach")
        if coach:
            if isinstance(coach, list):
                cnames = []
                for c in coach:
                    if isinstance(c, dict):
                        cnames.append(str(c.get("lineup_player") or c.get("name") or ""))
                    else:
                        cnames.append(str(c))
                cnames = [c for c in cnames if c]
                if cnames:
                    lines.append("- 教练: " + ", ".join(cnames))
            else:
                lines.append(f"- 教练: {coach}")
        lines.append("")
    h_m = len((lineups.get("home") or {}).get("missing") or [])
    a_m = len((lineups.get("away") or {}).get("missing") or [])
    h_s = len((lineups.get("home") or {}).get("starting") or [])
    a_s = len((lineups.get("away") or {}).get("starting") or [])
    if h_s and a_s:
        lines.append(f"- 信号: 双方首发已公布 (主{h_s}/客{a_s}); 缺阵人数 主{h_m}/客{a_m}")
        if h_m - a_m >= 2:
            lines.append("- 信号: 主队缺阵明显多于客队 → 阵容完整度偏向客队")
        elif a_m - h_m >= 2:
            lines.append("- 信号: 客队缺阵明显多于主队 → 阵容完整度偏向主队")
    return "\n".join(lines).rstrip() + "\n"


BJ_TZ = timezone(timedelta(hours=8))  # 北京时间

# raw(体彩中文联赛名) -> (apifootball league 关键词列表, country 消歧关键词或None)
LEAGUE_KEYWORDS = {
    "芬超": (["veikkausliiga"], None),
    "挪超": (["eliteserien"], None),
    "瑞超": (["allsvenskan"], None),
    "荷甲": (["eredivisie"], None),
    "荷乙": (["eerste divisie"], None),
    "德甲": (["bundesliga"], None),
    "德乙": (["2. bundesliga", "2. bulgaria"], None),
    "葡超": (["primeira liga"], None),
    "英联赛杯": (["efl cup", "league cup"], None),
    "英足总杯": (["fa cup"], None),
    "日职": (["j1"], "japan"),
    "日乙": (["j2"], "japan"),
    "韩职": (["k league"], "korea"),
    "巴西杯": (["copa do brasil"], None),
    "巴西甲": (["serie a"], "brazil"),
    "欧罗巴": (["europa"], None),
    "欧冠": (["champions"], None),
    "英超": (["premier league"], "england"),
    "英冠": (["championship"], "england"),
    "英甲": (["league one"], "england"),
    "西甲": (["la liga"], None),
    "意甲": (["serie a"], "italy"),
    "法甲": (["ligue 1"], None),
    "法乙": (["ligue 2"], None),
    "巴甲": (["serie a"], "brazil"),
    "苏超": (["premiership"], "scotland"),
    "美职": (["mls"], None),
    "土超": (["super lig"], None),
    "比甲": (["first division a"], None),
    "中超": (["super league"], "china"),
    "阿甲": (["primera division"], "argentina"),
    "墨超": (["liga mx"], None),
}


def mcp_tool(name, args, retries=4):
    """调 MCP 工具, 返回解析后的 JSON dict/list。"""
    sid, body = mcp_query.call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2024-11-05",
                                           "capabilities": {},
                                           "clientInfo": {"name": "mcp_evidence", "version": "1.0"}}},
                               retries=retries)
    sid, body = mcp_query.call({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": name, "arguments": args}},
                               session=sid, retries=retries)
    r = mcp_query.parse(body)
    if "error" in r:
        raise RuntimeError(f"MCP {name} 错误: {r['error']}")
    texts = [item.get("text", "") for item in r.get("result", {}).get("content", []) if item.get("type") == "text"]
    if not texts:
        return {}
    try:
        return json.loads(texts[0])
    except json.JSONDecodeError:
        return {"_raw": texts[0]}


def load_raw(path):
    """读体彩 raw JSON (兼容 utf-8 / utf-8-sig)。"""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc) as f:
                raw = json.load(f)
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    ms = raw.get("matches", []) if isinstance(raw, dict) else raw
    return ms


def to_bj(utc_str):
    """apifootball kickoff_utc -> 北京时间 datetime。"""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            return None
        return dt.astimezone(BJ_TZ).replace(tzinfo=None)
    except Exception:
        return None


def parse_bj(s):
    """raw kickoff_local '2026-08-08 00:00' -> datetime。"""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


# 自动匹配只接受显式维护的跨语言球队别名；未知球队宁可要求 --match-id。
TEAM_NAME_ALIASES = {
    "天狼星": {"sirius"},
    "布鲁马波卡纳": {"brommapojkarna"},
    "韦斯特罗斯": {"vasteras sk", "vasteras"},
    "佐加顿斯": {"djurgarden"},
    "圣克拉拉": {"santa clara"},
    "葡萄牙国民": {"nacional"},
}


def _normal_name(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def _raw_team_name(raw_match, side):
    team_ids = raw_match.get("team_ids") or {}
    return team_ids.get(f"{side}_full") or raw_match.get(side) or ""


def _team_matches(raw_name, candidate_name):
    expected = {_normal_name(raw_name)}
    expected.update(_normal_name(name) for name in TEAM_NAME_ALIASES.get(str(raw_name), set()))
    return bool(_normal_name(candidate_name) and _normal_name(candidate_name) in expected)


def raw_kickoff_bj(raw_match):
    kickoff_iso = raw_match.get("kickoff_iso")
    if kickoff_iso:
        try:
            value = datetime.fromisoformat(str(kickoff_iso).replace("Z", "+00:00"))
            if value.tzinfo is not None and value.utcoffset() is not None:
                return value.astimezone(BJ_TZ).replace(tzinfo=None)
        except ValueError:
            pass
    return parse_bj(raw_match.get("kickoff_local", ""))


def league_match(raw_league, cand):
    """raw 中文联赛名 vs apifootball 候选 (league + country)。"""
    kws = LEAGUE_KEYWORDS.get(raw_league)
    if not kws:
        return False
    keys, country = kws
    lg = str(cand.get("league", "")).lower()
    if not any(k in lg for k in keys):
        return False
    if country:
        ct = str(cand.get("country", "")).lower()
        if country not in ct:
            return False
    return True


def match_raw_to_candidates(raw_matches, candidates, window_sec=90 * 60):
    """按联赛、带时区开球时间、主客球队身份匹配，未知别名时安全拒绝。"""
    pairs = []
    for ri, m in enumerate(raw_matches):
        t_bj = raw_kickoff_bj(m)
        if t_bj is None:
            pairs.append((ri, None))
            continue
        hits = []
        for c in candidates:
            if not league_match(m.get("league", ""), c):
                continue
            t_c = to_bj(c.get("kickoff_utc", ""))
            if t_c is None or abs((t_c - t_bj).total_seconds()) > window_sec:
                continue
            if not (_team_matches(_raw_team_name(m, "home"), c.get("home_team")) and
                    _team_matches(_raw_team_name(m, "away"), c.get("away_team"))):
                continue
            hits.append(c)
        if len(hits) == 1:
            pairs.append((ri, hits[0]))
        elif len(hits) > 1:
            # 联赛和开球时间不足以验证身份（例如同联赛同一时刻开球）。
            # 宁可要求 --match-id 人工核验，也不能把第一个候选复用给多场。
            pairs.append((ri, None))
        else:
            pairs.append((ri, None))
    return pairs


def safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def safe_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# ---------- 证据影响分级 (Layer 1) ----------

IMPACT_HIGH = "[HIGH]"
IMPACT_MEDIUM = "[MEDIUM]"
IMPACT_LOW = "[LOW]"


def classify_injury_impact(player_row, team_total_goals=None):
    """根据球员赛季数据判断缺阵影响等级。
    返回 (等级标签, 量化说明字符串)。
    player_row: apifootball get_lineups missing_players 中的 dict (可能只有 name/reason)。
    team_total_goals: 该队赛季总进球 (可选, 用于计算占比)。
    """
    if not isinstance(player_row, dict):
        return IMPACT_LOW, ""
    # 尝试从球员统计推算
    goals = safe_float(player_row.get("player_goals") or player_row.get("goals"))
    assists = safe_float(player_row.get("player_assists") or player_row.get("assists"))
    minutes = safe_float(player_row.get("player_minutes") or player_row.get("minutes"))
    matches = safe_float(player_row.get("player_match_played") or player_row.get("matches"))

    contribution = (goals or 0) + (assists or 0) * 0.5
    goals_pct = None
    if goals and team_total_goals and team_total_goals > 0:
        goals_pct = goals / team_total_goals * 100

    # 分级逻辑
    if goals_pct is not None and goals_pct >= 15:
        return IMPACT_HIGH, f"赛季{int(goals)}球占比{goals_pct:.0f}%"
    if contribution >= 10:
        return IMPACT_HIGH, f"赛季贡献{contribution:.0f}(进球+助攻×0.5)"
    if minutes and matches and matches > 0 and minutes / matches >= 60 and contribution >= 3:
        return IMPACT_MEDIUM, f"主力轮换(场均{minutes/matches:.0f}分钟, 贡献{contribution:.0f})"
    if contribution >= 2:
        return IMPACT_MEDIUM, f"赛季贡献{contribution:.0f}"
    # 无数据时按位置猜测
    pos = str(player_row.get("lineup_position") or player_row.get("position") or "").lower()
    reason = str(player_row.get("lineup_time") or player_row.get("reason") or player_row.get("type") or "").lower()
    if "gk" in pos or "goalkeeper" in pos or "门将" in pos:
        return IMPACT_MEDIUM, "门将缺阵"
    if any(kw in reason for kw in ("suspended", "red card", "停赛")):
        return IMPACT_MEDIUM, "停赛缺阵"
    return IMPACT_LOW, ""


def classify_odds_divergence(home_odds_list):
    """根据多家机构赔率极差判断盘口分歧等级。
    返回 (等级标签, 说明)。
    """
    if not home_odds_list or len(home_odds_list) < 2:
        return IMPACT_LOW, ""
    spread = max(home_odds_list) - min(home_odds_list)
    if spread >= 0.5:
        return IMPACT_HIGH, f"主胜赔率极差{spread:.2f}, 机构严重分歧"
    if spread >= 0.2:
        return IMPACT_MEDIUM, f"主胜赔率极差{spread:.2f}, 机构有分歧"
    return IMPACT_LOW, "盘口一致"


def classify_standings_gap(home_pos, away_pos, home_pts, away_pts):
    """根据积分排名差判断实力差距等级。"""
    if home_pos is None or away_pos is None:
        return IMPACT_LOW, ""
    pos_gap = abs(home_pos - away_pos)
    pts_gap = abs((home_pts or 0) - (away_pts or 0))
    if pos_gap >= 12 or pts_gap >= 20:
        return IMPACT_HIGH, f"排名差{pos_gap}位, 积分差{pts_gap}分, 实力差距显著"
    if pos_gap >= 6 or pts_gap >= 10:
        return IMPACT_MEDIUM, f"排名差{pos_gap}位, 积分差{pts_gap}分"
    return IMPACT_LOW, f"排名差{pos_gap}位, 实力接近"


def classify_form_trend(recent_form):
    """根据近期战绩(最近6场)判断状态趋势等级。
    recent_form: list of dict, 每条含 home_score/away_score。
    返回 (等级标签, 说明, ppg值)。
    """
    if not recent_form or len(recent_form) < 3:
        return IMPACT_LOW, "", None
    points = 0
    n = 0
    for it in recent_form[:5]:
        hs = safe_float(it.get("home_score"))
        as_ = safe_float(it.get("away_score"))
        if hs is None or as_ is None:
            continue
        n += 1
        # 注意: h2h recent_form 中 home/away 是相对于该队
        # 简化处理: 胜=3 平=1 负=0
        if hs > as_:
            points += 3
        elif hs == as_:
            points += 1
    if n == 0:
        return IMPACT_LOW, "", None
    ppg = points / n
    if ppg >= 2.5:
        return IMPACT_HIGH, f"近{n}场{points}分(场均{ppg:.1f}), 状态火热", ppg
    if ppg <= 0.5:
        return IMPACT_HIGH, f"近{n}场{points}分(场均{ppg:.1f}), 状态低迷", ppg
    if ppg >= 2.0:
        return IMPACT_MEDIUM, f"近{n}场{points}分(场均{ppg:.1f}), 状态不错", ppg
    if ppg <= 1.0:
        return IMPACT_MEDIUM, f"近{n}场{points}分(场均{ppg:.1f}), 状态一般", ppg
    return IMPACT_LOW, f"近{n}场{points}分(场均{ppg:.1f})", ppg


def build_quant_summary(quant: dict) -> str:
    """从收集到的量化指标生成信号摘要段。
    quant: dict 包含各级别指标。
    """
    lines = ["## 量化信号摘要", ""]
    items = []

    # 伤停影响（用缺阵人数判断阵容完整度偏向）
    hm = quant.get("home_missing_count", 0)
    am = quant.get("away_missing_count", 0)
    if hm or am:
        bias = ""
        if hm - am >= 2:
            bias = " → 阵容完整度偏向客队"
        elif am - hm >= 2:
            bias = " → 阵容完整度偏向主队"
        items.append(f"伤停: 主队缺阵{hm}人 / 客队缺阵{am}人{bias}")

    # 赔率分歧
    od = quant.get("odds_divergence_level", "")
    od_detail = quant.get("odds_divergence_detail", "")
    if od and od != IMPACT_LOW:
        items.append(f"赔率分歧: {od} {od_detail}")

    # 实力差
    sg = quant.get("standings_gap_level", "")
    sg_detail = quant.get("standings_gap_detail", "")
    if sg and sg != IMPACT_LOW:
        items.append(f"实力差: {sg} {sg_detail}")

    # 近期状态
    hf = quant.get("home_form_detail", "")
    af = quant.get("away_form_detail", "")
    if hf:
        items.append(f"主队状态: {quant.get('home_form_level', '')} {hf}")
    if af:
        items.append(f"客队状态: {quant.get('away_form_level', '')} {af}")

    # 模型vs市场
    mkt_vs_model = quant.get("model_vs_market", "")
    if mkt_vs_model:
        items.append(f"模型vs市场: {mkt_vs_model}")

    if not items:
        return "## 量化信号摘要\n- 各项指标均在正常范围, 无显著异常信号\n"
    for it in items:
        lines.append(f"- {it}")
    return "\n".join(lines) + "\n"


def collect_quant_signals(odds_list, lineups, standings, h2h, pred=None, home_en="", away_en=""):
    """汇总各块的量化指标, 供 build_quant_summary 生成摘要 (Layer 1 汇总)。"""
    quant = {}
    # 伤停
    if lineups and lineups.get("available"):
        hm_rows = (lineups.get("home") or {}).get("missing") or []
        am_rows = (lineups.get("away") or {}).get("missing") or []
        quant["home_missing_count"] = len(hm_rows)
        quant["away_missing_count"] = len(am_rows)
        quant["injury_impact_home"] = sum(1 for r in hm_rows if classify_injury_impact(r)[0] == IMPACT_HIGH)
        quant["injury_impact_away"] = sum(1 for r in am_rows if classify_injury_impact(r)[0] == IMPACT_HIGH)
    # 赔率分歧
    if odds_list:
        hs = []
        for o in odds_list:
            v = safe_float((o.get("1x2") or {}).get("home"))
            if v:
                hs.append(v)
        lvl, detail = classify_odds_divergence(hs)
        quant["odds_divergence_level"] = lvl
        quant["odds_divergence_detail"] = detail
    # 积分差
    if standings and isinstance(standings, dict):
        hr = ar = None
        for t in standings.get("table", []):
            nm = str(t.get("team", "")).lower()
            if nm == home_en.lower():
                hr = t
            elif nm == away_en.lower():
                ar = t
        if hr and ar:
            lvl, detail = classify_standings_gap(
                safe_int(hr.get("position")), safe_int(ar.get("position")),
                safe_int(hr.get("points")), safe_int(ar.get("points")))
            quant["standings_gap_level"] = lvl
            quant["standings_gap_detail"] = detail
    # 近况
    if h2h:
        for side, key, lk in (("home", "team1_recent_form", "home_form"),
                              ("away", "team2_recent_form", "away_form")):
            rf = h2h.get(key) or []
            lvl, detail, ppg = classify_form_trend(rf)
            quant[f"{lk}_level"] = lvl
            quant[f"{lk}_detail"] = detail
    return quant


def fmt_odds_block(odds_list):
    """odds_list: 该场所有公司条目 -> markdown 段。"""
    if not odds_list:
        return None
    hs, ds, as_, o2, u2 = [], [], [], [], []
    for o in odds_list:
        x = o.get("1x2") or {}
        for v, arr in ((x.get("home"), hs), (x.get("draw"), ds), (x.get("away"), as_)):
            f = safe_float(v)
            if f:
                arr.append(f)
        ou = o.get("over_under_2_5") or {}
        for v, arr in ((ou.get("over"), o2), (ou.get("under"), u2)):
            f = safe_float(v)
            if f:
                arr.append(f)
    n = len(odds_list)
    if not hs:
        return None
    import statistics
    h, d, a = statistics.mean(hs), statistics.mean(ds), statistics.mean(as_)
    inv = 1 / h + 1 / d + 1 / a
    # 盘口分歧影响等级 (Layer 1)
    div_lvl, div_detail = classify_odds_divergence(hs)
    div_txt = f" | {div_lvl} {div_detail}" if div_lvl != IMPACT_LOW else ", 盘口一致"
    lines = [f"## 1. 国际盘赔率 ({n}家公司均值, 更新 {odds_list[0].get('updated','')})",
             f"- 平均: 主胜 {h:.2f} / 平 {d:.2f} / 客胜 {a:.2f}",
             f"- 去水位隐含概率: 主胜 {1/h/inv*100:.1f}% / 平 {1/d/inv*100:.1f}% / 客胜 {1/a/inv*100:.1f}%",
             f"- 主胜分布: {min(hs):.2f}~{max(hs):.2f} (极差 {max(hs)-min(hs):.2f}){div_txt}"]
    if o2:
        lines.append(f"- 大小球2.5: 大 {statistics.mean(o2):.2f} / 小 {statistics.mean(u2):.2f}")
    return "\n".join(lines)


def fmt_predictions_block(pred):
    if not pred:
        return None
    lines = ["## 2. 官方数学模型预测 (apifootball 官方统计模型, 独立于LLM与市场)",
             f"- 主胜 {pred.get('home_win_pct')}% / 平 {pred.get('draw_pct')}% / 客胜 {pred.get('away_win_pct')}% | favorite: {pred.get('favorite')}",
             f"- 双方进球 {pred.get('both_teams_score_pct')}% | 大2.5球 {pred.get('over_2_5_goals_pct')}% / 小2.5球 {pred.get('under_2_5_goals_pct')}%"]
    return "\n".join(lines)


def fmt_standings_block(standings, home_en, away_en):
    if not standings or not isinstance(standings, dict):
        return None
    table = standings.get("table", [])
    rows = []
    home_row = away_row = None
    for t in table:
        if str(t.get("team", "")).lower() == home_en.lower():
            home_row = t
            rows.append(f"- {t.get('team')}: 第{t.get('position')}名 ({t.get('played')}场 "
                        f"{t.get('wins')}胜{t.get('draws')}平{t.get('losses')}负, 进{t.get('goals_for')}失{t.get('goals_against')}, {t.get('points')}分)")
        elif str(t.get("team", "")).lower() == away_en.lower():
            away_row = t
            rows.append(f"- {t.get('team')}: 第{t.get('position')}名 ({t.get('played')}场 "
                        f"{t.get('wins')}胜{t.get('draws')}平{t.get('losses')}负, 进{t.get('goals_for')}失{t.get('goals_against')}, {t.get('points')}分)")
    if not rows:
        return None
    # 新赛季未开始: 全部 0 场, 积分榜无参考价值
    if table and all(str(r.get("played") or "0") in ("0", "") for r in table):
        return "## 3. 联赛积分榜 (战意判断)\n- ⚠️ 新赛季未开始, 积分榜为空, 无战意参考价值"
    lines = ["## 3. 联赛积分榜 (战意判断)"] + rows
    # 积分差影响等级 (Layer 1)
    if home_row and away_row:
        hp = safe_int(home_row.get("position")); ap = safe_int(away_row.get("position"))
        hp_pts = safe_int(home_row.get("points")); ap_pts = safe_int(away_row.get("points"))
        lvl, detail = classify_standings_gap(hp, ap, hp_pts, ap_pts)
        if lvl != IMPACT_LOW:
            lines.append(f"- {lvl} {detail}")
        else:
            lines.append(f"- 实力信号: {detail}")
    return "\n".join(lines)


def utc_date(item):
    """odds/predictions 的 date 参数按 UTC 日期口径(apifootball 实测), 非北京时间。"""
    c = item.get("cand") or {}
    if c.get("kickoff_utc"):
        try:
            value = datetime.fromisoformat(str(c["kickoff_utc"]).replace("Z", "+00:00"))
            if value.tzinfo is not None and value.utcoffset() is not None:
                return value.astimezone(timezone.utc).strftime("%Y-%m-%d")
        except ValueError:
            return None
    raw = item.get("raw") or {}
    kickoff_iso = raw.get("kickoff_iso")
    if kickoff_iso:
        try:
            value = datetime.fromisoformat(str(kickoff_iso).replace("Z", "+00:00"))
            if value.tzinfo is not None and value.utcoffset() is not None:
                return value.astimezone(timezone.utc).strftime("%Y-%m-%d")
        except ValueError:
            return None
    t = parse_bj(raw.get("kickoff_local", ""))
    if t:
        return (t - timedelta(hours=8)).strftime("%Y-%m-%d")  # 北京 -> UTC
    return None


def build_manual_item(args):
    """Build a manual item with the caller-supplied original sequence and kickoff."""
    raw = {
        "match_num": "手动",
        "league": args.league or "",
        "home": args.home,
        "away": args.away,
        "kickoff_iso": args.kickoff_iso,
        "match_id": "",
    }
    cand = {
        "match_id": args.match_id,
        "home_team": args.home,
        "away_team": args.away,
        "kickoff_utc": args.kickoff_iso,
    }
    return {
        "ri": args.seq - 1,
        "raw": raw,
        "mid": args.match_id,
        "home_en": args.home,
        "away_en": args.away,
        "cand": cand,
    }


def fmt_h2h_block(h2h):
    if not h2h:
        return None
    items = h2h.get("head_to_head", []) or []
    lines = []
    if items:
        lines.append("## 4. 历史交锋 H2H")
        for it in items[:8]:
            lines.append(f"- {it.get('date')}: {it.get('home_team')} {it.get('home_score')}-{it.get('away_score')} {it.get('away_team')} ({it.get('league')})")
    rf1 = h2h.get("team1_recent_form") or []
    rf2 = h2h.get("team2_recent_form") or []
    if rf1 or rf2:
        lines.append("")
        lines.append("## 4b. 近期状态 (apifootball 附带数据)")
        for tag, rf in (("主队", rf1), ("客队", rf2)):
            # 近况影响等级 (Layer 1)
            lvl, detail, ppg = classify_form_trend(rf or [])
            if lvl != IMPACT_LOW and detail:
                lines.append(f"- {tag}状态: {lvl} {detail}")
            for it in (rf or [])[:5]:
                lines.append(f"- {tag}: {it.get('date')} {it.get('home_team')} {it.get('home_score')}-{it.get('away_score')} {it.get('away_team')}")
    return "\n".join(lines) if lines else None


def detect_season_opener(standings, h2h):
    """检测赛季首战/赛季初场景: 积分榜全空 或 无近期状态数据。
    08-05 回测教训: 赛季首战无近况/积分数据, 传统量化指标全部失效,
    模型只能靠"主场优势"空话推理 → 5场错4场。必须显式标注数据缺口。"""
    standings_empty = False
    if standings and isinstance(standings, dict):
        table = standings.get("table", [])
        if table and all(str(r.get("played") or "0") in ("0", "") for r in table):
            standings_empty = True
    form_empty = True
    if h2h:
        rf1 = h2h.get("team1_recent_form") or []
        rf2 = h2h.get("team2_recent_form") or []
        if rf1 or rf2:
            form_empty = False
    return standings_empty and form_empty


def build_block(raw_m, cand, odds_list, pred, standings, h2h, mid, lineups=None, api_sports=None):
    home_en = cand.get("home_team", "") if cand else ""
    away_en = cand.get("away_team", "") if cand else ""
    collected_at = datetime.now(timezone.utc).isoformat()
    source_url = "https://apifootball.com/"
    parts = [f"# MCP 数据证据块: {raw_m.get('home','')}({home_en}) vs {raw_m.get('away','')}({away_en}) | {raw_m.get('league','')}",
             "",
             f"> 第三方结构化数据: apifootball MCP | source({source_url}) collected_at({collected_at})",
             f"> match_identity(sporttery_match_id={raw_m.get('match_id', '')};home={raw_m.get('home', '')};away={raw_m.get('away', '')};api_match_id={mid})",
             f"> 竞彩: {raw_m.get('match_num','')} | 体彩matchId {raw_m.get('match_id')} | apifootball match_id {mid}", ""]
    # 赛季首战数据缺口警告 (08-05 回测教训: 此时量化指标全部失效, 主胜偏见高发)
    if detect_season_opener(standings, h2h):
        parts.append("> ⚠️ [赛季首战数据缺口] 积分榜为空且无近期状态数据 → 近况/积分/状态类量化指标全部失效。"
                     "历史回测(2026-08-05)显示此类场次模型靠'主场优势'空话推理, 5场错4场。"
                     "本场必须只依赖伤停/阵容/交锋/赔率/战意证据, 且优先双选, 禁止仅凭'主场作战'选主胜。")
    blocks = [lee.render_sporttery_markets(raw_m, collected_at)]
    if api_sports is not None:
        blocks.append(lee.render_api_sports_evidence(api_sports, collected_at))
    b1 = fmt_odds_block(odds_list)
    if b1:
        blocks.append(b1)
    b_lu = fmt_lineups_block(lineups, home_en, away_en)
    if b_lu:
        blocks.append(b_lu)
    if pred:
        blocks.append(fmt_predictions_block(pred))
        # 模型 vs 市场分歧信号
        try:
            pct_h = float(pred.get("home_win_pct"))
        except (TypeError, ValueError):
            pct_h = None
        if pct_h is not None and odds_list:
            x = odds_list[0].get("1x2") or {}
            h = safe_float(x.get("home"))
            if h:
                mkt_h = 1 / h / (1 / h + 1 / safe_float(x.get("draw") or 1e9) + 1 / safe_float(x.get("away") or 1e9)) * 100
                if abs(mkt_h - pct_h) >= 10:
                    blocks.append(f"- ⚠️ 模型vs市场分歧: 市场主胜 {mkt_h:.0f}% vs 官方模型 {pct_h:.0f}% —— 分歧≥10%, 谨慎追热门, 可考虑双选")
    b3 = fmt_standings_block(standings, home_en, away_en)
    if b3:
        blocks.append(b3)
    b4 = fmt_h2h_block(h2h)
    if b4:
        blocks.append(b4)
    if len(blocks) < 2:
        blocks.append("## 5. 数据缺口\n- 本场 MCP 数据覆盖不全 (部分块未取到), 预测时以人工证据为主, 此块仅参考")
    # Layer 1 量化信号摘要 (置顶注入, 让 LLM 先看到核心异常信号)
    quant = collect_quant_signals(odds_list, lineups, standings, h2h, pred, home_en, away_en)
    if quant:
        blocks.insert(0, build_quant_summary(quant).rstrip("\n"))
    text = "\n\n".join(parts + blocks)
    annotated = []
    for line in text.splitlines():
        if line.lstrip().startswith(("-", "*")):
            if "source(" not in line.lower():
                line += f" source({source_url})"
            if "collected_at(" not in line.lower():
                line += f" collected_at({collected_at})"
        annotated.append(line)
    return "\n".join(annotated).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="apifootball MCP 数据证据块生成器")
    ap.add_argument("--input", help="体彩 raw JSON 路径")
    ap.add_argument("--out-dir", required=True, help="证据输出目录 (predict.py 的 evidence_<date>/ 目录)")
    ap.add_argument("--date-from", help="apifootball 比赛拉取起始日 YYYY-MM-DD (默认 raw 首场日期-1)")
    ap.add_argument("--date-to", help="拉取截止日 (默认 raw 末场日期+1)")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 场 (测试用)")
    ap.add_argument("--match-id", help="手动指定 apifootball match_id (配合 --home/--away/--league/--seq)")
    ap.add_argument("--home", default="", help="手动模式: 主队英文名")
    ap.add_argument("--away", default="", help="手动模式: 客队英文名")
    ap.add_argument("--league", default="", help="手动模式: 中文联赛名")
    ap.add_argument("--seq", type=int, default=1, help="手动模式: 场次序号(证据文件序号)")
    ap.add_argument("--kickoff-iso", default="", help="手动模式: 带时区开球时间，例如 2026-08-10T17:00:00Z")
    ap.add_argument("--workers", type=int, default=4, help="并发数(服务器慢, 默认4)")
    ap.add_argument("--watch-refresh", action="store_true", help="初次生成后监控至T-75并自动刷新")
    ap.add_argument("--refresh-before-minutes", type=int, default=75)
    ap.add_argument("--poll-seconds", type=int, default=60)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # ---- 1. 构造场次清单 ----
    raw_ms = []
    manual = []
    if args.match_id:
        if args.seq < 1:
            ap.error("--seq 必须 >= 1")
        if not args.home or not args.away or not args.kickoff_iso:
            ap.error("手动模式需要 --home、--away 与带时区的 --kickoff-iso")
        if utc_date({"cand": {"kickoff_utc": args.kickoff_iso}}) is None:
            ap.error("--kickoff-iso 必须是带时区的 ISO-8601 时间")
        manual.append(build_manual_item(args))
    else:
        if not args.input:
            ap.error("需要 --input 或 --match-id")
        raw_ms = load_raw(args.input)
        print(f"📋 raw 场次: {len(raw_ms)}")
        if args.limit:
            raw_ms = raw_ms[:args.limit]
        # 拉 apifootball 比赛候选
        dates = [parse_bj(m.get("kickoff_local", "")) for m in raw_ms]
        dates = [d for d in dates if d]
        if not dates:
            ap.error("raw 里没有可解析的 kickoff_local")
        d_from = args.date_from or (min(dates) - timedelta(days=1)).strftime("%Y-%m-%d")
        d_to = args.date_to or (max(dates) + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"🔭 拉取 apifootball 比赛 {d_from} ~ {d_to} ...")
        cands_raw = mcp_tool("get_football_matches", {"date_from": d_from, "date_to": d_to})
        cands = cands_raw if isinstance(cands_raw, list) else cands_raw.get("matches", [])
        print(f"   候选 {len(cands)} 场")
        pairs = match_raw_to_candidates(raw_ms, cands)
        for ri, c in pairs:
            if c:
                manual.append({"ri": ri, "raw": raw_ms[ri], "mid": c.get("match_id"),
                               "home_en": c.get("home_team", ""), "away_en": c.get("away_team", ""),
                               "league_id": c.get("league_id"), "cand": c})
            else:
                print(f"⚠️ 第{ri+1}场 [{raw_ms[ri].get('match_num','')}] {raw_ms[ri].get('home')} vs {raw_ms[ri].get('away')} "
                      f"({raw_ms[ri].get('league')}) 未匹配到 apifootball 比赛, 跳过")

    # ---- 2. 并发拉数据 ----
    lock = threading.Lock()
    results = {}
    futures = {}

    def fetch(kind, name, args_, key):
        try:
            r = mcp_tool(name, args_)
            with lock:
                results.setdefault(kind, {})[key] = r
                print(f"  ✓ {kind} {key}: {str(r)[:80]}")
        except Exception as e:
            with lock:
                results.setdefault(kind, {})[key] = None
                print(f"  ✗ {kind} {key}: {e}")

    def fetch_lineups(mid):
        try:
            parsed = parse_lineups_payload(fetch_lineups_rest(mid), mid)
            with lock:
                results.setdefault("lineups", {})[mid] = parsed
                state = "available" if parsed and parsed.get("available") else "not_available"
                print(f"  ✓ lineups {mid}: {state}")
        except Exception as e:
            with lock:
                results.setdefault("lineups", {})[mid] = None
                print(f"  ✗ lineups {mid}: {e}")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        # odds + predictions: 每场单查 (批量接口截断); date 用 UTC 日期口径
        for item in manual:
            mid = item["mid"]
            d = utc_date(item)
            if d is None:
                print(f"⚠️ 跳过 {mid}: 缺少可验证的带时区开球时间")
                continue
            futures[ex.submit(fetch, "odds", "get_football_odds",
                              {"date_from": d, "date_to": d, "match_id": mid}, mid)] = ("odds", mid)
            futures[ex.submit(fetch, "preds", "get_football_predictions",
                              {"date_from": d, "date_to": d, "match_id": mid}, mid)] = ("preds", mid)
            futures[ex.submit(fetch_lineups, mid)] = ("lineups", mid)
        # standings: 按 league_id 去重
        league_ids = {}
        for item in manual:
            lid = item.get("league_id")
            if lid:
                league_ids.setdefault(lid, item)
        for lid, item in league_ids.items():
            futures[ex.submit(fetch, "standings", "get_football_standings", {"league_id": lid}, lid)] = ("standings", lid)
        # h2h: 每对一次
        for item in manual:
            if item.get("home_en") and item.get("away_en"):
                key = f"{item['home_en']}|{item['away_en']}"
                futures[ex.submit(fetch, "h2h", "get_head_to_head",
                                  {"team1_name": item["home_en"], "team2_name": item["away_en"]}, key)] = ("h2h", key)
        for fut in as_completed(futures):
            fut.result()

    # ---- 3. 生成文件 ----
    made = 0
    contexts = []
    api_client = lee.ApiSportsClient()
    for item in manual:
        ri = item["ri"] + 1
        raw_m = item["raw"]
        mid = item["mid"]
        home_en = item.get("home_en", "")
        away_en = item.get("away_en", "")
        odds_list = (results.get("odds", {}).get(mid) or {}).get("odds", [])
        pred = (results.get("preds", {}).get(mid) or {}).get("predictions", [{}])[0] or None
        standings = results.get("standings", {}).get(str(item.get("league_id", "")), None) if item.get("league_id") else None
        h2h = results.get("h2h", {}).get(f"{home_en}|{away_en}", None)
        lineups = results.get("lineups", {}).get(mid)
        kickoff = raw_m.get("kickoff_iso") or (item.get("cand") or {}).get("kickoff_utc")
        api_sports = (api_client.collect_match(home_en, away_en, kickoff)
                      if home_en and away_en and kickoff else
                      {"status": "UNAVAILABLE", "reason": "missing_identity_or_kickoff"})
        block = build_block(raw_m, item.get("cand") or {}, odds_list, pred, standings, h2h, mid,
                            lineups=lineups, api_sports=api_sports)
        fname = f"evidence_{ri:03d}_{re.sub(r'[^a-z0-9]+', '_', home_en.lower())}_{re.sub(r'[^a-z0-9]+', '_', away_en.lower())}_mcp.md"
        path = os.path.join(args.out_dir, fname)
        written = lee.write_canonical_snapshot(path, block, datetime.now(timezone.utc).isoformat())
        contexts.append({"item": item, "path": path, "kickoff": kickoff,
                         "odds_list": odds_list, "pred": pred, "standings": standings,
                         "h2h": h2h, "lineups": lineups})
        made += 1
        print(f"📄 {path} ({len(block)}字, archived={written['archived']})")
    print(f"\n✅ 完成, 生成 {made} 个 MCP 数据块 -> {args.out_dir}")

    if args.watch_refresh and contexts:
        pending = {str(ctx["item"]["mid"]): ctx for ctx in contexts if ctx.get("kickoff")}
        print(f"👀 T-{args.refresh_before_minutes} watcher 启动, 待刷新 {len(pending)} 场", flush=True)
        while pending:
            now = datetime.now(timezone.utc)
            for key, ctx in list(pending.items()):
                kickoff_dt = datetime.fromisoformat(ctx["kickoff"].replace("Z", "+00:00"))
                if now >= kickoff_dt.astimezone(timezone.utc):
                    print(f"⛔ {key} 已开球, 禁止刷新", flush=True)
                    pending.pop(key)
                    continue
                if not lee.refresh_due(kickoff_dt, now, args.refresh_before_minutes):
                    continue
                item = ctx["item"]
                home_en, away_en = item.get("home_en", ""), item.get("away_en", "")
                refreshed_api = api_client.collect_match(home_en, away_en, ctx["kickoff"])
                try:
                    refreshed_lineups = parse_lineups_payload(fetch_lineups_rest(item["mid"]), item["mid"])
                except Exception:
                    refreshed_lineups = None
                refreshed_block = build_block(
                    item["raw"], item.get("cand") or {}, ctx["odds_list"], ctx["pred"],
                    ctx["standings"], ctx["h2h"], item["mid"],
                    lineups=refreshed_lineups, api_sports=refreshed_api)
                written = lee.write_canonical_snapshot(
                    ctx["path"], refreshed_block, datetime.now(timezone.utc).isoformat())
                print(f"🔄 {key} T-{args.refresh_before_minutes} 刷新完成, archived={written['archived']}", flush=True)
                pending.pop(key)
            if pending:
                time.sleep(max(1, args.poll_seconds))


if __name__ == "__main__":
    main()

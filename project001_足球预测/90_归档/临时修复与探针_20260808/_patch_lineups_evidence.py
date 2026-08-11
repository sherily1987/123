# -*- coding: utf-8 -*-
"""Patch mcp_evidence.py to include apiv3 get_lineups for LLM evidence."""
from __future__ import annotations

import ast
from pathlib import Path

p = Path(r"C:/Users/Administrator/football-llm-predictor/mcp_evidence.py")
t = p.read_text(encoding="utf-8")

t = t.replace(
    "为 predict.py 的六类证据补充结构化硬数据: 国际盘赔率 / 官方数学模型 / 联赛积分榜 / 历史交锋。",
    "为 predict.py 的六类证据补充结构化硬数据: 国际盘赔率 / 官方数学模型 / 联赛积分榜 / 历史交锋 / 首发阵容(get_lineups)。",
)
t = t.replace(
    "  4. 并发拉: odds(单场) / predictions(单场) / standings(按联赛去重) / h2h(每对)",
    "  4. 并发拉: odds / predictions / standings / h2h / lineups(REST get_lineups)",
)
t = t.replace(
    "环境变量: MCP_APIFOOTBALL_API_KEY",
    "环境变量: MCP_APIFOOTBALL_API_KEY (MCP) + API_FOOTBALL_KEY (REST lineups)",
)

HELPER = r'''
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
        missing = _fmt_players(s.get("missing") or [], 15)
        subs_n = len(s.get("subs") or [])
        label = f"{tag}({en})" if en else tag
        lines.append(f"### {label}")
        if starters:
            lines.append(f"- 首发({len(starters)}): " + " / ".join(starters))
        else:
            lines.append("- 首发: 暂无公布")
        if missing:
            lines.append(f"- 缺阵/不可用({len(missing)}): " + " / ".join(missing))
        else:
            lines.append("- 缺阵名单: 无或未提供")
        if subs_n:
            lines.append(f"- 替补席人数: {subs_n}")
        if s.get("coach"):
            lines.append(f"- 教练: {s.get('coach')}")
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

'''

insert_after = "import mcp_query  # noqa: E402  (call/parse 内核, 唯一实现)\n"
if "def fetch_lineups_rest" not in t:
    if insert_after not in t:
        raise SystemExit("insert point missing")
    t = t.replace(insert_after, insert_after + HELPER, 1)

t = t.replace(
    "def build_block(raw_m, cand, odds_list, pred, standings, h2h, mid):",
    "def build_block(raw_m, cand, odds_list, pred, standings, h2h, mid, lineups=None):",
    1,
)

needle = """    b1 = fmt_odds_block(odds_list)
    if b1:
        blocks.append(b1)
    if pred:"""
repl = """    b1 = fmt_odds_block(odds_list)
    if b1:
        blocks.append(b1)
    b_lu = fmt_lineups_block(lineups, home_en, away_en)
    if b_lu:
        blocks.append(b_lu)
    if pred:"""
if needle not in t:
    raise SystemExit("build_block needle missing")
t = t.replace(needle, repl, 1)

marker = "        for fut in as_completed(futures):\n            fut.result()"
lineup_jobs = '''
        # lineups: REST get_lineups（MCP 无此工具）
        def fetch_lineup(mid):
            try:
                raw = fetch_lineups_rest(mid)
                parsed = parse_lineups_payload(raw, mid)
                with lock:
                    results.setdefault("lineups", {})[mid] = parsed
                    n = 0
                    if parsed:
                        n = len((parsed.get("home") or {}).get("starting") or [])
                    print(f"  {'✓' if parsed else '·'} lineups {mid}: starters_home={n}")
            except Exception as e:
                with lock:
                    results.setdefault("lineups", {})[mid] = None
                    print(f"  ✗ lineups {mid}: {e}")

        for item in manual:
            futures[ex.submit(fetch_lineup, item["mid"])] = ("lineups", item["mid"])
'''
if "def fetch_lineup" not in t:
    if marker not in t:
        raise SystemExit("as_completed marker missing")
    t = t.replace(marker, lineup_jobs + "\n" + marker, 1)

old_call = 'block = build_block(raw_m, item.get("cand") or {}, odds_list, pred, standings, h2h, mid)'
new_call = (
    'lineups = results.get("lineups", {}).get(mid)\n'
    '        block = build_block(raw_m, item.get("cand") or {}, odds_list, pred, standings, h2h, mid, lineups=lineups)'
)
if old_call not in t:
    raise SystemExit("build_block call missing")
t = t.replace(old_call, new_call, 1)

p.write_text(t, encoding="utf-8")
ast.parse(t)
print("mcp_evidence OK", len(t))
print("has helpers", "fmt_lineups_block" in t, "fetch_lineups_rest" in t)

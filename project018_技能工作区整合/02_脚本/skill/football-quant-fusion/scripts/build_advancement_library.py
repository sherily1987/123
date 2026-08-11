#!/usr/bin/env python3
"""Build two-leg advancement sample library from Wikipedia (UEFA competitions).

数据源：en.wikipedia.org 的 淘汰赛(knockout phase) 与 资格赛(qualifying) 页面。
- knockout 页面：{{..Bracket-Info}} 括号模板，行格式 seed|team|leg1|leg2|agg|seed|team|leg1|leg2|agg，
  {{aet}} = 加时、{{pso}} = 点球、决赛 "1 (4)" = 点球比分。
- qualifying 页面：{{TwoLegResult|T1|旗|总分|T2|旗|首回合|次回合|(可选 pen=|note=)}}。

输出：每条 = 一场两回合系列（含 90分钟比分、加时标记、点球结果、晋级方）。
数字全部由脚本解析产生。
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

UA = "CodexResearch/1.0 (football data collection)"
D = "\u2013"  # en-dash


def wiki_wikitext(title):
    q = urllib.parse.quote(title)
    u = "https://en.wikipedia.org/w/api.php?action=parse&page=" + q + "&prop=wikitext&format=json&formatversion=2"
    for attempt in range(4):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            if "parse" not in j:
                return None
            return j["parse"]["wikitext"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(8 * (attempt + 1))
                continue
            if e.code in (404, 400):
                return None
            raise
        except Exception:
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def clean_team(s):
    """把 wikitext 队伍字段清洗为可读队名。"""
    s = s.replace("{{aet}}", "").replace("{{pso}}", "")
    s = re.sub(r"\{\{fbaicon\|[^}]*\}\}", "", s)
    s = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = s.replace("'''", "").strip()
    s = re.sub(r"\{\{[^}]*\}\}", "", s).strip()
    return s


def parse_bracket(wt):
    """解析 {{..Bracket-Info}} 括号模板：返回两回合系列列表。"""
    m = re.search(r"\{\{(?:24|32|16)TeamBracket-Info\n(.*?)\}\}\s*<section end", wt, re.S)
    if not m:
        m = re.search(r"\{\{(?:24|32|16)TeamBracket-Info\n(.*?)\n\}\}", wt, re.S)
    if not m:
        return []
    body = m.group(1)
    rows = []
    round_name = "unknown"
    for line in body.splitlines():
        lc = re.search(r"<!--([^>]*)-->", line)
        if lc:
            round_name = lc.group(1).strip()
        flags = {"aet": "{{aet}}" in line, "pso": "{{pso}}" in line}
        line = line.replace("{{aet}}", " ").replace("{{pso}}", " ")
        line = re.sub(r"\{\{fbaicon\|[^}]*\}\}", "", line)
        line = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", line)
        line = re.sub(r"\[\[([^\]]*)\]\]", r"\1", line)
        line = line.replace("'''", "")
        is_two_leg_row = line.strip().startswith("||")
        parts = [x.strip() for x in line.lstrip("|").split("|")]
        parts = [x for x in parts if x]
        if is_two_leg_row and len(parts) >= 10 and parts[2].isdigit() and parts[3].isdigit() and parts[7].isdigit() and parts[8].isdigit():
            t1 = clean_team(parts[1])
            t2 = clean_team(parts[6])
            if not t1 or not t2:
                continue
            m1 = re.search(r"\((\d+)\)", parts[4])
            m2 = re.search(r"\((\d+)\)", parts[9])
            pen = [int(m1.group(1)), int(m2.group(1))] if m1 and m2 else None
            rows.append({
                "round": round_name, "team1": t1, "team2": t2,
                "leg1": [int(parts[2]), int(parts[7])],
                "leg2": [int(parts[3]), int(parts[8])],
                "agg1": parts[4], "agg2": parts[9],
                "aet": flags["aet"], "pso": flags["pso"] or bool(pen),
                "penalty_score": pen,
            })
            continue
        # 无种子行（旧格式）：team1|s1|s2|agg1|team2|s1|s2|agg2
        if is_two_leg_row and len(parts) >= 8 and parts[1].isdigit() and parts[2].isdigit() and parts[5].isdigit() and parts[6].isdigit():
            t1 = clean_team(parts[0])
            t2 = clean_team(parts[4])
            if not t1 or not t2:
                continue
            m1 = re.search(r"\((\d+)\)", parts[3])
            m2 = re.search(r"\((\d+)\)", parts[7])
            pen = [int(m1.group(1)), int(m2.group(1))] if m1 and m2 else None
            rows.append({
                "round": round_name, "team1": t1, "team2": t2,
                "leg1": [int(parts[1]), int(parts[5])],
                "leg2": [int(parts[2]), int(parts[6])],
                "agg1": parts[3], "agg2": parts[7],
                "aet": flags["aet"], "pso": flags["pso"] or bool(pen),
                "penalty_score": pen,
            })
            continue
        # 单场决赛（点球决胜）：venue|seed|team1|score1(pens)|score2|team2|score3(pens)
        if flags["pso"] and not is_two_leg_row:
            pen_pairs = re.findall(r"\((\d+)\)", line)
            if len(pen_pairs) >= 2:
                t1 = t2 = None
                p_parts = [x.strip() for x in line.lstrip("|").split("|")]
                p_parts = [x for x in p_parts if x]
                if len(p_parts) >= 6:
                    t1 = clean_team(p_parts[2])
                    t2 = clean_team(p_parts[5])
                rows.append({
                    "round": round_name, "team1": t1, "team2": t2,
                    "leg1": [None, None], "leg2": None, "agg1": None, "agg2": None,
                    "aet": True, "pso": True,
                    "penalty_score": [int(pen_pairs[0]), int(pen_pairs[1])],
                    "final_single_leg": True,
                })
    return rows


def parse_twoleg(wt):
    """解析 {{TwoLegResult|T1|旗|总分|T2|旗|首|次|pen=?}} 模板（资格赛）。"""
    out = []
    for m in re.finditer(r"\{\{TwoLegResult\|([^}]*)\}\}", wt):
        parts = [x.strip() for x in m.group(1).split("|")]
        if len(parts) < 7:
            continue
        t1, agg, t2 = parts[0], parts[2], parts[3]
        leg1, leg2 = parts[5], parts[6]
        pen = None
        for p in parts[7:]:
            if p.lower().startswith("pen="):
                pen = p.split("=", 1)[1]
        m1 = re.match(r"(\d+)\s*[\u2013-]\s*(\d+)", leg1)
        m2 = re.match(r"(\d+)\s*[\u2013-]\s*(\d+)", leg2)
        if not m1 or not m2:
            continue
        out.append({
            "round": "qualifying", "team1": clean_team(t1), "team2": clean_team(t2),
            "leg1": [int(m1.group(1)), int(m1.group(2))],
            "leg2": [int(m2.group(1)), int(m2.group(2))],
            "agg1": agg, "agg2": None, "penalty_score": pen,
            "aet": "aet" in leg1.lower() or "aet" in leg2.lower() or "a.e.t" in leg1.lower() or "a.e.t" in leg2.lower(),
            "pso": bool(pen) or "pen" in leg1.lower() or "pen" in leg2.lower(),
        })
    return out


def parse_sports_series(wt):
    """解析资格赛 {{#invoke:Sports series|main|...}} 行：
    队1|旗|总分|队2|旗|首回合|次回合，leg 可能带 {{aet}}/点球标记。"""
    out = []
    headings = [(m.group(1).strip(), m.start()) for m in re.finditer(r"^==([^=]+)==\s*$", wt, re.M)]
    for m in re.finditer(r"\{\{#invoke:Sports series\|main\|(.*?)\n\}\}", wt, re.S):
        body = m.group(1)
        round_name = "qualifying"
        for hname, hpos in headings:
            if hpos < m.start():
                round_name = hname
            else:
                break
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            aet = "{{aet}}" in line or "a.e.t" in line
            pso = "{{pso}}" in line or re.search(r"\(\d+\s*[\u2013-]\s*\d+\s*(?:p|pen)", line) is not None
            line = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", line)
            line = re.sub(r"\[\[([^\]]*)\]\]", r"\1", line)
            line = line.replace("'''", "")
            parts = [x.strip() for x in line.lstrip("|").split("|")]
            parts = [x for x in parts if x]
            if len(parts) < 7:
                continue
            t1, agg, t2, leg1, leg2 = parts[0], parts[2], parts[3], parts[5], parts[6]
            m1 = re.match(r"(\d+)\s*[\u2013-]\s*(\d+)", leg1)
            m2 = re.match(r"(\d+)\s*[\u2013-]\s*(\d+)", leg2)
            if not m1 or not m2:
                continue
            pen = None
            pm = re.findall(r"\((\d+)\s*[\u2013-]\s*(\d+)\s*(?:p|pen)", line)
            if pm:
                pen = [int(pm[0][0]), int(pm[0][1])]
            out.append({
                "round": round_name, "team1": clean_team(t1), "team2": clean_team(t2),
                "leg1": [int(m1.group(1)), int(m1.group(2))],
                "leg2": [int(m2.group(1)), int(m2.group(2))],
                "agg1": agg, "agg2": None, "aet": aet, "pso": pso, "penalty_score": pen,
            })
    return out


def transcluded_pages(wt):
    """{{#lst:页面名|节}} 引用的子页面标题。"""
    return re.findall(r"\{\{#lst:([^|}]+)\|", wt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--seasons", default="2023,2024,2025", help="淘汰赛赛季起始年份，逗号分隔")
    ap.add_argument("--include-qualifying", action="store_true", help="附加抓取 2026/27 资格赛（进行中）")
    a = ap.parse_args()

    def comp_name(sy, code):
        if code == "UECL" and sy == 2023:
            return "UEFA Europa Conference League"
        return {"CL": "UEFA Champions League", "UEL": "UEFA Europa League", "UECL": "UEFA Conference League"}[code]

    comps = [("CL", "UEFA Champions League"), ("UEL", "UEFA Europa League"), ("UECL", "UEFA Conference League")]
    ties = []
    pages = []
    for sy in [int(x) for x in a.seasons.split(",")]:
        for code, _ in comps:
            title = f"{sy}{D}{str(sy+1)[-2:]} {comp_name(sy, code)} knockout phase"
            wt = wiki_wikitext(title)
            if not wt:
                print(f"SKIP {title}")
                continue
            pages.append(title)
            for t in parse_bracket(wt):
                t.update({"competition": code, "season": f"{sy}-{sy+1}"})
                ties.append(t)
            time.sleep(0.8)
    if a.include_qualifying:
        for code, _ in comps:
            title = f"2026{D}27 {comp_name(2026, code)} qualifying"
            wt = wiki_wikitext(title)
            if not wt:
                print(f"SKIP {title}")
                continue
            pages.append(title)
            page_titles = [title] + transcluded_pages(wt)
            seen_pages = set()
            for pt in page_titles:
                pt = pt.strip()
                if not pt or pt in seen_pages:
                    continue
                seen_pages.add(pt)
                sub = wiki_wikitext(pt)
                if not sub:
                    continue
                if pt != title:
                    pages.append(pt)
                for t in parse_sports_series(sub) or parse_twoleg(sub):
                    t.update({"competition": code, "season": "2026-27"})
                    ties.append(t)
                time.sleep(0.6)
            time.sleep(0.8)

    # 晋级方推导：两回合总分
    for t in ties:
        if t.get("final_single_leg"):
            continue
        tot1 = t["leg1"][0] + t["leg2"][0]
        tot2 = t["leg1"][1] + t["leg2"][1]
        t["total1"] = tot1
        t["total2"] = tot2
        if tot1 > tot2:
            t["advanced"] = "team1"
        elif tot2 > tot1:
            t["advanced"] = "team2"
        elif t.get("penalty_score"):
            p1, p2 = t["penalty_score"]
            t["advanced"] = "team1" if p1 > p2 else ("team2" if p2 > p1 else "penalties_unknown")
        else:
            t["advanced"] = "penalties_or_et"

    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, "w", encoding="utf-8") as f:
        for t in ties:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    from collections import Counter
    print(json.dumps({
        "status": "ok", "pages": pages, "ties": len(ties),
        "by_comp": dict(Counter(t["competition"] for t in ties)),
        "by_season": dict(Counter(t["season"] for t in ties)),
        "aet": sum(1 for t in ties if t.get("aet")),
        "pso": sum(1 for t in ties if t.get("pso")),
        "output": a.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

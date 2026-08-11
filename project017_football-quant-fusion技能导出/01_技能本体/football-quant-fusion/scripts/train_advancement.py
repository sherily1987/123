#!/usr/bin/env python3
"""train_advancement — 用两回合样本库重训晋级常数（R2①）。

估计两个引擎常数：
1) penalty_home_prob：leg-2 主场球队点球胜率（样本：两回合点球决胜系列）。
   引擎约定 home=leg-2 主场，故取 P(team2 点球胜)。
2) et_tempo：加时进球率相对 90 分钟进球率的倍率。
   tempo = 3 × Σ(加时进球) / Σ(90分钟进球)；加时进球从 Wikipedia Football box
   （|aet=yes + 进球时间戳 ≥91分钟）统计，90分钟进球 = 两腿最终总进球 − 加时进球。

输出：常数估计 + 置信区间 + 覆盖率，写入 predict.py 对应常量（--apply 时）。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/football-quant-fusion/scripts")
import build_advancement_library as B

D = B.D
COMP_PAGES = [
    ("2023", "CL", "UEFA Champions League"),
    ("2023", "UEL", "UEFA Europa League"),
    ("2023", "UECL", "UEFA Europa Conference League"),
    ("2024", "CL", "UEFA Champions League"),
    ("2024", "UEL", "UEFA Europa League"),
    ("2024", "UECL", "UEFA Conference League"),
    ("2025", "CL", "UEFA Champions League"),
    ("2025", "UEL", "UEFA Europa League"),
    ("2025", "UECL", "UEFA Conference League"),
    ("2026", "CL", "UEFA Champions League", "qualifying"),
    ("2026", "UEL", "UEFA Europa League", "qualifying"),
    ("2026", "UECL", "UEFA Conference League", "qualifying"),
]


def clean_name(s):
    return B.clean_team(s)


# [中文功能] 解析 Football box 块
def parse_boxes(wt):
    boxes = []
    for m in re.finditer(r"\{\{Football box[ \t]*\n?(.*?)\n\}\}", wt, re.S):
        boxes.append(_parse_one_box(m.group(1)))
    for m in re.finditer(r"\{\{#invoke:football box\|main\n(.*?)\n\}\}", wt, re.S):
        boxes.append(_parse_one_box(m.group(1)))
    return boxes


def _parse_one_box(body):
    fields = {}
    current = None
    buf = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("|") and "=" in line:
            if current and buf:
                fields.setdefault(current, []).extend(buf)
            key, _, val = line[1:].partition("=")
            current = key.strip()
            val = val.strip()
            buf = [val] if val else []
        elif current and line.startswith("*"):
            buf.append(line)
    if current and buf:
        fields.setdefault(current, []).extend(buf)
    t1 = clean_name((fields.get("team1") or [""])[0])
    t2 = clean_name((fields.get("team2") or [""])[0])
    score = (fields.get("score") or [""])[0]
    aet = str((fields.get("aet") or [""])[0]).strip().lower().startswith("y")
    et_goals = 0
    for side in ("goals1", "goals2"):
        for g in fields.get(side, []) or []:
            mm = re.search(r"\{\{goal\|(\d+)(?:\+(\d+))?", g)
            if mm:
                base = int(mm.group(1))
                if aet and base >= 91:
                    et_goals += 1
    return {"team1": t1, "team2": t2, "score": score, "aet": aet, "et_goals": et_goals}


# [中文功能] Wilson 置信区间（二项）
def wilson_ci(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n))) / den
    return round(c - h, 4), round(c + h, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True, help="advancement_library.jsonl")
    ap.add_argument("--output", required=True)
    ap.add_argument("--apply", action="store_true", help="写回 predict.py 常量")
    a = ap.parse_args()
    ties = [json.loads(x) for x in Path(a.library).read_text(encoding="utf-8").splitlines() if x.strip()]
    pso_ties = [t for t in ties if t.get("pso") and t.get("penalty_score")]
    aet_ties = [t for t in ties if t.get("aet") and t.get("leg1", [None])[0] is not None]

    # 抓取并解析各淘汰赛页的 Football box
    box_map = {}
    pages = []
    for row in COMP_PAGES:
        sy, code, name = row[0], row[1], row[2]
        kind = row[3] if len(row) > 3 else "knockout phase"
        title = f"{sy}{D}{str(int(sy)+1)[-2:]} {name} {kind}"
        wt = B.wiki_wikitext(title)
        if not wt:
            print(f"SKIP {title}")
            continue
        pages.append(title)
        season_key = f"{sy}-{str(int(sy)+1)[-2:]}" if kind == "qualifying" else f"{sy}-{int(sy)+1}"
        page_titles = [title] + B.transcluded_pages(wt)
        seen = set()
        for pt in page_titles:
            pt = pt.strip()
            if not pt or pt in seen:
                continue
            seen.add(pt)
            sub = wt if pt == title else B.wiki_wikitext(pt)
            if not sub:
                continue
            for bx in parse_boxes(sub):
                box_map.setdefault((code, season_key), []).append(bx)
            time.sleep(0.6)
        time.sleep(0.8)

    # 匹配加时系列：找 aet box（任一方位）
    matched = []
    for t in aet_ties:
        key = (t["competition"], t["season"])
        cands = [bx for bx in box_map.get(key, []) if bx["aet"]
                 and ({bx["team1"], bx["team2"]} == {t["team1"], t["team2"]})]
        if not cands:
            continue
        et = max(bx["et_goals"] for bx in cands)
        final_total = (t.get("total1") or 0) + (t.get("total2") or 0)
        ninety = final_total - et
        if ninety <= 0:
            continue
        matched.append({"tie": f"{t['team1']} vs {t['team2']}",
                        "comp": t["competition"], "season": t["season"],
                        "et_goals": et, "final_total": final_total, "ninety_goals": ninety})

    # 点球：P(team2=leg-2 主场 点球胜)
    k2 = sum(1 for t in pso_ties if t["penalty_score"][1] > t["penalty_score"][0])
    k1 = sum(1 for t in pso_ties if t["penalty_score"][0] > t["penalty_score"][1])
    n_pso = len(pso_ties)
    pen_home_prob = (k2 / n_pso) if n_pso else None
    pen_ci = wilson_ci(k2, n_pso)

    # 加时倍率：tempo = 3 × ΣET / Σ90min
    s_et = sum(m["et_goals"] for m in matched)
    s_90 = sum(m["ninety_goals"] for m in matched)
    et_tempo = (3.0 * s_et / s_90) if s_90 else None
    # 简单近似 CI：ET 进球按泊松噪声，用 delta 方法粗略给出区间
    tempo_ci = None
    if s_90:
        p_et = s_et / s_90
        se = math.sqrt(p_et * (1 - p_et) / s_90)
        tempo_ci = (round(3 * max(0.0, p_et - 1.96 * se), 4), round(3 * (p_et + 1.96 * se), 4))

    rep = {
        "schema_version": "advancement-train-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pages": pages,
        "penalty": {
            "n": n_pso,
            "team1_wins": k1, "team2_wins": k2,
            "penalty_home_prob_leg2_home": pen_home_prob,
            "ci_95": pen_ci,
            "note": "team2 为次回合主场球队；引擎 penalty_home_prob 取此值",
        },
        "extra_time": {
            "aet_ties_in_library": len(aet_ties),
            "matched_boxes": len(matched),
            "et_goals_total": s_et,
            "ninety_goals_total": s_90,
            "et_tempo": et_tempo,
            "ci_95": tempo_ci,
            "matches": matched,
        },
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "penalty_n": n_pso, "penalty_home_prob": pen_home_prob, "penalty_ci": pen_ci,
        "aet_matched": len(matched), "et_goals": s_et, "ninety_goals": s_90,
        "et_tempo": et_tempo, "et_ci": tempo_ci,
        "output": a.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

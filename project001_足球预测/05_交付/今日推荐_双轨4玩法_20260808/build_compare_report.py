# -*- coding: utf-8 -*-
"""Build dual-track 4-market comparison report."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent
mo = json.loads(io.open(OUT / "model_output.json", encoding="utf-8-sig").read())
llm = json.loads(io.open(OUT / "llm_predictions.json", encoding="utf-8-sig").read())
inp = json.loads(io.open(OUT / "input.json", encoding="utf-8-sig").read())

H2R = {0: "主胜", 1: "平局", 2: "客胜"}
R2H = {"主胜": "H", "平局": "D", "客胜": "A", "H": "H", "D": "D", "A": "A"}


def argmax_1x2(pct):
    if not pct or len(pct) < 3:
        return None, None
    i = max(range(3), key=lambda k: pct[k] or 0)
    return H2R[i], pct


MAP_HAFU = {
    "HH": "胜胜", "HD": "胜平", "HA": "胜负", "DH": "平胜", "DD": "平平", "DA": "平负",
    "AH": "负胜", "AD": "负平", "AA": "负负",
    "hh": "胜胜", "hd": "胜平", "ha": "胜负", "dh": "平胜", "dd": "平平", "da": "平负",
    "ah": "负胜", "ad": "负平", "aa": "负负",
}

def hafu_top(hafu_model):
    if not hafu_model:
        return None, None
    probs = hafu_model.get("prob_pct") or hafu_model.get("market_prob_pct")
    labels = hafu_model.get("state_labels")
    if not probs:
        return None, None
    # labels might be 胜胜 etc
    if not labels:
        labels = ["胜胜", "胜平", "胜负", "平胜", "平平", "平负", "负胜", "负平", "负负"]
    if isinstance(probs, dict):
        best = max(probs, key=lambda k: probs[k] or 0)
        return MAP_HAFU.get(best, best), probs.get(best)
    if isinstance(probs, list) and labels and len(probs) == len(labels):
        i = max(range(len(probs)), key=lambda k: probs[k] or 0)
        lab = labels[i]
        return MAP_HAFU.get(lab, lab), probs[i]
    return None, None


def quant_row(r):
    fc = r.get("forecast") or {}
    co = r.get("core_output") or {}
    final = fc.get("final_1x2_pct") or co.get("final_1x2_pct")
    mkt = fc.get("market_prob_pct") or co.get("market_prob_pct")
    direction, _ = argmax_1x2(final)
    mdir, _ = argmax_1x2(mkt)
    tops = fc.get("top_scores") or co.get("top_scores") or []
    if tops and isinstance(tops[0], dict):
        score = tops[0].get("score")
        score_p = tops[0].get("prob_pct")
    elif tops and isinstance(tops[0], (list, tuple)):
        score = f"{tops[0][0]}-{tops[0][1]}" if len(tops[0]) >= 2 else str(tops[0])
        score_p = None
    else:
        score, score_p = None, None
    ou = fc.get("ou_2_5") or {}
    if isinstance(ou, dict) and ou:
        ou_dir = "大2.5" if (ou.get("over_pct") or 0) >= (ou.get("under_pct") or 0) else "小2.5"
        ou_detail = f"大{ou.get('over_pct')}%/小{ou.get('under_pct')}%"
    else:
        ou_dir, ou_detail = None, None
    hafu_m = co.get("hafu_model") or fc.get("hafu_model") or {}
    # also try sporttery_hafu in core
    if not hafu_m:
        mm = (co.get("multi_market_fit") or {})
        hafu_m = mm.get("hafu") or {}
    hafu_lab, hafu_p = hafu_top(hafu_m if isinstance(hafu_m, dict) else {})
    # fallback: from hafu market in field
    match = r.get("match") or ""
    gate = r.get("recommendation_gate") or {}
    return {
        "match": match,
        "mode": r.get("mode"),
        "1x2": direction,
        "1x2_pct": final,
        "market_1x2": mdir,
        "market_pct": mkt,
        "score": score,
        "score_pct": score_p,
        "ou25": ou_dir,
        "ou25_detail": ou_detail,
        "hafu": hafu_lab,
        "hafu_pct": hafu_p,
        "banker": gate.get("banker_allowed"),
        "dependency": r.get("market_dependency_pct"),
    }


# map quant by normalized ha
def norm(s):
    return re.sub(r"\s+", "", (s or "").lower())


qmap = {}
for r in mo.get("results") or []:
    m = r.get("match") or ""
    # "home vs away"
    if " vs " in m:
        h, a = m.split(" vs ", 1)
    elif " VS " in m:
        h, a = m.split(" VS ", 1)
    else:
        h, a = m, ""
    qmap[norm(h) + "|" + norm(a)] = quant_row(r)
    qmap[norm(h)] = quant_row(r)  # weak

# input match_num map
num_by_ha = {}
for m in inp.get("matches") or []:
    sm = m.get("sporttery_meta") or {}
    num = sm.get("match_num")
    num_by_ha[norm(m.get("home")) + "|" + norm(m.get("away"))] = {
        "num": num,
        "kickoff": m.get("kickoff"),
        "league": m.get("competition") or m.get("league"),
        "odds": m.get("odds"),
        "home": m.get("home"),
        "away": m.get("away"),
    }

rows = []
for item in llm:
    home, away = item.get("home"), item.get("away")
    key = norm(home) + "|" + norm(away)
    meta = num_by_ha.get(key) or {}
    q = qmap.get(key) or qmap.get(norm(home)) or {}
    mk = item.get("markets") or {}
    # LLM 1x2 to code
    l1 = mk.get("1x2")
    q1 = q.get("1x2")
    agree_1x2 = None
    if l1 and q1:
        agree_1x2 = R2H.get(l1, l1) == R2H.get(q1, q1) or l1 == q1
    # score agree exact
    ls, qs = mk.get("score"), q.get("score")
    agree_score = (str(ls) == str(qs)) if ls and qs else None
    # ou
    lo, qo = mk.get("ou25"), q.get("ou25")
    agree_ou = (lo == qo) if lo and qo else None
    # hafu
    lh, qh = mk.get("hafu"), q.get("hafu")
    agree_hafu = (lh == qh) if lh and qh else None

    rows.append(
        {
            "match_num": item.get("match_num") or meta.get("num"),
            "home": home,
            "away": away,
            "league": item.get("league") or meta.get("league"),
            "kickoff": item.get("kickoff") or meta.get("kickoff"),
            "odds": item.get("odds") or meta.get("odds"),
            "quant": q,
            "llm": mk,
            "agree": {
                "1x2": agree_1x2,
                "score": agree_score,
                "ou25": agree_ou,
                "hafu": agree_hafu,
            },
            "llm_models": [
                {
                    "model": (p.get("model") or "").split("/")[-1],
                    "result": p.get("result"),
                    "score": f"{p.get('home_score')}-{p.get('away_score')}" if p.get("home_score") is not None else None,
                    "tg": p.get("total_goals"),
                    "half": p.get("half_result"),
                }
                for p in (item.get("models") or [])
                if not p.get("error")
            ],
        }
    )

# sort by kickoff
rows.sort(key=lambda r: r.get("kickoff") or "")

# stats on pairs where both exist
def rate(key):
    vals = [r["agree"][key] for r in rows if r["agree"][key] is not None]
    if not vals:
        return None, 0
    return sum(1 for v in vals if v) / len(vals), len(vals)


r1, n1 = rate("1x2")
rs, ns = rate("score")
ro, no = rate("ou25")
rh, nh = rate("hafu")

now = datetime.now().strftime("%Y-%m-%d %H:%M")
lines = []
lines.append(f"# 双轨四玩法对照报告 · {now}")
lines.append("")
lines.append("> 量化：football-quant-fusion（market_only 为主）  ")
lines.append("> LLM：智谱 glm-4-flash + 千问 qwen-flash + DeepSeek V3（3 模型投票）  ")
lines.append("> 口径：未开赛场次（采集后过滤 kickoff>采集时点）；无 HAD 场次量化可能缺失  ")
lines.append("> **概率/方向模型输出，非投注建议；market_only≈复述盘口，无独立 edge 不出胆**")
lines.append("")
lines.append("## 覆盖与一致率")
lines.append("")
lines.append(f"- 量化建模：**{len(mo.get('results') or [])}** 场（HAD 可用）")
lines.append(f"- LLM 预测：**{sum(1 for r in llm if r.get('ok'))}/{len(llm)}** 场成功")
lines.append(f"- 胜平负一致率：**{(r1*100):.0f}%**（n={n1}）" if r1 is not None else "- 胜平负一致率：—")
lines.append(f"- 比分完全一致率：**{(rs*100):.0f}%**（n={ns}）" if rs is not None else "- 比分一致率：—")
lines.append(f"- 大小球2.5一致率：**{(ro*100):.0f}%**（n={no}）" if ro is not None else "- 大小球一致率：—")
lines.append(f"- 半全场一致率：**{(rh*100):.0f}%**（n={nh}）" if rh is not None else "- 半全场一致率：—")
lines.append("")
lines.append("## 逐场对照表")
lines.append("")
lines.append("| 编号 | 开球 | 对阵 | 盘口H/D/A | 量化1X2 | LLM1X2 | 一致? | 量化比分 | LLM比分 | 量化大2.5 | LLM大2.5 | 量化半全场 | LLM半全场 |")
lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")

for r in rows:
    q, L, a = r["quant"], r["llm"], r["agree"]
    odds = r.get("odds") or []
    od = f"{odds[0]}/{odds[1]}/{odds[2]}" if isinstance(odds, (list, tuple)) and len(odds) >= 3 else "—"
    def yn(v):
        if v is True:
            return "✅"
        if v is False:
            return "❌"
        return "—"
    q1 = q.get("1x2") or "—"
    if q.get("1x2_pct"):
        p = q["1x2_pct"]
        q1 = f"{q1} ({p[0]:.0f}/{p[1]:.0f}/{p[2]:.0f})"
    kick = (r.get("kickoff") or "")[5:16].replace("T", " ")
    lines.append(
        f"| {r.get('match_num') or '—'} | {kick} | {r['home']} vs {r['away']} | {od} | "
        f"{q1} | {L.get('1x2') or '—'} | {yn(a.get('1x2'))} | "
        f"{q.get('score') or '—'} | {L.get('score') or '—'} | "
        f"{q.get('ou25') or '—'} | {L.get('ou25') or '—'} | "
        f"{q.get('hafu') or '—'} | {L.get('hafu') or '—'} |"
    )

lines.append("")
lines.append("## 分歧场次（胜平负不一致）")
lines.append("")
div = [r for r in rows if r["agree"].get("1x2") is False]
if not div:
    lines.append("无胜平负方向分歧（或量化缺失）。")
else:
    for r in div:
        q, L = r["quant"], r["llm"]
        lines.append(
            f"- **{r.get('match_num')} {r['home']} vs {r['away']}**：量化={q.get('1x2')}{q.get('1x2_pct')} / "
            f"LLM={L.get('1x2')} 比分Q={q.get('score')} L={L.get('score')}"
        )

lines.append("")
lines.append("## 结构清晰场（量化主胜/客胜≥60% 且双轨同向）")
lines.append("")
clear = []
for r in rows:
    q = r["quant"]
    pct = q.get("1x2_pct") or [0, 0, 0]
    mx = max(pct) if pct else 0
    if mx >= 60 and r["agree"].get("1x2") is True:
        clear.append((mx, r))
clear.sort(reverse=True, key=lambda x: x[0])
if not clear:
    lines.append("无。")
else:
    for mx, r in clear:
        q, L = r["quant"], r["llm"]
        lines.append(
            f"- **{r.get('match_num')} {r['home']} vs {r['away']}**：{q.get('1x2')} {mx:.0f}% | "
            f"比分 Q{q.get('score')}/L{L.get('score')} | OU Q{q.get('ou25')}/L{L.get('ou25')} | "
            f"HAFU Q{q.get('hafu')}/L{L.get('hafu')}"
        )

lines.append("")
lines.append("## 玩法说明")
lines.append("")
lines.append("| 玩法 | 量化来源 | LLM 来源 |")
lines.append("|---|---|---|")
lines.append("| 胜平负 | final_1x2_pct argmax（去水盘口） | 3 模型 result 投票 |")
lines.append("| 比分 | top_scores[0] | 比分众数 |")
lines.append("| 大小球2.5 | ou_2_5 over/under | 由总进球档推导（≥3大） |")
lines.append("| 半全场 | hafu_model 概率 argmax | half_result×result 九宫格投票 |")
lines.append("")
lines.append("## 纪律")
lines.append("")
lines.append("- 全部 **banker_allowed=否**（历史门控，不出胆）")
lines.append("- 量化几乎全 **market_only**，与市场方向高度一致属预期")
lines.append("- LLM 半全场/大小球由比分结构推导，证据不足时勿当强信号")
lines.append("- 无 HAD 的埃因霍温/阿马多拉等：量化未建模，仅 LLM")
lines.append("")
lines.append("## 文件")
lines.append("")
lines.append(f"- 目录：`{OUT}`")
lines.append("- `model_output.json` / `llm_predictions.json` / `input.json` / `raw_llm.json`")
lines.append("")
lines.append("*概率模型输出，非投注建议。*")

report = "\n".join(lines)
(OUT / "双轨四玩法对照_20260808.md").write_text(report, encoding="utf-8")
(OUT / "dual_track_4markets.json").write_text(
    json.dumps({"as_of": now, "stats": {"1x2": [r1, n1], "score": [rs, ns], "ou25": [ro, no], "hafu": [rh, nh]}, "rows": rows}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

# copy delivery
deliv = Path(r"H:/claude AI自媒体/project014_football-quant-fusion/05_交付/2026-08-08_双轨四玩法")
deliv.mkdir(parents=True, exist_ok=True)
(deliv / "双轨四玩法对照_20260808.md").write_text(report, encoding="utf-8")
import shutil
for f in ["dual_track_4markets.json", "llm_predictions.json", "model_output.json", "input.json"]:
    shutil.copy2(OUT / f, deliv / f)

print(report[:3500])
print("...")
print("stats", r1, n1, rs, ns, ro, no, rh, nh)
print("rows", len(rows), "div", len(div), "clear", len(clear))
print("wrote", OUT / "双轨四玩法对照_20260808.md")

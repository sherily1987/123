#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build dual-track pending-backtest package for 20260808."""
from __future__ import annotations

import io
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8))
now = datetime.now(BJ)
stamp = now.strftime("%Y-%m-%dT%H:%M%z")
date_key = "20260808"

base = Path(__file__).resolve().parent
raw = json.loads(io.open(base / "raw.json", encoding="utf-8-sig").read())
model = json.loads(io.open(base / "model_output.json", encoding="utf-8-sig").read())
pred_txt = Path(
    r"C:/Users/Administrator/football-llm-predictor/data/predictions_2026-08-08.txt"
).read_text(encoding="utf-8", errors="replace")
reg_dir = base / "registry"
single_dir = base / "single"
shared = Path(
    r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/"
    r"shared/football-quant-fusion/backtest/predictions/2026/08"
)

dests = [
    Path(r"H:/claude AI自媒体/project014_football-quant-fusion/04_素材/待回测记录") / date_key,
    base / "待回测记录" / date_key,
]
for d in dests:
    d.mkdir(parents=True, exist_ok=True)

def _match_str(m):
    if isinstance(m, str):
        return m
    if isinstance(m, dict):
        h = m.get("home") or ""
        a = m.get("away") or ""
        if h and a:
            return f"{h} vs {a}"
        return str(m.get("match") or m)
    return str(m or "")


quant_by_ha = {}
for r in model.get("results") or []:
    # fusion_predict 批量输出：results[] 每项本身就是 fusion payload（不是 {match,output}）
    out = r.get("output") if isinstance(r.get("output"), dict) else r
    fc = out.get("forecast") or out.get("core_output") or out
    mstr = _match_str(r.get("match") or out.get("match"))
    final = (
        fc.get("final_1x2_pct")
        or out.get("final_1x2_pct")
        or (out.get("core_output") or {}).get("final_1x2_pct")
    )
    tops = (
        fc.get("top_scores")
        or out.get("top_scores")
        or (out.get("core_output") or {}).get("top_scores")
        or []
    )
    top_scores = []
    for t in tops[:3]:
        if isinstance(t, dict):
            top_scores.append(str(t.get("score")))
        else:
            top_scores.append(str(t))
    while len(top_scores) < 3:
        top_scores.append(None)
    rg = out.get("recommendation_gate") or {}
    quant_by_ha[mstr] = {
        "final_1x2_pct": final,
        "top_scores": top_scores,
        "mode": out.get("mode") or fc.get("mode"),
        "banker_allowed": rg.get("banker_allowed"),
        "market_prob_pct": fc.get("market_prob_pct") or out.get("market_prob_pct"),
        "raw_result": r,
    }

DIR_MAP = {"主胜": "H", "平局": "D", "客胜": "A"}
llm_by_num = {}
blocks = re.split(r"(?=⚽ 第\d+/\d+场)", pred_txt)
for blk in blocks:
    if "综合方向" not in blk:
        continue
    m = re.search(r"\[([^\]]+)\]\s*(.+?)\s+VS\s+(.+?)\s*\|\s*(.+?)\s*\|\s*(.+)", blk)
    if not m:
        continue
    num, home, away, league, kick = [x.strip() for x in m.groups()]
    dm = re.search(r"综合方向:\s*(\S+)", blk)
    direction = dm.group(1) if dm else None
    sm = re.search(r"强度(\d+)%", blk)
    strength = int(sm.group(1)) if sm else None
    cm = re.search(r"建议双选\s*([^,\n]+)", blk)
    double_hint = cm.group(1).strip() if cm else None
    sp = re.search(r"比分偏好:\s*(\S+)", blk)
    score = sp.group(1) if sp else None
    votes = {}
    vm = re.search(r"投票分布:\s*(.+)", blk)
    if vm:
        for part in vm.group(1).split("|"):
            part = part.strip()
            mm = re.match(r"(主胜|平局|客胜):([\d.]+)", part)
            if mm:
                votes[mm.group(1)] = float(mm.group(2))
    models = []
    for line in blk.splitlines():
        mm = re.search(
            r"\[([^\]]+)\]\s*(主胜|平局|客胜)(?:\s*\(备选:([^)]+)\))?\s*比分:(\S+)\s*—\s*(.+)",
            line,
        )
        if mm:
            models.append(
                {
                    "model": mm.group(1).strip(),
                    "direction": mm.group(2),
                    "alt": mm.group(3),
                    "score": mm.group(4),
                    "reason": mm.group(5).strip()[:120],
                }
            )
    letter = DIR_MAP.get(direction)
    if double_hint:
        parts = re.findall(r"主胜|平局|客胜", double_hint)
        letters = "/".join(DIR_MAP[p] for p in parts if p in DIR_MAP)
        pick = f"双选 {'/'.join(parts)}（{letters}）"
        single_pref = f"{direction}（{letter}）"
    else:
        pick = f"单选 {direction}（{letter}）"
        single_pref = f"{direction}（{letter}）"
    llm_by_num[num] = {
        "match_num": num,
        "home": home,
        "away": away,
        "league": league,
        "direction": direction,
        "letter": letter,
        "strength": strength,
        "double_hint": double_hint,
        "pick": pick,
        "single_pref": single_pref,
        "score": score,
        "votes": votes,
        "models": models,
        "caution": bool(double_hint) or (strength is not None and strength < 60),
    }

quant_records = []
llm_records = []

for m in raw["matches"]:
    num = m["match_num"]
    mid = f"sporttery-{m['match_id']}"
    home, away = m["home"], m["away"]
    ha = f"{home} vs {away}"
    kick = m.get("kickoff_iso") or m.get("kickoff_local")
    league = m.get("league")
    q = quant_by_ha.get(ha)

    cands = sorted(shared.glob(f"{mid}__*__prematch.json"))
    latest = cands[-1] if cands else None
    record_file_name = f"{num}_{latest.name}" if latest else None
    prediction_id = latest.stem if latest else None
    created_at = None
    if latest:
        try:
            meta = json.loads(io.open(latest, encoding="utf-8-sig").read())
            created_at = meta.get("created_at")
        except Exception:
            pass

    for dest in dests:
        s = single_dir / f"{num}.json"
        if s.exists():
            shutil.copy2(s, dest / f"{num}_input.json")
        if q:
            io.open(dest / f"{num}_output.json", "w", encoding="utf-8").write(
                json.dumps(q["raw_result"], ensure_ascii=False, indent=2)
            )
        if latest:
            shutil.copy2(latest, dest / f"{num}_{latest.name}")
        rf = reg_dir / f"{num}.json"
        if rf.exists():
            shutil.copy2(rf, dest / f"{num}_registry.json")

    tops = (q or {}).get("top_scores") or [None, None, None]
    note = None
    registered = bool(latest)
    if num in ("周六001", "周六002"):
        note = "kickoff already passed; refuse store register; local snapshot only"
    elif not m.get("odds_eligible"):
        note = "no HAD; quant modeling skipped"
    elif not q:
        note = "no quant output"

    quant_records.append(
        {
            "match_num": num,
            "match_id": mid,
            "league": league,
            "home": home,
            "away": away,
            "kickoff": kick,
            "final_1x2_pct": (q or {}).get("final_1x2_pct"),
            "top_score_1": tops[0],
            "top_score_2": tops[1],
            "top_score_3": tops[2],
            "record_file": record_file_name,
            "prediction_id": prediction_id,
            "snapshot": "prematch",
            "created_at": created_at,
            "mode": (q or {}).get("mode"),
            "banker_allowed": (q or {}).get("banker_allowed"),
            "market_prob_pct": (q or {}).get("market_prob_pct"),
            "odds_eligible": m.get("odds_eligible"),
            "registered_to_store": registered,
            "note": note,
        }
    )

    L = llm_by_num.get(num)
    if not L:
        continue
    score_picks = [L["score"]] if L.get("score") else []
    for md in L.get("models") or []:
        sc = md.get("score")
        if sc and sc not in score_picks:
            score_picks.append(sc)
    llm_obj = {
        "schema": "llm-track-1.0",
        "track": "LLM证据驱动（3模型：zhipu/qwen/deepseek）",
        "match_num": num,
        "match_id": mid,
        "match": ha,
        "competition": league,
        "kickoff": kick,
        "direction": {
            "pick": L["pick"],
            "single_preference": L["single_pref"],
            "strength_pct": L["strength"],
            "votes": L["votes"],
            "caution": L["caution"],
            "note": "证据以体彩官方盘口+身份核验为主；伤停/近况深搜本轮缺口。",
        },
        "score_picks": score_picks[:3],
        "models": L["models"],
        "signals": [
            f"体彩HAD={m.get('model_odds')}",
            f"HHAD={m.get('model_hhad')}",
            f"LLM强度={L['strength']}%",
        ],
        "evidence": [
            {
                "fact": f"体彩官方胜平负 {m.get('model_odds')}；更新 {m.get('had_updated_at')}",
                "source": m.get("fixed_bonus_url") or "webapi.sporttery.cn",
                "collected_at": stamp,
                "mapped": "odds_official",
                "basis": "sales-day collect 2026-08-08",
            },
            {
                "fact": (
                    f"身份核验 主={(m.get('team_ids') or {}).get('home_full')} "
                    f"客={(m.get('team_ids') or {}).get('away_full')}"
                ),
                "source": "sporttery team_ids",
                "collected_at": stamp,
                "mapped": "identity",
                "basis": "raw.json",
            },
        ],
        "comparison_note": (
            f"量化 final={(q or {}).get('final_1x2_pct')} "
            f"market={(q or {}).get('market_prob_pct')}；LLM {L['pick']} 强度{L['strength']}%"
        ),
        "pre_registered_at": stamp,
        "disclaimer": "LLM 轨道为定性判断（非概率模型输出），仅作对比研究；不构成投注建议。",
    }
    for dest in dests:
        io.open(dest / f"llm_{num}.json", "w", encoding="utf-8").write(
            json.dumps(llm_obj, ensure_ascii=False, indent=2)
        )
    llm_records.append(
        {
            "match_num": num,
            "match_id": mid,
            "match": ha,
            "kickoff": kick,
            "llm_pick": L["pick"],
            "llm_score_picks": score_picks[:3],
            "llm_file": f"llm_{num}.json",
            "quant_file": f"{num}_output.json" if q else None,
            "quant_final_1x2_pct": (q or {}).get("final_1x2_pct"),
            "pre_registered_at": stamp,
            "strength_pct": L["strength"],
            "caution": L["caution"],
        }
    )

index = {
    "schema": "pending-backtest-1.0",
    "kickoff_date": "2026-08-08",
    "sales_day": "2026-08-08",
    "sales_label": "周六",
    "snapshot": "prematch",
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "source_raw": str(base / "raw.json"),
    "notes": [
        "量化：13场销售日，11场有HAD建模；001/002开球后拒绝共享库登记；018/024无HAD",
        "共享库 prematch 成功登记：有HAD且未开球场次",
        "出胆：全部 banker_allowed=False；check_output 11/11 方向一致无失真",
    ],
    "records": quant_records,
}
index_llm = {
    "schema": "llm-track-index-1.0",
    "kickoff_date": "2026-08-08",
    "generated_at": stamp,
    "note": "LLM 对比轨道；3模型 zhipu/qwen/deepseek（国内直连）。海外模型因全局代理劫持未启用。",
    "records": llm_records,
}

for dest in dests:
    shutil.copy2(base / "raw.json", dest / "raw.json")
    shutil.copy2(base / "input.json", dest / "input.json")
    shutil.copy2(base / "model_output.json", dest / "model_output.json")
    for name in [
        "predictions_2026-08-08.txt",
        "预测报告_2026-08-08.md",
        "预测报告_2026-08-08.xlsx",
    ]:
        src = Path(r"C:/Users/Administrator/football-llm-predictor/data") / name
        if src.exists():
            shutil.copy2(src, dest / name)
    io.open(dest / "index.json", "w", encoding="utf-8").write(
        json.dumps(index, ensure_ascii=False, indent=2)
    )
    io.open(dest / "index_llm.json", "w", encoding="utf-8").write(
        json.dumps(index_llm, ensure_ascii=False, indent=2)
    )
    lines = [
        "match_num,match_id,league,home,away,kickoff,final_h,final_d,final_a,top1,registered_to_store,note"
    ]
    for r in quant_records:
        pct = r.get("final_1x2_pct") or [None, None, None]
        lines.append(
            ",".join(
                [
                    r["match_num"],
                    r["match_id"],
                    r.get("league") or "",
                    r["home"],
                    r["away"],
                    str(r.get("kickoff") or ""),
                    str(pct[0] if pct else ""),
                    str(pct[1] if pct else ""),
                    str(pct[2] if pct else ""),
                    str(r.get("top_score_1") or ""),
                    str(r.get("registered_to_store")),
                    (r.get("note") or "").replace(",", ";"),
                ]
            )
        )
    io.open(dest / "index.csv", "w", encoding="utf-8-sig").write("\n".join(lines) + "\n")
    print("DEST", dest)
    print("  files", len(list(dest.iterdir())))
    print(
        "  quant store-registered",
        sum(1 for r in quant_records if r.get("registered_to_store")),
        "/",
        len(quant_records),
    )
    print("  llm", len(llm_records))

print("OK")

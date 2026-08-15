#!/usr/bin/env python3
"""看一条重放 diff 记录的 odds 与当时 market_prob/model 概率，理解 37.4/25.3/37.4 来源。"""
import json
from pathlib import Path

STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")

for line in open(STORE / "registry.jsonl", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    e = json.loads(line)
    if e.get("prediction_id") == "sporttery-2039299__vunknown__20260802T150949Z__t-minus-24h":
        rec = json.loads(Path(e["path"]).read_text(encoding="utf-8"))
        inp = rec.get("input") or {}
        out = rec.get("output") or {}
        core = out.get("core_output") or {}
        print("input.odds:", inp.get("odds"))
        print("input.hhad:", inp.get("hhad"))
        print("input.ttg:", inp.get("ttg"))
        print("input keys:", sorted(inp.keys()))
        print("core.market_prob_pct:", core.get("market_prob_pct"))
        print("core.model_1x2_pct:", core.get("model_1x2_pct"))
        print("core.final_1x2_pct:", core.get("final_1x2_pct"))
        print("core.devig_method:", core.get("devig_method"))
        print("core.devig_available_methods:", core.get("devig_available_methods"))
        print("core.bookmaker_margin_pct:", core.get("bookmaker_margin_pct"))
        print("core.status:", core.get("status"))
        print("core.reliability_flags:", core.get("reliability_flags"))
        print("core.goal_total_input:", core.get("goal_total_input"))
        print("core.implied_goal_total:", core.get("implied_goal_total"))
        break

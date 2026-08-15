#!/usr/bin/env python3
"""看 9fe6e8e8a988 时代记录的 input 结构与 core_output 的 final_1x2，判断重放可行性。"""
import json
from pathlib import Path

STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")

n = 0
for line in open(STORE / "registry.jsonl", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    e = json.loads(line)
    p = Path(e["path"])
    if not p.exists():
        continue
    rec = json.loads(p.read_text(encoding="utf-8"))
    m = rec.get("model") or {}
    if not m.get("engine_sha256", "").startswith("9fe6e8e8a988"):
        continue
    inp = rec.get("input") or {}
    out = rec.get("output") or {}
    core = out.get("core_output") or {}
    print("=== 记录:", rec.get("prediction_id"), "===")
    print("input keys:", sorted(inp.keys()))
    print("core_output keys:", sorted(core.keys()))
    # 概率输出
    for k in ("final_1x2_pct", "final_1x2", "market_prob_pct", "uncalibrated_pct"):
        if k in core:
            print(f"core.{k} =", core[k])
    # 输入里的赔率/总进球（重放必需）
    for k in ("odds", "hhad", "ttg", "total", "mode", "home", "away", "competition", "kickoff"):
        if k in inp:
            v = inp[k]
            print(f"input.{k} =", json.dumps(v, ensure_ascii=False)[:200])
    n += 1
    if n >= 2:
        break

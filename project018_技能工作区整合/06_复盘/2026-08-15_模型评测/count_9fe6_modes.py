#!/usr/bin/env python3
"""统计 9fe6e8e8a988 时代 1466 场的 mode 分布（判断概率输出是否主要由市场去水决定）。"""
import json
from collections import Counter
from pathlib import Path

STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")

mode_cnt = Counter()
route_cnt = Counter()
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
    mode_cnt[rec.get("mode") or "?"] += 1
    route_cnt[rec.get("route") or "?"] += 1
    n += 1

print("9fe6e8e8a988 时代总记录数:", n)
print("\nmode 分布:")
for k, v in mode_cnt.most_common():
    print(f"  {k}: {v}")
print("\nroute 分布:")
for k, v in route_cnt.most_common():
    print(f"  {k}: {v}")

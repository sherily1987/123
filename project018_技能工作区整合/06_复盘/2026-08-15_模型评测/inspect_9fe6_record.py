#!/usr/bin/env python3
"""从一条 9fe6e8e8a988 时代登记记录里提取当时的引擎版本与校准常量快照。"""
import json
from pathlib import Path

STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")

# 找一条 engine_sha256=9fe6e8e8a988 的记录
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
    if m.get("engine_sha256", "").startswith("9fe6e8e8a988"):
        print("prediction_id:", rec.get("prediction_id"))
        print("created_at:", rec.get("created_at"))
        print("model.version:", m.get("version"))
        print("model.core_version:", m.get("core_version"))
        print("model.fusion_version:", m.get("fusion_version"))
        out = rec.get("output") or {}
        core = out.get("core_output") or {}
        print("core_output.engine_version:", core.get("engine_version"))
        # 校准常量 / 去水方法若在输出里
        for key in ("calibration", "core_calibration", "devig", "market_fit"):
            v = core.get(key) or out.get(key)
            if v:
                print(f"--- {key} ---")
                print(json.dumps(v, ensure_ascii=False)[:800])
        print("output keys:", sorted(out.keys())[:40])
        break

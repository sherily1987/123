#!/usr/bin/env python3
"""重放测试：用当前 predict.py 重跑 9fe6e8e8a988 时代记录的 input，对比 final_1x2 概率输出。

判定：
  一致      -> 当前代码能复现当时概率，概率等价
  不一致    -> 概率数值输出变了，不等价
  status!=ok-> 当前引擎因新增逻辑（如 market_freshness）拒绝/改变输出，不等价
"""
import importlib.util
import json
import sys
from pathlib import Path

CORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
sys.path.insert(0, str(CORE))

spec = importlib.util.spec_from_file_location("predict_replay", CORE / "predict.py")
predict_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(predict_mod)


def close(a, b, tol=1e-4):
    return all(abs(x - y) < tol for x, y in zip(a, b))


records = []
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
        records.append(rec)

print(f"9fe6e8e8a988 时代记录总数: {len(records)}")
import random
random.seed(20260815)
sample = random.sample(records, min(30, len(records)))

same = 0
diff = 0
rejected = 0
error = 0
for rec in sample:
    inp = rec.get("input") or {}
    old_final = ((rec.get("output") or {}).get("core_output") or {}).get("final_1x2_pct")
    old_mode = inp.get("mode")
    if not isinstance(old_final, list) or len(old_final) != 3:
        continue
    try:
        res = predict_mod.predict(inp)
    except Exception as exc:
        error += 1
        print(f"[error] {rec['prediction_id']}: {type(exc).__name__} {str(exc)[:80]}")
        continue
    st = res.get("status")
    new_final = res.get("final_1x2_pct")
    if st not in ("ok", None) or not isinstance(new_final, list) or len(new_final) != 3:
        rejected += 1
        if rejected <= 5:
            print(f"[rejected] {rec['prediction_id']} mode={old_mode} status={st} "
                  f"old_final={old_final} new_final={new_final}")
        continue
    if close([x / 100 for x in old_final], [x / 100 for x in new_final]):
        same += 1
    else:
        diff += 1
        if diff <= 5:
            print(f"[diff] {rec['prediction_id']} mode={old_mode} "
                  f"old={old_final} new={new_final}")

print(f"\n=== 重放结果（抽样 {len(sample)}） ===")
print(f"概率一致: {same}")
print(f"概率不一致: {diff}")
print(f"当前引擎拒绝/状态非ok: {rejected}")
print(f"异常: {error}")

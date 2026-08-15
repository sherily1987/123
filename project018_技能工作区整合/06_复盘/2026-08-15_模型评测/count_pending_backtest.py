#!/usr/bin/env python3
"""统计回测库「待回测」样本：已登记预测、比赛已结束、但赛果未回填的场次。"""
import json
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
RESULTS = STORE / "results"
NOW = datetime.now(timezone.utc)

# results 文件集合（去 .json 后缀）
results_ids = {p.stem for p in RESULTS.glob("*.json")}

# registry 遍历
entries = []
for line in open(STORE / "registry.jsonl", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    entries.append(json.loads(line))

total_records = len(entries)
match_ids = {e["match_id"] for e in entries}

# 每个 match_id 的 kickoff（取任一 prediction 文件里的）
kickoff_by_match = {}
for e in entries:
    mid = e["match_id"]
    if mid in kickoff_by_match:
        continue
    p = Path(e["path"])
    if not p.exists():
        continue
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        continue
    m = rec.get("match") or {}
    ko = m.get("kickoff") or (rec.get("input") or {}).get("kickoff")
    if ko:
        kickoff_by_match[mid] = ko

def _dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

settled = match_ids & results_ids
missing = match_ids - results_ids

# 缺赛果的场次里，kickoff 已过（真正的待回测积压）vs 未来
missing_past = []
missing_future = []
missing_nokickoff = []
for mid in missing:
    ko = kickoff_by_match.get(mid)
    dt = _dt(ko) if ko else None
    if dt is None:
        missing_nokickoff.append(mid)
    elif dt <= NOW:
        missing_past.append(mid)
    else:
        missing_future.append(mid)

print("=== 回测库样本状态 ===")
print(f"registry 记录总数（含多快照）: {total_records}")
print(f"去重 match_id 数: {len(match_ids)}")
print(f"results 赛果文件数: {len(results_ids)}")
print(f"已有赛果（settled）: {len(settled)}")
print(f"缺赛果（missing results）: {len(missing)}")
print(f"  其中 kickoff 已过（待回测积压）: {len(missing_past)}")
print(f"  其中 kickoff 未来（尚未开赛）: {len(missing_future)}")
print(f"  其中 无 kickoff 信息: {len(missing_nokickoff)}")

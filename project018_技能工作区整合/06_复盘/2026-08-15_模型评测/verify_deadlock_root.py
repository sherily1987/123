#!/usr/bin/env python3
"""验证「死锁根因」假设：核心引擎(predict.py)哈希 vs legacy 样本的 engine_sha256 是否一致。

若一致 → 说明概率计算核心自 legacy 批以来未变，只是 fusion 框架层/配置在变，
按「概率签名」分组即可把 legacy 归入 current，突破 current=0 死锁。
"""
import hashlib
import json
from pathlib import Path

STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
CORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
PREDICT = CORE / "predict.py"
MARKET_FIT = CORE / "market_fit.py"
ODDS = CORE / "odds_methods.py"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha_f(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


print("=== 当前核心引擎文件哈希 ===")
print(f"predict.py      {sha(PREDICT)[:12]}...")
print(f"market_fit.py   {sha(MARKET_FIT)[:12]}...")
print(f"odds_methods.py {sha(ODDS)[:12]}...")

print("\n=== legacy 样本的 model.engine_sha256 分布（predict.py 哈希） ===")
from collections import Counter
cnt = Counter()
config_cnt = Counter()
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
    es = m.get("engine_sha256")
    cs = m.get("config_sha256")
    if es:
        cnt[es[:12]] += 1
    if cs:
        config_cnt[cs[:12]] += 1

print("engine_sha256(predict.py) 分布:")
for k, v in cnt.most_common():
    cur = "  <== 与当前一致" if k == sha(PREDICT)[:12] else ""
    print(f"  {k}...  {v} 场{cur}")

print("\nconfig_sha256 分布:")
for k, v in config_cnt.most_common():
    print(f"  {k}...  {v} 场")

# 当前 config_sha256（从 build_identity 逻辑推导：version_manifest + market_weights + recommendation_policy）
def _hash_files(paths):
    digest = hashlib.sha256()
    for p in sorted((Path(x) for x in paths), key=lambda x: str(x).lower()):
        digest.update(str(p.name).encode("utf-8"))
        digest.update(b"\0")
        digest.update(p.read_bytes() if p.exists() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()

CFG = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\skill\football-quant-fusion\config")
cur_config = _hash_files([CFG / "version_manifest.json", CFG / "market_weights.json", CFG / "recommendation_policy.json"])
print(f"\n当前 config_sha256 = {cur_config[:12]}...")
print(f"legacy 里有多少场 config_sha256 与当前一致: {config_cnt.get(cur_config[:12], 0)}")

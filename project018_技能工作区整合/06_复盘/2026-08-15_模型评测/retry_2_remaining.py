#!/usr/bin/env python3
"""重试剩余 2 场：艾卜哈(2040832)直查重试 + 汉堡(2036932)按日期查历史赛果列表。"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
from settle_from_sporttery import fetch_fixed_by_id

# 1. 重试艾卜哈直查（3 次，间隔递增）
print("=== 重试艾卜哈 2040832 直查 ===")
for i in range(3):
    row = fetch_fixed_by_id("2040832")
    if row.get("finished"):
        print(f"  第{i+1}次命中: score_90={row['score_90']}")
        break
    print(f"  第{i+1}次 not_finished (status={row.get('status_name')})")
    time.sleep(1.0)

# 2. 汉堡场按日期查赛果列表（fetch_sporttery_full.py --results）
print("\n=== 汉堡场 2036932 按日期查赛果列表 ===")
CORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
import subprocess
out = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\06_复盘\2026-08-15_模型评测\_tmp_results_20260114.json")
r = subprocess.run([sys.executable, str(CORE / "fetch_sporttery_full.py"),
                    "--results", "--date", "2026-01-14", "--output", str(out)],
                   capture_output=True, text=True)
print("fetch exit:", r.returncode)
if out.exists():
    data = json.loads(out.read_text(encoding="utf-8"))
    results = data.get("results", [])
    print(f"01-14 赛果列表 {len(results)} 场")
    for x in results:
        if str(x.get("match_id")) == "2036932" or "汉堡" in str(x) or "勒沃库森" in str(x):
            print("  命中:", json.dumps(x, ensure_ascii=False)[:400])
    # 打印列表里所有场次（看有没有汉堡）
    for x in results[:15]:
        print("  ", x.get("match_id"), x.get("home"), "vs", x.get("away"), "->", x.get("score_90"))

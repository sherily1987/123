#!/usr/bin/env python3
"""提取回测报告关键字段，输出紧凑摘要。"""
import json
import sys

p = r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest\backtest_20260815_internal_store.json"
d = json.load(open(p, encoding="utf-8"))

print("=== 顶层 ===")
for k in ("schema_version", "generated_at", "store", "evaluation_unit", "snapshot_policy",
          "record_sample_size", "sample_size", "unique_match_n", "deduped_duplicates"):
    print(f"{k}: {d.get(k)}")

print("\n=== calibration_gate ===")
print(json.dumps(d.get("calibration_gate"), ensure_ascii=False))

print("\n=== by_version_cohort ===")
for k, v in d.get("by_version_cohort", {}).items():
    print(f"{k}: n={v.get('n')} acc={v.get('accuracy_pct')} brier={v.get('brier_mean')} "
          f"logloss={v.get('log_loss')} ece={v.get('ece')}")

print("\n=== by_engine_build ===")
for k, v in sorted(d.get("by_engine_build", {}).items(), key=lambda x: -(x[1].get('n') or 0)):
    print(f"{k}: n={v.get('n')} acc={v.get('accuracy_pct')} brier={v.get('brier_mean')} ece={v.get('ece')}")

print("\n=== paired_market (overall) ===")
pm = d.get("paired_market", {})
print(json.dumps(pm, ensure_ascii=False))

print("\n=== walk_forward 汇总 ===")
wf = d.get("walk_forward", {})
print(f"status={wf.get('status')} fold_count={wf.get('fold_count')} combined_test_n={wf.get('combined_test_n')}")
cm = wf.get("combined_test_metrics", {})
if cm:
    print(f"combined: n={cm.get('n')} acc={cm.get('accuracy_pct')} brier={cm.get('brier_mean')} "
          f"logloss={cm.get('log_loss')} ece={cm.get('ece')}")
    print(f"  score top1={cm.get('score',{}).get('top1_accuracy_pct')} top3={cm.get('score',{}).get('top3_accuracy_pct')} "
          f"top5={cm.get('score',{}).get('top5_accuracy_pct')} score_ll={cm.get('score',{}).get('score_log_loss')}")
cp = wf.get("combined_paired_market", {})
if cp:
    print(f"combined paired_market: brier_delta={cp.get('brier_delta_model_minus_market')} 95ci={cp.get('brier_delta_95ci')}")

print("\n=== current_identity ===")
print(json.dumps(d.get("current_identity"), ensure_ascii=False, indent=2))

print("\n=== warning / disclaimer ===")
print(f"warning={d.get('warning')}")
print(f"disclaimer={d.get('disclaimer')}")

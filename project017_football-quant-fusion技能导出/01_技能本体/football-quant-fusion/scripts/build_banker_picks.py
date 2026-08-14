# -*- coding: utf-8 -*-
"""出胆汇总脚本（2026-08-12 用户裁定：主方向概率>=50%即出胆）。

消费 fusion_predict 输出的 recommendation_gate.banker_allowed，
把允许出胆的场次按 confidence 降序汇总为胆单，写入交付目录。

用法：
  python build_banker_picks.py --input <fusion输出.json> --output <胆单.md> [--json <胆单.json>]

读：
  results[].recommendation_gate.{banker_allowed, confidence_pct, reasons}
  results[].forecast.{final_1x2_display, top_scores, ou_2_5}
  results[].fusion_decision.{status}
写：
  --output 胆单 Markdown（含每场概率/比分/风险标注）
  --json   可选结构化胆单
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LABELS = ("主胜", "平局", "客胜")


def extract(row: dict) -> dict:
    gate = row.get("recommendation_gate") or {}
    fc = row.get("forecast") or {}
    fd = row.get("fusion_decision") or {}
    core = row.get("core_output") or {}
    probs = fc.get("final_1x2_pct") or core.get("final_1x2_pct") or []
    if len(probs) != 3:
        probs = []
    primary = max(range(3), key=lambda j: probs[j]) if len(probs) == 3 else None
    top_scores = fc.get("top_scores") or core.get("top_scores") or []
    ou = fc.get("ou_2_5") or core.get("ou_2_5") or {}
    return {
        "match": row.get("match") or "",
        "match_id": (row.get("input") or {}).get("sporttery_meta", {}).get("match_id"),
        "match_num": (row.get("input") or {}).get("sporttery_meta", {}).get("match_num"),
        "league": (row.get("input") or {}).get("competition") or "",
        "kickoff": (row.get("input") or {}).get("kickoff")
        or ((row.get("match") or {}).get("kickoff") if isinstance(row.get("match"), dict) else None),
        "banker_allowed": bool(gate.get("banker_allowed")),
        "confidence_pct": gate.get("confidence_pct"),
        "gate_reasons": gate.get("reasons") or [],
        "primary_label": LABELS[primary] if primary is not None else None,
        "primary_prob": probs[primary] if primary is not None else None,
        "probs_display": fc.get("final_1x2_display") or {},
        "top_scores": [(s.get("score"), s.get("prob_pct")) for s in (top_scores or [])[:3]],
        "ou25_over_pct": ou.get("over_pct"),
        "fusion_status": fd.get("status") or core.get("status"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="fusion_predict 输出 JSON（含 results[]）")
    ap.add_argument("--output", required=True, help="胆单 Markdown 输出路径")
    ap.add_argument("--json", default=None, help="可选结构化胆单 JSON 输出路径")
    a = ap.parse_args()

    data = json.loads(Path(a.input).read_text(encoding="utf-8"))
    results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(results, list):
        raise SystemExit("输入不是 fusion 输出（缺少 results 列表）")

    rows = [extract(r) for r in results]
    picks = [r for r in rows if r["banker_allowed"]]
    picks.sort(key=lambda r: -(r["confidence_pct"] or 0))

    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# 胆单（banker picks）",
        "",
        f"> 规则：用户裁定 2026-08-12 —— 主方向概率 ≥50% 即出胆（`banker_prob_threshold=0.50`）。",
        f"> 生成时间：{now} ｜ 来源：{Path(a.input).name}",
        "",
        f"## 汇总",
        "",
        f"- 总场次：{len(rows)} ｜ **出胆：{len(picks)} 场**",
        "",
    ]
    if not picks:
        lines.append("本次无场次达到出胆条件（全部 <50% 或状态被阻断）。")
    for i, p in enumerate(picks, 1):
        flags = []
        if p["fusion_status"] == "AVOID_DATA_RISK":
            flags.append("⚠️ 数据风险(AVOID_DATA_RISK)")
        if any("ONE_GOAL" in r for r in p["gate_reasons"]):
            flags.append("⚠️ 让球险")
        flag_txt = (" ｜ " + " ｜ ".join(flags)) if flags else ""
        prob_txt = " / ".join(f"{k} {v}" for k, v in (p["probs_display"] or {}).items()) or "—"
        lines += [
            f"### 胆{i}：{p['match']} → **{p['primary_label']}**（{p['primary_prob']:.1f}%）{flag_txt}",
            "",
            f"- 概率：{prob_txt}",
            f"- 比分偏好：{'、'.join(f'{s} ({pct}%)' for s, pct in p['top_scores']) or '—'}",
            f"- 大2.5：{'—' if p['ou25_over_pct'] is None else str(round(p['ou25_over_pct'], 1)) + '%'}",
            f"- confidence：{p['confidence_pct']}",
            f"- 门禁备注：{'；'.join(p['gate_reasons']) or '无'}",
            "",
        ]
    if not picks:
        lines.append("")
    lines.append("## 未出胆场次")
    lines.append("")
    for r in rows:
        if not r["banker_allowed"]:
            why = "；".join(r["gate_reasons"]) or "banker=False"
            lines.append(f"- {r['match']}：{why}")
    lines.append("")

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"胆单已写入：{out}（出胆 {len(picks)}/{len(rows)} 场）")

    if a.json:
        jp = Path(a.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps({
            "schema": "banker-picks-1.0",
            "generated_at": now,
            "rule": "用户裁定 2026-08-12: 主方向概率>=50%即出胆",
            "threshold": 0.50,
            "total": len(rows),
            "picks": picks,
            "not_picked": [r for r in rows if not r["banker_allowed"]],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"结构化胆单已写入：{jp}")

    for p in picks:
        print(f"  胆：{p['match']} → {p['primary_label']} {p['primary_prob']:.1f}%")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""43 场低市场依赖的强度审计。不改概率文件，不 bump 版本。

问的是：独立信息通路输给市场，是 λ/强度本身错，还是融合加权过冲？
再附塞维利亚这种 market_only 下 model_1x2 已偏离的影子样本。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\skill\football-quant-fusion\scripts")
sys.path.insert(0, str(SCRIPTS))

from fusion_backtest import (  # noqa: E402
    dedupe_snapshot_rows,
    load_jsonl,
    resolve_path,
    score_record,
    select_primary_rows,
)
from runtime_paths import backtest_store  # noqa: E402

LABELS = ("H", "D", "A")
SEVILLA_OUTPUT = Path(
    r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练"
    r"\05_交付\每日开售预测\2026-08-16\双轨实测_塞维利亚vs巴列卡诺\04_量化轨输出.json"
)
SEVILLA_INPUT = Path(
    r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练"
    r"\05_交付\每日开售预测\2026-08-16\双轨实测_塞维利亚vs巴列卡诺\03_单场模型输入.json"
)


def brier(probs, idx):
    return sum((p - (1.0 if i == idx else 0.0)) ** 2 for i, p in enumerate(probs))


def as_unit(pct):
    if not isinstance(pct, (list, tuple)) or len(pct) != 3:
        return None
    vals = [float(x) for x in pct]
    if max(vals) > 1.5:
        vals = [x / 100.0 for x in vals]
    return vals


def argmax(probs):
    if not probs:
        return None
    return LABELS[max(range(3), key=lambda i: probs[i])]


def find_pct(out, *names):
    core = out.get("core_output") or {}
    fc = out.get("forecast") or core.get("forecast") or {}
    for blob in (fc, out, core):
        for name in names:
            val = blob.get(name)
            unit = as_unit(val)
            if unit:
                return unit
    return None


def extract_strength(rec):
    inp = rec.get("input") or {}
    out = rec.get("output") or {}
    core = out.get("core_output") or {}
    fc = out.get("forecast") or core.get("forecast") or {}
    gr = fc.get("goal_rate") or core.get("goal_rate") or {}
    audit = (core.get("lambda_audit") or fc.get("lambda_audit") or {})
    api = (out.get("data_usage_audit") or {}).get("api_features") or out.get("api_features") or {}
    prior = inp.get("lambda_prior") or inp.get("lambda_home")
    tags = list(gr.get("source_tags") or core.get("xg_tags") or [])
    return {
        "input_mode": inp.get("mode"),
        "output_mode": rec.get("mode") or out.get("mode"),
        "lambda_home": audit.get("lambda_home") if audit.get("lambda_home") is not None else gr.get("home"),
        "lambda_away": audit.get("lambda_away") if audit.get("lambda_away") is not None else gr.get("away"),
        "lambda_ratio": audit.get("lambda_ratio_high_low"),
        "goal_rate_kind": gr.get("kind"),
        "source_tags": tags,
        "no_anchor_fallback": "NO_ANCHOR_FALLBACK" in tags,
        "has_lambda_prior": isinstance(inp.get("lambda_prior"), dict) or (
            inp.get("lambda_home") not in (None, 0) and inp.get("lambda_away") not in (None, 0)
        ),
        "has_elo": inp.get("elo_home") not in (None, 0) and inp.get("elo_away") not in (None, 0),
        "real_event_xg": gr.get("real_event_xg"),
        "api_history_matches": api.get("history_matches"),
        "api_status": api.get("status"),
        "odds": inp.get("odds"),
    }


def verdict(model, market, final, actual_idx):
    if model is None or market is None or actual_idx is None:
        return "unscored"
    bm, bk, bf = brier(model, actual_idx), brier(market, actual_idx), brier(final, actual_idx)
    if bm > bk + 1e-9 and bf > bk + 1e-9:
        return "strength_worse"
    if bm <= bk + 1e-9 and bf > bk + 1e-9:
        return "fusion_overshoot"
    if bm > bk + 1e-9 and bf <= bk + 1e-9:
        return "fusion_rescued"
    return "signal_helped"


def load_scored(root: Path):
    scored = []
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        row, _ = score_record(rec, root)
        if row is None or not row.get("market_probs") or row.get("actual_idx") is None:
            continue
        row["market_dependency_pct"] = (rec.get("output") or {}).get("market_dependency_pct")
        if row["market_dependency_pct"] is None:
            row["market_dependency_pct"] = rec.get("output", {}).get("recommendation_gate", {}).get(
                "market_dependency_pct"
            )
        row["_rec"] = rec
        scored.append(row)
    rows, _ = dedupe_snapshot_rows(scored)
    return select_primary_rows(rows, "latest_before_kickoff")


def row_from_record(rec, scored=None):
    out = rec.get("output") or {}
    match = rec.get("match") or {}
    strength = extract_strength(rec)
    final = find_pct(out, "final_1x2_pct", "final_1x2")
    market = find_pct(out, "market_prob_pct")
    if market is None and scored:
        market = scored.get("market_probs")
    model = find_pct(out, "model_1x2_pct", "model_1x2")
    actual_idx = scored.get("actual_idx") if scored else None
    dep = out.get("market_dependency_pct")
    if dep is None:
        dep = (out.get("recommendation_gate") or {}).get("market_dependency_pct")
    away_shift = None
    if model and market:
        away_shift = round((model[2] - market[2]) * 100, 1)
    item = {
        "match_id": rec.get("match_id"),
        "home": match.get("home") or (rec.get("input") or {}).get("home"),
        "away": match.get("away") or (rec.get("input") or {}).get("away"),
        "league": match.get("competition") or match.get("stage"),
        "kickoff": match.get("kickoff"),
        "snapshot": rec.get("snapshot_type"),
        "dep_pct": dep,
        "odds": strength["odds"],
        "input_mode": strength["input_mode"],
        "output_mode": strength["output_mode"],
        "lambda_home": strength["lambda_home"],
        "lambda_away": strength["lambda_away"],
        "lambda_equal": (
            strength["lambda_home"] is not None
            and strength["lambda_away"] is not None
            and abs(float(strength["lambda_home"]) - float(strength["lambda_away"])) < 1e-6
        ),
        "goal_rate_kind": strength["goal_rate_kind"],
        "source_tags": strength["source_tags"],
        "no_anchor_fallback": strength["no_anchor_fallback"],
        "has_lambda_prior": strength["has_lambda_prior"],
        "has_elo": strength["has_elo"],
        "real_event_xg": strength["real_event_xg"],
        "api_history_matches": strength["api_history_matches"],
        "market_1x2": [round(x * 100, 1) for x in market] if market else None,
        "model_1x2": [round(x * 100, 1) for x in model] if model else None,
        "final_1x2": [round(x * 100, 1) for x in final] if final else None,
        "away_shift_pp": away_shift,
        "market_pick": argmax(market),
        "model_pick": argmax(model),
        "final_pick": argmax(final),
        "actual": LABELS[actual_idx] if actual_idx is not None else None,
        "actual_score": scored.get("actual_score") if scored else None,
        "brier_model": round(brier(model, actual_idx), 4) if model and actual_idx is not None else None,
        "brier_market": round(brier(market, actual_idx), 4) if market and actual_idx is not None else None,
        "brier_final": round(brier(final, actual_idx), 4) if final and actual_idx is not None else None,
        "verdict": verdict(model, market, final, actual_idx),
    }
    if item["brier_final"] is not None and item["brier_market"] is not None:
        item["delta_final_vs_market"] = round(item["brier_final"] - item["brier_market"], 4)
    if item["brier_model"] is not None and item["brier_market"] is not None:
        item["delta_model_vs_market"] = round(item["brier_model"] - item["brier_market"], 4)
    return item


def sevilla_shadow():
    if not SEVILLA_OUTPUT.exists():
        return None
    out = json.loads(SEVILLA_OUTPUT.read_text(encoding="utf-8"))
    inp = json.loads(SEVILLA_INPUT.read_text(encoding="utf-8")) if SEVILLA_INPUT.exists() else {}
    rec = {
        "match_id": out.get("match_id") or "sporttery-2040884",
        "snapshot_type": "prematch",
        "mode": out.get("mode"),
        "match": {
            "home": inp.get("home", "塞维利亚"),
            "away": inp.get("away", "巴列卡诺"),
            "competition": inp.get("competition", "西甲"),
            "kickoff": inp.get("kickoff"),
        },
        "input": inp,
        "output": out,
    }
    item = row_from_record(rec, None)
    item["note"] = "未结算。market_only 影子 model_1x2，不属于 43 场低依赖样本。"
    return item


def to_md(rows, shadow):
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    n_fallback = sum(1 for r in rows if r["no_anchor_fallback"] or r["lambda_equal"])
    n_prior = sum(1 for r in rows if r["has_lambda_prior"] or r["has_elo"])
    n_xg = sum(1 for r in rows if r["real_event_xg"])
    lines = [
        "# 低依赖 43 场强度审计",
        "",
        "口径与 `diagnose_model_vs_market.py` 相同：去重 + latest_before_kickoff + 同场有市场概率。",
        "不改概率文件。n=43，CI 跨 0，本表只分类机制，不下「该开 m3」的结论。",
        "",
        "## 裁决含义",
        "",
        "| 裁决 | 含义 |",
        "|---|---|",
        "| `strength_worse` | 纯模型和分析都比市场差：λ/强度本身就不准 |",
        "| `fusion_overshoot` | 纯模型不差，融合后的 final 变差：权重/依赖度拉得过低 |",
        "| `fusion_rescued` | 纯模型更差，但 final 被市场锚救回来 |",
        "| `signal_helped` | 纯模型和 final 都不差于市场 |",
        "",
        "## 汇总",
        "",
        f"- 低依赖已结算：**{len(rows)}** 场",
        f"- 裁决：{', '.join(f'{k} {v}' for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))}",
        f"- 无锚回退或 λ 主客相等：**{n_fallback}** 场（不是 Dixon-Coles 强度）",
        f"- 输入里真有 λ prior / Elo：**{n_prior}** 场",
        f"- 有事件 xG：**{n_xg}** 场",
        "",
        "## 逐场",
        "",
        "| 比赛 | 联赛 | 依赖% | λ主/客 | 标签 | 市场 | 纯模型 | final | 实际 | 裁决 | Δfinal |",
        "|---|---|---:|---|---|---|---|---|---|---|---:|",
    ]
    for r in rows:
        lam = "—"
        if r["lambda_home"] is not None:
            lam = f"{r['lambda_home']:.2f}/{r['lambda_away']:.2f}"
        tags = ",".join(r["source_tags"][:2]) or "—"
        lines.append(
            f"| {r['home']} vs {r['away']} | {r['league']} | {r['dep_pct']} | {lam} | {tags} "
            f"| {r['market_1x2']} | {r['model_1x2']} | {r['final_1x2']} "
            f"| {r['actual']} {r['actual_score']} | `{r['verdict']}` | {r.get('delta_final_vs_market')} |"
        )
    if shadow:
        lines += [
            "",
            "## 附录：塞维利亚 vs 巴列卡诺（未结算影子）",
            "",
            f"- 市场 {shadow['market_1x2']}，纯模型 {shadow['model_1x2']}，final {shadow['final_1x2']}",
            f"- 客胜偏移 {shadow['away_shift_pp']}pp；λ {shadow['lambda_home']}/{shadow['lambda_away']}；`{shadow['output_mode']}`",
            f"- {shadow.get('note')}",
            "",
        ]
    lines += [
        "## 读法",
        "",
        "1. 若 `strength_worse` 占多数：先修强度/禁止无锚 model_first，不要加融合权重。",
        "2. 若 `fusion_overshoot` 占多数：强度可用，收紧介入门槛、减小偏离幅度。",
        "3. `NO_ANCHOR_FALLBACK` 或 λ 主客相等：这场没有独立强度，依赖度不该被拉低。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main():
    root = backtest_store()
    scored = load_scored(root)
    low = [r for r in scored if r.get("market_dependency_pct") is not None
           and float(r["market_dependency_pct"]) < 80]
    rows = [row_from_record(r["_rec"], r) for r in low]
    rows.sort(key=lambda r: (r.get("delta_final_vs_market") is None, -(r.get("delta_final_vs_market") or 0)))
    shadow = sevilla_shadow()
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    report = {
        "schema": "strength-audit-43-1.0",
        "n_low_dep": len(rows),
        "verdict_counts": counts,
        "n_no_anchor_or_equal_lambda": sum(1 for r in rows if r["no_anchor_fallback"] or r["lambda_equal"]),
        "n_has_independent_anchor": sum(1 for r in rows if r["has_lambda_prior"] or r["has_elo"]),
        "n_real_xg": sum(1 for r in rows if r["real_event_xg"]),
        "matches": rows,
        "shadow_sevilla": shadow,
    }
    js = HERE / "审计_低依赖43场强度_20260816.json"
    md = HERE / "审计_低依赖43场强度_20260816.md"
    js.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md.write_text(to_md(rows, shadow), encoding="utf-8")
    print(f"n={len(rows)} verdicts={counts}")
    print(f"no_anchor_or_equal_lambda={report['n_no_anchor_or_equal_lambda']}")
    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

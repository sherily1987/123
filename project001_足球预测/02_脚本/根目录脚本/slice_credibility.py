#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 联赛 × 模式 × 出胆门控 切片量化共享库可信度。

数字全部由脚本从 registry.jsonl + predictions + results 产生。
去重规则对齐 fusion_backtest：(match_id, snapshot_type) 保留 created_at 最新。
另附「每场一票」（优先 closing）视图，避免同场多快照稀释。

用法:
  python slice_credibility.py
  python slice_credibility.py --store <backtest_dir> --out-dir <dir>
"""
from __future__ import annotations

import argparse
import io
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STORE = Path(
    r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/"
    r"shared/football-quant-fusion/backtest"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "06_复盘" / "credibility_slices"


def load_json(path: Path):
    return json.loads(io.open(path, encoding="utf-8-sig").read())


def find(d, *keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and cur.get(k) is not None:
            return cur[k]
        if isinstance(cur, dict):
            cur = cur.get(k) or {}
        else:
            return default
    return default


def actual_1x2(h, a):
    return 0 if h > a else (1 if h == a else 2)


def as_prob3(x):
    if not isinstance(x, (list, tuple)) or len(x) != 3:
        return None
    try:
        vals = [float(v) for v in x]
    except (TypeError, ValueError):
        return None
    if max(vals) > 1.5:  # percent
        vals = [v / 100.0 for v in vals]
    s = sum(vals)
    if s <= 0:
        return None
    if abs(s - 1.0) > 0.05:
        vals = [v / s for v in vals]
    return vals


def devig_odds(odds):
    try:
        o = [float(x) for x in odds]
        if len(o) != 3 or min(o) <= 1.01:
            return None
        q = [1.0 / x for x in o]
        s = sum(q)
        return [x / s for x in q]
    except Exception:
        return None


def flag_keys(flags):
    out = []
    for f in flags or []:
        s = str(f)
        out.append(s.split(":")[0].strip())
    return out


def snapshot_rank(st):
    s = (st or "").lower()
    order = {
        "closing": 100,
        "close": 100,
        "t-1h": 90,
        "t-2h": 85,
        "t-4h": 80,
        "t-6h": 75,
        "t-12h": 70,
        "t-24h": 60,
        "t-minus-24h": 60,
        "t-minus-6h": 75,
        "opening": 10,
        "open": 10,
        "prematch": 50,
    }
    return order.get(s, 40)


def primary_bin(pmax):
    edges = [0.0, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 1.01]
    labels = [
        "[0.00,0.40)",
        "[0.40,0.50)",
        "[0.50,0.55)",
        "[0.55,0.60)",
        "[0.60,0.65)",
        "[0.65,0.70)",
        "[0.70,0.80)",
        "[0.80,1.01)",
    ]
    for i in range(len(edges) - 1):
        if edges[i] <= pmax < edges[i + 1]:
            return labels[i]
    return labels[-1]


def trust_label(n, acc, mkt_acc, extreme_rate, dep_mean, banker_rate):
    """定性可信度标签（规则可审计，非 ML）。"""
    if n < 30:
        return "样本不足", "灰", "n<30，只看现象不看结论"
    notes = []
    # 相对市场
    edge_pp = (acc - mkt_acc) * 100 if mkt_acc is not None else None
    if edge_pp is not None:
        if edge_pp >= 3:
            notes.append(f"主方向优于市场{edge_pp:.1f}pp")
        elif edge_pp <= -3:
            notes.append(f"主方向劣于市场{abs(edge_pp):.1f}pp")
        else:
            notes.append("与市场持平(±3pp)")
    if dep_mean is not None and dep_mean >= 90:
        notes.append("高市场依赖(≈复述盘口)")
    if extreme_rate is not None and extreme_rate >= 0.08:
        notes.append(f"失真旗标率{extreme_rate*100:.1f}%")
    if banker_rate is not None and banker_rate < 0.01:
        notes.append("几乎不出胆")

    # 等级
    if n >= 200 and edge_pp is not None and edge_pp >= 2 and (extreme_rate or 0) < 0.05:
        grade, color = "可优先参考", "绿"
    elif n >= 100 and edge_pp is not None and edge_pp >= -1 and (extreme_rate or 0) < 0.10:
        grade, color = "可作基线", "蓝"
    elif n >= 50 and (extreme_rate or 0) >= 0.10:
        grade, color = "需降级解读", "橙"
    elif n >= 50 and edge_pp is not None and edge_pp < -3:
        grade, color = "弱于市场", "红"
    elif n >= 50:
        grade, color = "谨慎参考", "黄"
    else:
        grade, color = "观察中", "灰"
    return grade, color, "；".join(notes) if notes else "—"


def summarize_rows(rows):
    if not rows:
        return None
    n = len(rows)
    hits = sum(r["hit"] for r in rows)
    mkt_hits = [r["mkt_hit"] for r in rows if r["mkt_hit"] is not None]
    briers = [r["brier"] for r in rows]
    extremes = sum(r["extreme"] for r in rows)
    bankers = sum(1 for r in rows if r["banker"] is True)
    deps = [r["dep"] for r in rows if r["dep"] is not None]
    edges = [r["edge_pp"] for r in rows if r["edge_pp"] is not None]
    pmaxs = [r["pmax"] for r in rows]
    # primary direction calibration
    cal = defaultdict(lambda: {"n": 0, "hit": 0, "pmax_sum": 0.0})
    for r in rows:
        b = primary_bin(r["pmax"])
        cal[b]["n"] += 1
        cal[b]["hit"] += r["hit"]
        cal[b]["pmax_sum"] += r["pmax"]

    acc = hits / n
    mkt_acc = (sum(mkt_hits) / len(mkt_hits)) if mkt_hits else None
    grade, color, note = trust_label(
        n,
        acc,
        mkt_acc,
        extremes / n,
        (sum(deps) / len(deps)) if deps else None,
        bankers / n,
    )
    cal_rows = []
    for b in [
        "[0.00,0.40)",
        "[0.40,0.50)",
        "[0.50,0.55)",
        "[0.55,0.60)",
        "[0.60,0.65)",
        "[0.65,0.70)",
        "[0.70,0.80)",
        "[0.80,1.01)",
    ]:
        c = cal.get(b)
        if not c:
            continue
        avg_p = c["pmax_sum"] / c["n"]
        rate = c["hit"] / c["n"]
        cal_rows.append(
            {
                "bin": b,
                "n": c["n"],
                "avg_pmax": round(avg_p, 4),
                "hit_rate": round(rate, 4),
                "gap_pp": round((avg_p - rate) * 100, 2),
            }
        )
    return {
        "n": n,
        "hit": hits,
        "accuracy_pct": round(acc * 100, 2),
        "market_n": len(mkt_hits),
        "market_accuracy_pct": round(sum(mkt_hits) / len(mkt_hits) * 100, 2) if mkt_hits else None,
        "vs_market_pp": round((acc - (sum(mkt_hits) / len(mkt_hits))) * 100, 2) if mkt_hits else None,
        "brier_mean": round(sum(briers) / n, 6),
        "extreme_n": extremes,
        "extreme_rate_pct": round(extremes / n * 100, 2),
        "banker_n": bankers,
        "banker_rate_pct": round(bankers / n * 100, 2),
        "dep_mean": round(sum(deps) / len(deps), 2) if deps else None,
        "edge_pp_mean": round(sum(edges) / len(edges), 3) if edges else None,
        "edge_pp_max": round(max(edges), 3) if edges else None,
        "pmax_mean": round(sum(pmaxs) / n, 4),
        "trust_grade": grade,
        "trust_color": color,
        "trust_note": note,
        "primary_calibration": cal_rows,
    }


def extract_row(pred, result):
    out = pred.get("output") or {}
    core = out.get("core_output") or out
    fc = out.get("forecast") or core.get("forecast") or {}
    inp = pred.get("input") or {}

    probs = as_prob3(
        find(out, "final_1x2_pct")
        or find(fc, "final_1x2_pct")
        or find(core, "final_1x2_pct")
        or find(out, "final_1x2")
        or find(core, "final_1x2")
    )
    if not probs:
        return None, "missing_1x2"

    s90 = result.get("score_90")
    if not isinstance(s90, dict) or s90.get("home") is None:
        return None, "no_score"
    h, a = int(s90["home"]), int(s90["away"])
    idx = actual_1x2(h, a)
    pred_idx = max(range(3), key=lambda i: probs[i])
    hit = int(pred_idx == idx)

    mkt = as_prob3(
        find(fc, "market_prob_pct")
        or find(out, "market_prob_pct")
        or find(core, "market_prob_pct")
    )
    if mkt is None:
        mkt = devig_odds(inp.get("odds"))
    mkt_hit = None
    if mkt is not None:
        mkt_idx = max(range(3), key=lambda i: mkt[i])
        mkt_hit = int(mkt_idx == idx)

    dep = find(out, "market_dependency_pct")
    if dep is None:
        dep = find(fc, "market_dependency_pct")
    try:
        dep = float(dep) if dep is not None else None
    except Exception:
        dep = None

    edge = find(out, "edge_vs_market_pp") or find(fc, "edge_vs_market_pp")
    edge_pp = None
    if isinstance(edge, (list, tuple)) and len(edge) == 3:
        try:
            edge_pp = float(edge[pred_idx])
        except Exception:
            edge_pp = None
    elif isinstance(edge, (int, float)):
        edge_pp = float(edge)

    rg = out.get("recommendation_gate") or fc.get("recommendation_gate") or {}
    banker = rg.get("banker_allowed")
    if banker is None and not rg:
        banker = None

    flags = flag_keys(
        fc.get("reliability_flags")
        or out.get("reliability_flags")
        or core.get("reliability_flags")
    )
    extreme = any(
        k.startswith("EXTREME_")
        or k in {"HHAD_CONFLICT", "TTG_SCORE_CONFLICT", "CRS_SCORE_LOW_OVERLAP"}
        for k in flags
    )

    in_mode = (inp.get("mode") or "").strip() or "?"
    out_mode = (out.get("mode") or fc.get("mode") or "").strip() or in_mode
    # 有效模式：输出侧为准（反映引擎真实分支）
    eff_mode = out_mode or in_mode

    # 依赖桶
    if dep is None:
        dep_bucket = "dep_unknown"
    elif dep >= 90:
        dep_bucket = "dep>=90(复述盘口)"
    elif dep >= 50:
        dep_bucket = "dep50-90"
    else:
        dep_bucket = "dep<50(更独立)"

    if banker is True:
        banker_bucket = "出胆=True"
    elif banker is False:
        banker_bucket = "出胆=False"
    else:
        banker_bucket = "出胆=未知"

    league = (
        (pred.get("match") or {}).get("competition")
        or (pred.get("match") or {}).get("stage")
        or inp.get("competition")
        or "?"
    )
    version = ((pred.get("model") or {}).get("version")) or "unknown"
    pmax = max(probs)
    brier = sum((p - (1 if i == idx else 0)) ** 2 for i, p in enumerate(probs))

    return {
        "match_id": pred.get("match_id"),
        "prediction_id": pred.get("prediction_id"),
        "snapshot_type": pred.get("snapshot_type"),
        "created_at": pred.get("created_at") or "",
        "league": league,
        "version": version,
        "in_mode": in_mode,
        "out_mode": out_mode,
        "eff_mode": eff_mode,
        "mode_mismatch": int(in_mode != out_mode and in_mode != "?" and out_mode != "?"),
        "dep": dep,
        "dep_bucket": dep_bucket,
        "banker": banker,
        "banker_bucket": banker_bucket,
        "probs": probs,
        "pmax": pmax,
        "pred_idx": pred_idx,
        "actual_idx": idx,
        "hit": hit,
        "mkt_hit": mkt_hit,
        "brier": brier,
        "edge_pp": edge_pp,
        "extreme": int(extreme),
        "flags": flags,
        "kickoff": (pred.get("match") or {}).get("kickoff"),
        "home": (pred.get("match") or {}).get("home"),
        "away": (pred.get("match") or {}).get("away"),
    }, None


def load_settled_rows(store: Path):
    reg = store / "registry.jsonl"
    entries = [
        json.loads(x)
        for x in io.open(reg, encoding="utf-8-sig").read().splitlines()
        if x.strip()
    ]
    # load all predictions pointed by registry
    preds = []
    missing_pred = 0
    for e in entries:
        p = Path(e.get("path") or "")
        if not p.exists():
            # fallback by filename under predictions
            name = p.name
            alt = store / "predictions" / "2026" / "08" / name
            if alt.exists():
                p = alt
            else:
                missing_pred += 1
                continue
        try:
            pred = load_json(p)
        except Exception:
            missing_pred += 1
            continue
        # attach path meta
        pred["_path"] = str(p)
        preds.append(pred)

    # dedupe (match_id, snapshot_type) keep latest created_at
    best = {}
    for pred in preds:
        key = (pred.get("match_id"), pred.get("snapshot_type"))
        prev = best.get(key)
        if prev is None or (pred.get("created_at") or "") > (prev.get("created_at") or ""):
            best[key] = pred
    deduped = list(best.values())

    rows = []
    skip = Counter()
    for pred in deduped:
        mid = pred.get("match_id")
        rp = store / "results" / f"{mid}.json"
        if not rp.exists():
            skip["no_result_file"] += 1
            continue
        try:
            result = load_json(rp)
        except Exception:
            skip["bad_result"] += 1
            continue
        row, err = extract_row(pred, result)
        if err:
            skip[err] += 1
            continue
        rows.append(row)

    # one-per-match view: prefer higher snapshot_rank then latest created_at
    by_match = {}
    for r in rows:
        mid = r["match_id"]
        prev = by_match.get(mid)
        if prev is None:
            by_match[mid] = r
            continue
        pr, cr = snapshot_rank(prev["snapshot_type"]), snapshot_rank(r["snapshot_type"])
        if cr > pr or (cr == pr and (r["created_at"] or "") > (prev["created_at"] or "")):
            by_match[mid] = r
    one_per_match = list(by_match.values())

    meta = {
        "registry_entries": len(entries),
        "predictions_loaded": len(preds),
        "missing_pred": missing_pred,
        "deduped_snapshots": len(deduped),
        "settled_snapshot_rows": len(rows),
        "settled_matches": len(one_per_match),
        "skip": dict(skip),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "store": str(store),
    }
    return rows, one_per_match, meta


def group_table(rows, key_fn, min_n=1):
    groups = defaultdict(list)
    for r in rows:
        groups[key_fn(r)].append(r)
    table = []
    for k, rs in groups.items():
        if len(rs) < min_n:
            continue
        s = summarize_rows(rs)
        s["key"] = k if not isinstance(k, tuple) else " | ".join(str(x) for x in k)
        s["key_parts"] = k if isinstance(k, tuple) else (k,)
        table.append(s)
    table.sort(key=lambda x: (-x["n"], x["key"]))
    return table


def md_escape(s):
    return str(s).replace("|", "\\|")


def fmt_pct(x):
    return "—" if x is None else f"{x:.2f}%"


def fmt_pp(x):
    if x is None:
        return "—"
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.2f}pp"


def render_md(meta, overall, tables: dict, cal_overall, mismatch_stats, action_rules):
    lines = []
    lines.append("# 量化引擎可信度切片表")
    lines.append("")
    lines.append(f"- 生成时间（UTC）：`{meta['generated_at']}`")
    lines.append(f"- 数据源：`{meta['store']}`")
    lines.append(
        f"- registry={meta['registry_entries']} | 去重快照={meta['deduped_snapshots']} | "
        f"已结算快照行={meta['settled_snapshot_rows']} | 已结算比赛(每场一票)={meta['settled_matches']}"
    )
    lines.append(f"- 跳过原因：`{json.dumps(meta['skip'], ensure_ascii=False)}`")
    lines.append("")
    lines.append("> 口径：主方向 = final_1x2 argmax；市场基线 = market_prob 或 HAD 去水 argmax；")
    lines.append("> 失真 = EXTREME_* / HHAD_CONFLICT / TTG_SCORE_CONFLICT / CRS_SCORE_LOW_OVERLAP；")
    lines.append("> 可信度标签为规则引擎（n/相对市场/失真率/依赖度），不是投注建议。")
    lines.append("")
    lines.append("## 0. 怎么用这张表")
    lines.append("")
    lines.append("| 颜色/等级 | 含义 | 用法 |")
    lines.append("|---|---|---|")
    lines.append("| 绿·可优先参考 | 样本够且不弱于市场、失真低 | 可作方向排序主参考 |")
    lines.append("| 蓝·可作基线 | 样本够、接近市场 | 当市场镜像/概率结构，不追 alpha |")
    lines.append("| 黄·谨慎参考 | 有样本但无优势 | 只看风险提示，不据此加注 |")
    lines.append("| 橙·需降级解读 | 失真旗标偏多 | 强制回退市场去水，忽略模型极端概率 |")
    lines.append("| 红·弱于市场 | 主方向明显差于市场 | 该切片模型输出降权 |")
    lines.append("| 灰·样本不足/观察中 | n 不够 | 不写进结论 |")
    lines.append("")
    lines.append("## 1. 全局（每场一票）")
    lines.append("")
    o = overall
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| n（比赛） | {o['n']} |")
    lines.append(f"| 模型主方向命中 | {o['hit']}/{o['n']}（{o['accuracy_pct']}%） |")
    lines.append(
        f"| 市场主方向命中 | {o['market_n']} 场有市场口径 → {fmt_pct(o['market_accuracy_pct'])} |"
    )
    lines.append(f"| 模型相对市场 | {fmt_pp(o['vs_market_pp'])} |")
    lines.append(f"| Brier | {o['brier_mean']} |")
    lines.append(f"| 失真率 | {o['extreme_rate_pct']}%（{o['extreme_n']}） |")
    lines.append(f"| 出胆率 | {o['banker_rate_pct']}%（{o['banker_n']}） |")
    lines.append(f"| 市场依赖度均值 | {o['dep_mean']} |")
    lines.append(f"| edge_pp 均值/最大 | {o['edge_pp_mean']} / {o['edge_pp_max']} |")
    lines.append(f"| 可信度 | **{o['trust_grade']}**（{o['trust_color']}）— {o['trust_note']} |")
    lines.append("")
    lines.append("### 1.1 主方向概率校准（每场一票，看 pmax 段）")
    lines.append("")
    lines.append("| 概率段 | n | 平均pmax | 实际命中 | 高估(+) / 低估(-) |")
    lines.append("|---|---:|---:|---:|---:|")
    for c in cal_overall:
        lines.append(
            f"| {c['bin']} | {c['n']} | {c['avg_pmax']*100:.1f}% | {c['hit_rate']*100:.1f}% | {c['gap_pp']:+.1f}pp |"
        )
    lines.append("")
    lines.append("### 1.2 输入 mode vs 输出 mode 漂移")
    lines.append("")
    lines.append(f"- 模式不一致场次：{mismatch_stats['mismatch_n']}/{mismatch_stats['n']}（{mismatch_stats['mismatch_rate_pct']}%）")
    lines.append(f"- 输入 mode 分布：`{mismatch_stats['in_mode']}`")
    lines.append(f"- 输出 mode 分布：`{mismatch_stats['out_mode']}`")
    lines.append("")
    lines.append("> 若 input=market_only 但 output=model_first 且伴随 EXTREME 旗标，应按失真降级，不信模型 90%+。")
    lines.append("")

    def emit_table(title, tbl, cols_extra=None):
        lines.append(f"## {title}")
        lines.append("")
        header = (
            "| 切片 | n | 模型命中 | 市场命中 | vs市场 | 失真率 | 出胆率 | 依赖度 | 等级 | 说明 |"
        )
        sep = "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"
        lines.append(header)
        lines.append(sep)
        for r in tbl:
            lines.append(
                "| {key} | {n} | {acc}% | {macc} | {vs} | {ex}% | {bk}% | {dep} | **{grade}** | {note} |".format(
                    key=md_escape(r["key"]),
                    n=r["n"],
                    acc=r["accuracy_pct"],
                    macc=fmt_pct(r["market_accuracy_pct"]),
                    vs=fmt_pp(r["vs_market_pp"]),
                    ex=r["extreme_rate_pct"],
                    bk=r["banker_rate_pct"],
                    dep="—" if r["dep_mean"] is None else r["dep_mean"],
                    grade=r["trust_grade"],
                    note=md_escape(r["trust_note"]),
                )
            )
        lines.append("")

    emit_table("2. 按联赛（每场一票）", tables["by_league"])
    emit_table("3. 按有效模式 eff_mode=output.mode（每场一票）", tables["by_eff_mode"])
    emit_table("4. 按输入模式 input.mode（每场一票）", tables["by_in_mode"])
    emit_table("5. 按出胆门控（每场一票）", tables["by_banker"])
    emit_table("6. 按市场依赖度桶（每场一票）", tables["by_dep"])
    emit_table(
        "7. 联赛 × 有效模式（n≥10）",
        [r for r in tables["league_x_mode"] if r["n"] >= 10],
    )
    emit_table(
        "8. 联赛 × 出胆（n≥10）",
        [r for r in tables["league_x_banker"] if r["n"] >= 10],
    )
    emit_table(
        "9. 有效模式 × 出胆（全部）",
        tables["mode_x_banker"],
    )
    emit_table(
        "10. 联赛 × 有效模式 × 出胆（n≥10）",
        [r for r in tables["league_x_mode_x_banker"] if r["n"] >= 10],
    )

    # 快照视图对比
    lines.append("## 11. 快照行视图 vs 每场一票（敏感度）")
    lines.append("")
    lines.append("| 视图 | n | 模型命中 | 市场命中 | vs市场 | 失真率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for name, s in tables["view_compare"]:
        lines.append(
            f"| {name} | {s['n']} | {s['accuracy_pct']}% | {fmt_pct(s['market_accuracy_pct'])} | {fmt_pp(s['vs_market_pp'])} | {s['extreme_rate_pct']}% |"
        )
    lines.append("")

    lines.append("## 12. 实操规则（由本表直接导出）")
    lines.append("")
    for i, rule in enumerate(action_rules, 1):
        lines.append(f"{i}. {rule}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**免责声明**：概率模型切片诊断，非投注建议。")
    lines.append("")
    return "\n".join(lines)


def build_action_rules(tables, overall, mismatch_stats):
    rules = []
    # league greens/reds
    good, bad, extreme_leagues = [], [], []
    for r in tables["by_league"]:
        if r["n"] < 50:
            continue
        if r["trust_color"] in {"绿", "蓝"}:
            good.append(f"{r['key']}({r['accuracy_pct']}%, n={r['n']})")
        if r["trust_color"] == "红" or (
            r["vs_market_pp"] is not None and r["vs_market_pp"] <= -3
        ):
            bad.append(f"{r['key']}({fmt_pp(r['vs_market_pp'])}, n={r['n']})")
        if r["extreme_rate_pct"] >= 10:
            extreme_leagues.append(f"{r['key']}(失真{r['extreme_rate_pct']}%)")
    if good:
        rules.append("优先参考联赛：" + "、".join(good))
    else:
        rules.append("大样本联赛中暂无稳定“绿档 alpha”，最多当市场基线用。")
    if bad:
        rules.append("降权/慎用联赛：" + "、".join(bad))
    if extreme_leagues:
        rules.append("失真偏高切片遇到 EXTREME/HHAD_CONFLICT 时强制市场去水：" + "、".join(extreme_leagues))

    # mode rules
    for r in tables["by_eff_mode"]:
        if r["n"] < 20:
            rules.append(
                f"有效模式 `{r['key']}` 仅 n={r['n']}，不单列结论（命中 {r['accuracy_pct']}%）。"
            )
            continue
        if r["extreme_rate_pct"] >= 10 or r["trust_color"] in {"橙", "红"}:
            rules.append(
                f"有效模式 `{r['key']}`：{r['trust_grade']}（命中{r['accuracy_pct']}% / 失真{r['extreme_rate_pct']}%）→ 不信极端概率。"
            )
        else:
            rules.append(
                f"有效模式 `{r['key']}`：{r['trust_grade']}（命中{r['accuracy_pct']}% / vs市场{fmt_pp(r['vs_market_pp'])}）。"
            )

    # banker
    banker_true = next((r for r in tables["by_banker"] if "True" in r["key"]), None)
    banker_false = next((r for r in tables["by_banker"] if "False" in r["key"]), None)
    if banker_true and banker_true["n"] >= 1:
        rules.append(
            f"历史 `出胆=True` 仅 {banker_true['n']} 场，命中 {banker_true['accuracy_pct']}%——"
            + ("样本不足，不能证明门控有效。" if banker_true["n"] < 30 else "可继续跟踪 ROI/CLV。")
        )
    else:
        rules.append("历史几乎无 `banker_allowed=True`：当前体系是风控过滤器，不是出胆引擎。")
    if banker_false:
        rules.append(
            f"`出胆=False` 主体 n={banker_false['n']}，命中 {banker_false['accuracy_pct']}%："
            "把输出当概率排序/风险提示，不把 argmax 当稳胆。"
        )

    if mismatch_stats["mismatch_rate_pct"] >= 1:
        rules.append(
            f"输入/输出 mode 漂移 {mismatch_stats['mismatch_rate_pct']}%："
            "报告必须同时打印 input.mode 与 output.mode；不一致时以 check_output 降级规则为准。"
        )

    if overall.get("vs_market_pp") is not None and overall["vs_market_pp"] <= 0:
        rules.append(
            f"全局 vs 市场 {fmt_pp(overall['vs_market_pp'])}：默认假设无 alpha，只有 edge≥门槛且非失真才允许升格。"
        )

    rules.append(
        "决策优先级：①失真旗标→市场去水 ②banker_allowed ③联赛切片等级 ④主方向概率段校准（0.60-0.70 高估区间降置信）。"
    )
    return rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    store = Path(args.store)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, one, meta = load_settled_rows(store)
    if not one:
        raise SystemExit(f"无已结算样本：{meta}")

    overall = summarize_rows(one)
    cal_overall = overall["primary_calibration"]

    mismatch_n = sum(r["mode_mismatch"] for r in one)
    mismatch_stats = {
        "n": len(one),
        "mismatch_n": mismatch_n,
        "mismatch_rate_pct": round(mismatch_n / len(one) * 100, 2),
        "in_mode": dict(Counter(r["in_mode"] for r in one)),
        "out_mode": dict(Counter(r["out_mode"] for r in one)),
    }

    tables = {
        "by_league": group_table(one, lambda r: r["league"]),
        "by_eff_mode": group_table(one, lambda r: r["eff_mode"]),
        "by_in_mode": group_table(one, lambda r: r["in_mode"]),
        "by_banker": group_table(one, lambda r: r["banker_bucket"]),
        "by_dep": group_table(one, lambda r: r["dep_bucket"]),
        "league_x_mode": group_table(one, lambda r: (r["league"], r["eff_mode"])),
        "league_x_banker": group_table(one, lambda r: (r["league"], r["banker_bucket"])),
        "mode_x_banker": group_table(one, lambda r: (r["eff_mode"], r["banker_bucket"])),
        "league_x_mode_x_banker": group_table(
            one, lambda r: (r["league"], r["eff_mode"], r["banker_bucket"])
        ),
        "view_compare": [
            ("每场一票(优先closing)", overall),
            ("全部已结算快照行", summarize_rows(rows)),
        ],
    }

    action_rules = build_action_rules(tables, overall, mismatch_stats)
    md = render_md(meta, overall, tables, cal_overall, mismatch_stats, action_rules)

    stamp = datetime.now().strftime("%Y%m%d")
    md_path = out_dir / f"credibility_slices_{stamp}.md"
    json_path = out_dir / f"credibility_slices_{stamp}.json"
    md_path.write_text(md, encoding="utf-8")

    payload = {
        "meta": meta,
        "overall_one_per_match": overall,
        "mismatch_stats": mismatch_stats,
        "tables": {
            k: v
            for k, v in tables.items()
            if k != "view_compare"
        },
        "view_compare": [
            {"name": n, "summary": s} for n, s in tables["view_compare"]
        ],
        "action_rules": action_rules,
        # compact row dump for audit (no huge matrices)
        "rows_one_per_match": [
            {
                "match_id": r["match_id"],
                "league": r["league"],
                "in_mode": r["in_mode"],
                "out_mode": r["out_mode"],
                "banker": r["banker"],
                "dep": r["dep"],
                "hit": r["hit"],
                "mkt_hit": r["mkt_hit"],
                "pmax": round(r["pmax"], 4),
                "extreme": r["extreme"],
                "snapshot_type": r["snapshot_type"],
                "home": r["home"],
                "away": r["away"],
            }
            for r in one
        ],
    }
    io.open(json_path, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )

    # console summary
    print("=== credibility slice done ===")
    print("store:", store)
    print("settled matches:", meta["settled_matches"], "snapshot rows:", meta["settled_snapshot_rows"])
    print(
        f"overall: model {overall['accuracy_pct']}% | market {overall['market_accuracy_pct']}% | "
        f"vs {overall['vs_market_pp']}pp | extreme {overall['extreme_rate_pct']}% | "
        f"banker {overall['banker_rate_pct']}% | grade {overall['trust_grade']}"
    )
    print("mode mismatch:", mismatch_stats)
    print("top leagues:")
    for r in tables["by_league"][:8]:
        print(
            f"  {r['key']}: n={r['n']} acc={r['accuracy_pct']}% mkt={r['market_accuracy_pct']} "
            f"vs={r['vs_market_pp']} ext={r['extreme_rate_pct']}% => {r['trust_grade']}"
        )
    print("by eff_mode:")
    for r in tables["by_eff_mode"]:
        print(
            f"  {r['key']}: n={r['n']} acc={r['accuracy_pct']}% ext={r['extreme_rate_pct']}% => {r['trust_grade']}"
        )
    print("by banker:")
    for r in tables["by_banker"]:
        print(f"  {r['key']}: n={r['n']} acc={r['accuracy_pct']}%")
    print("wrote:", md_path)
    print("wrote:", json_path)


if __name__ == "__main__":
    main()

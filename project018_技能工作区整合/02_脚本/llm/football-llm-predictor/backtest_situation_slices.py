# -*- coding: utf-8 -*-
"""
按态势切片回测 LLM/双轨方向命中。

切片:
  - action: single / dual / observe
  - lineup_gap: true/false
  - has_conflict: conflict_n >= 1
  - track_agree: 量化与LLM方向一致（若双轨都有）

口径: 竞彩 90 分钟 score_90；方向命中；dual 时 primary 或 alt 命中算 dual_hit。

用法:
  python backtest_situation_slices.py \\
    --situation data/situation_2026-08-08/situations.json \\
    --results data/results_2026-08-05.json \\
    --results data/results_2026-08-07.json \\
    --results data/results_2026-08-08.json \\
    --dual-json "F:/.../dual_track_with_situation.json" \\
    --out-dir data/situation_backtest
"""
from __future__ import annotations

import argparse
import io
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def load_json(p: Path):
    return json.loads(io.open(p, encoding="utf-8-sig").read())


def colon_to_dash(s):
    if s is None:
        return None
    s = str(s).strip().replace("：", ":").replace(":", "-")
    return s if re.fullmatch(r"\d+-\d+", s) else None


def result_1x2(score):
    h, a = map(int, score.split("-"))
    if h > a:
        return "主胜"
    if h < a:
        return "客胜"
    return "平局"


def norm(s):
    return re.sub(r"\s+", "", (s or "").strip().lower())


def k_ha(h, a):
    return f"{norm(h)}|{norm(a)}"


def load_results(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        if not p.exists():
            continue
        data = load_json(p)
        for r in data.get("results") or []:
            sc = colon_to_dash(r.get("score_90"))
            if not sc:
                continue
            r = dict(r)
            r["score_90"] = sc
            if r.get("score_ht"):
                r["score_ht"] = colon_to_dash(r["score_ht"]) or r["score_ht"]
            rows.append(r)
    return rows


def index_results(rows):
    by_num, by_ha = {}, {}
    for r in rows:
        if r.get("match_num"):
            by_num[r["match_num"]] = r
        by_ha[k_ha(r.get("home"), r.get("away"))] = r
    return by_num, by_ha


def pct(h, n):
    return round(100.0 * h / n, 1) if n else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--situation", required=True)
    ap.add_argument("--results", action="append", default=[], help="results_*.json, repeatable")
    ap.add_argument("--dual-json", default="", help="optional dual_track_with_situation.json")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    sit_batch = load_json(Path(args.situation))
    situations = sit_batch.get("situations") or []
    res_paths = [Path(p) for p in args.results]
    results = load_results(res_paths)
    by_num, by_ha = index_results(results)

    dual_by_num = {}
    if args.dual_json and Path(args.dual_json).exists():
        dual = load_json(Path(args.dual_json))
        for r in dual.get("rows") or []:
            if r.get("match_num"):
                dual_by_num[r["match_num"]] = r

    evaluated = []
    for s in situations:
        r = None
        if s.get("match_num"):
            r = by_num.get(s["match_num"])
        if not r:
            r = by_ha.get(k_ha(s.get("home"), s.get("away")))
        if not r:
            continue
        actual = result_1x2(r["score_90"])
        primary = s.get("primary_direction")
        alt = s.get("alt_direction")
        action = s.get("action") or "unknown"
        single_hit = primary == actual
        dual_hit = single_hit or (alt == actual)
        # observe: still score for research but flag
        qdir = ldir = None
        drow = dual_by_num.get(s.get("match_num") or "")
        if drow:
            qdir = (drow.get("quant") or {}).get("1x2")
            ldir = (drow.get("llm") or {}).get("1x2")
        else:
            tr = s.get("tracks") or {}
            qdir = (tr.get("quant") or {}).get("direction")
            ldir = (tr.get("llm") or {}).get("direction")
        q_hit = qdir == actual if qdir else None
        l_hit = ldir == actual if ldir else None
        agree = bool(qdir and ldir and qdir == ldir)

        dims = s.get("dimensions") or {}
        unc = dims.get("uncertainty") or {}
        lineup = dims.get("lineup") or {}
        evaluated.append(
            {
                "match_num": s.get("match_num"),
                "home": s.get("home"),
                "away": s.get("away"),
                "action": action,
                "label": s.get("label"),
                "primary": primary,
                "alt": alt,
                "actual": actual,
                "score_90": r["score_90"],
                "single_hit": single_hit,
                "dual_hit": dual_hit,
                "quant_dir": qdir,
                "llm_dir": ldir,
                "quant_hit": q_hit,
                "llm_hit": l_hit,
                "track_agree": agree,
                "lineup_gap": bool(lineup.get("gap")),
                "has_conflict": len(s.get("conflicts") or []) >= 1,
                "gap_count": unc.get("gap_count"),
                "uncertainty_grade": unc.get("grade"),
            }
        )

    def slice_stats(rows, pred="single_hit"):
        n = len(rows)
        h = sum(1 for x in rows if x.get(pred))
        return {"n": n, "hit": h, "hit_rate_pct": pct(h, n)}

    slices = {}
    # by action
    for act in ("single", "dual", "observe"):
        sub = [x for x in evaluated if x["action"] == act]
        slices[f"action={act}"] = {
            "primary_as_single": slice_stats(sub, "single_hit"),
            "primary_or_alt_as_dual": slice_stats(sub, "dual_hit"),
            "quant": slice_stats([x for x in sub if x["quant_hit"] is not None], "quant_hit"),
            "llm": slice_stats([x for x in sub if x["llm_hit"] is not None], "llm_hit"),
        }
    # lineup gap
    for flag, name in ((True, "lineup_gap"), (False, "lineup_ok")):
        sub = [x for x in evaluated if x["lineup_gap"] is flag]
        slices[name] = {
            "primary": slice_stats(sub, "single_hit"),
            "dual_rule": slice_stats(sub, "dual_hit"),
        }
    # conflict
    for flag, name in ((True, "has_conflict"), (False, "no_conflict")):
        sub = [x for x in evaluated if x["has_conflict"] is flag]
        slices[name] = {
            "primary": slice_stats(sub, "single_hit"),
            "dual_rule": slice_stats(sub, "dual_hit"),
        }
    # agree
    for flag, name in ((True, "track_agree"), (False, "track_disagree")):
        sub = [x for x in evaluated if x["track_agree"] is flag]
        slices[name] = {
            "primary": slice_stats(sub, "single_hit"),
            "dual_rule": slice_stats(sub, "dual_hit"),
        }

    overall = {
        "n": len(evaluated),
        "primary": slice_stats(evaluated, "single_hit"),
        "dual_rule": slice_stats(evaluated, "dual_hit"),
        "quant": slice_stats([x for x in evaluated if x["quant_hit"] is not None], "quant_hit"),
        "llm": slice_stats([x for x in evaluated if x["llm_hit"] is not None], "llm_hit"),
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "situation-slice-backtest.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "situation_source": str(args.situation),
        "results_sources": [str(p) for p in res_paths],
        "overall": overall,
        "slices": slices,
        "detail": evaluated,
        "caveat": "n<<100 不构成正式结论；observe 场次命中率仅研究用，不代表可投",
    }
    (out_dir / "situation_slice_backtest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # md
    lines = [
        f"# 态势切片回测",
        f"",
        f"> 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"> 可评场次: **{overall['n']}**  ",
        f"> 口径: 90分钟方向；dual_rule = primary 或 alt 命中  ",
        f"> ⚠️ 样本远小于 100，只作结构体检，不下投资结论",
        f"",
        f"## 总体",
        f"",
        f"| 口径 | 命中 |",
        f"|---|---|",
        f"| 态势主方向(single口径) | {overall['primary']['hit']}/{overall['primary']['n']} ({overall['primary']['hit_rate_pct']}%) |",
        f"| 态势双选规则(dual口径) | {overall['dual_rule']['hit']}/{overall['dual_rule']['n']} ({overall['dual_rule']['hit_rate_pct']}%) |",
        f"| 量化方向 | {overall['quant']['hit']}/{overall['quant']['n']} ({overall['quant']['hit_rate_pct']}%) |",
        f"| LLM方向 | {overall['llm']['hit']}/{overall['llm']['n']} ({overall['llm']['hit_rate_pct']}%) |",
        f"",
        f"## 按 action 切片",
        f"",
        f"| action | n | 主方向命中 | 双选规则命中 | 量化 | LLM |",
        f"|---|---:|---:|---:|---:|---:|",
    ]
    for act in ("single", "dual", "observe"):
        sl = slices[f"action={act}"]
        def fmt(b):
            if not b or not b["n"]:
                return "—"
            return f"{b['hit']}/{b['n']} ({b['hit_rate_pct']}%)"
        lines.append(
            f"| {act} | {sl['primary_as_single']['n']} | {fmt(sl['primary_as_single'])} | "
            f"{fmt(sl['primary_or_alt_as_dual'])} | {fmt(sl['quant'])} | {fmt(sl['llm'])} |"
        )

    lines += [
        f"",
        f"## 其他切片",
        f"",
        f"| 切片 | n | 主方向 | 双选规则 |",
        f"|---|---:|---:|---:|",
    ]
    for name in ("lineup_gap", "lineup_ok", "has_conflict", "no_conflict", "track_agree", "track_disagree"):
        sl = slices[name]
        n = sl["primary"]["n"]
        lines.append(
            f"| {name} | {n} | {sl['primary']['hit']}/{n} ({sl['primary']['hit_rate_pct']}%) | "
            f"{sl['dual_rule']['hit']}/{n} ({sl['dual_rule']['hit_rate_pct']}%) |"
        )

    lines += [f"", f"## 逐场明细", f"", f"| 场次 | 动作 | 主/备 | 实际 | 比分 | 主中 | 双中 | Q | L |", f"|---|---|---|---|---|---|---|---|---|"]
    for x in evaluated:
        lines.append(
            f"| {x['match_num']} | {x['action']} | {x['primary']}"
            f"{('/'+x['alt']) if x.get('alt') else ''} | {x['actual']} | {x['score_90']} | "
            f"{'✔' if x['single_hit'] else '✘'} | {'✔' if x['dual_hit'] else '✘'} | "
            f"{'✔' if x['quant_hit'] else ('✘' if x['quant_hit'] is False else '—')} | "
            f"{'✔' if x['llm_hit'] else ('✘' if x['llm_hit'] is False else '—')} |"
        )
    lines += [
        f"",
        f"## 读法",
        f"",
        f"1. **observe 命中率高也不代表可投**——样本偏差+未下注筛选。",
        f"2. 关注: single 是否显著高于 dual/observe 的主方向命中（结构是否健康）。",
        f"3. lineup_ok vs lineup_gap：有首发后是否改善（需更多样本）。",
        f"4. 累计 ≥100 场同版本再谈结论。",
        f"",
    ]
    (out_dir / "situation_slice_backtest.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"evaluated {len(evaluated)} -> {out_dir}")
    print("overall primary", overall["primary"], "dual_rule", overall["dual_rule"])
    for act in ("single", "dual", "observe"):
        print(act, slices[f"action={act}"]["primary_as_single"])


if __name__ == "__main__":
    main()

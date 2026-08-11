# -*- coding: utf-8 -*-
"""
把 MatchSituation 并入双轨对照，并重写带态势列的双轨报告。

用法:
  python integrate_situation_dual.py \\
    --situation data/situation_2026-08-08/situations.json \\
    --dual-json "F:/HM足球比赛预测/今日推荐_双轨4玩法_20260808/dual_track_4markets.json" \\
    --dual-report "F:/HM足球比赛预测/今日推荐_20260808/今日双轨报告_20260808.md" \\
    --out-dir "F:/HM足球比赛预测/今日推荐_20260808"
"""
from __future__ import annotations

import argparse
import io
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


def load_json(p: Path):
    return json.loads(io.open(p, encoding="utf-8-sig").read())


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())


def key(home, away):
    return f"{norm(home)}|{norm(away)}"


def index_situations(batch: dict) -> dict:
    out = {}
    for s in batch.get("situations") or []:
        if s.get("match_num"):
            out[f"num:{s['match_num']}"] = s
        out[key(s.get("home"), s.get("away"))] = s
    return out


def attach(dual: dict, sit_idx: dict) -> dict:
    rows = dual.get("rows") or []
    attached = 0
    for r in rows:
        s = sit_idx.get(f"num:{r.get('match_num')}") or sit_idx.get(key(r.get("home"), r.get("away")))
        if not s:
            r["situation"] = None
            continue
        r["situation"] = {
            "action": s.get("action"),
            "label": s.get("label"),
            "primary_direction": s.get("primary_direction"),
            "alt_direction": s.get("alt_direction"),
            "conflicts": s.get("conflicts") or [],
            "conflict_n": len(s.get("conflicts") or []),
            "fund_lean": s.get("fund_lean"),
            "uncertainty_grade": ((s.get("dimensions") or {}).get("uncertainty") or {}).get("grade"),
            "gap_count": ((s.get("dimensions") or {}).get("uncertainty") or {}).get("gap_count"),
            "lineup_gap": ((s.get("dimensions") or {}).get("lineup") or {}).get("gap"),
            "has_lineups_signal": not ((s.get("dimensions") or {}).get("lineup") or {}).get("gap", True),
            "action_reasons": s.get("action_reasons") or [],
            "banker_allowed": False,
        }
        attached += 1
    dual = dict(dual)
    dual["situation_attached"] = attached
    dual["situation_schema"] = "match_situation.v1"
    dual["situation_integrated_at"] = datetime.now().isoformat(timespec="seconds")
    acts = Counter((r.get("situation") or {}).get("action") for r in rows if r.get("situation"))
    dual["situation_action_counts"] = dict(acts)
    return dual


def dir_letter(d):
    return {"主胜": "H", "平局": "D", "客胜": "A", "H": "H", "D": "D", "A": "A"}.get(d or "", "—")


def render_integrated_report(dual: dict, title_date: str) -> str:
    rows = dual.get("rows") or []
    acts = dual.get("situation_action_counts") or {}
    lines = [
        f"# 今日双轨 + 态势对照 · {title_date}",
        f"",
        f"> 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"> 量化 / LLM 双轨 + **MatchSituation** 动作层  ",
        f"> `single`=单选对照(非出胆) · `dual`=双选 · `observe`=仅观察 · **永不由态势出胆**",
        f"",
        f"## 0. 态势动作分布",
        f"",
        f"| 动作 | 场次 | 含义 |",
        f"|---|---:|---|",
        f"| single | {acts.get('single',0)} | 双轨较一致，可作对照，**不等于出胆** |",
        f"| dual | {acts.get('dual',0)} | 证据薄/冲突/低置信 → 双选 |",
        f"| observe | {acts.get('observe',0)} | 无HAD/身份疑/信息过薄 → 仅观察 |",
        f"",
        f"已挂接态势: **{dual.get('situation_attached',0)}** / {len(rows)} 场",
        f"",
        f"## 1. 总表（双轨 + 态势）",
        f"",
        f"| 编号 | 对阵 | 量化 | LLM | 一致 | 态势动作 | 态势主/备 | 标签 | 冲突 |",
        f"|---|---|---|---|---|---|---|---|---:|",
    ]
    for r in rows:
        q = r.get("quant") or {}
        l = r.get("llm") or {}
        s = r.get("situation") or {}
        qdir = q.get("1x2") or "—"
        ldir = l.get("1x2") or "—"
        if q.get("1x2") and l.get("1x2"):
            agree = "✅" if q.get("1x2") == l.get("1x2") else "⚠️"
        elif not q.get("1x2"):
            agree = "仅LLM"
        else:
            agree = "—"
        act = s.get("action") or "—"
        prim = s.get("primary_direction") or "—"
        alt = s.get("alt_direction")
        pb = f"{prim}" + (f"/{alt}" if alt else "")
        lines.append(
            f"| {r.get('match_num','')} | {r.get('home')} vs {r.get('away')} | "
            f"**{qdir}** | **{ldir}** | {agree} | `{act}` | {pb} | {s.get('label') or '—'} | {s.get('conflict_n', 0)} |"
        )

    lines += [
        f"",
        f"## 2. 建议阅读顺序",
        f"",
        f"1. 先看 **observe**（直接跳过下注）",
        f"2. 再看 **dual**（只作双选对照）",
        f"3. 最后看 **single**（仍要过量化 `banker_allowed`，今日通常全 false）",
        f"",
        f"## 3. 逐场要点（态势理由）",
        f"",
    ]
    for r in rows:
        s = r.get("situation") or {}
        if not s:
            continue
        lines.append(f"### {r.get('match_num')} {r.get('home')} vs {r.get('away')}")
        lines.append(f"- 动作: `{s.get('action')}` · {s.get('label')}")
        if s.get("action_reasons"):
            lines.append("- 理由: " + "；".join(s["action_reasons"]))
        if s.get("conflicts"):
            lines.append("- 冲突: " + "；".join(s["conflicts"]))
        q, l = r.get("quant") or {}, r.get("llm") or {}
        lines.append(
            f"- 量化 {q.get('1x2') or '—'} / LLM {l.get('1x2') or '—'} "
            f"比分 Q:{q.get('score') or '—'} L:{l.get('score') or '—'}"
        )
        lines.append("")

    lines += [
        f"## 4. 回测切片入口",
        f"",
        f"```bash",
        f"python backtest_situation_slices.py \\",
        f"  --situation situations.json \\",
        f"  --results-glob data/results_*.json \\",
        f"  --out situation_backtest.md",
        f"```",
        f"",
        f"切片维度: action × lineup_gap × conflict_n≥1 × 双轨是否一致",
        f"",
        f"## 5. 免责",
        f"",
        f"概率/定性/态势输出均非投注建议；出胆仅以量化 recommendation_gate 为准。",
        f"",
    ]
    return "\n".join(lines)


def patch_existing_report(report_path: Path, dual: dict) -> str | None:
    """Insert situation section into existing dual report if present."""
    if not report_path.exists():
        return None
    text = report_path.read_text(encoding="utf-8")
    marker = "## 态势动作层（MatchSituation）"
    block_lines = [
        marker,
        "",
        f"> 自动并入 · {datetime.now().strftime('%Y-%m-%d %H:%M')} · schema match_situation.v1",
        "",
        "| 编号 | 态势动作 | 主/备 | 标签 | 冲突数 |",
        "|---|---|---|---|---:|",
    ]
    for r in dual.get("rows") or []:
        s = r.get("situation") or {}
        if not s:
            continue
        pb = s.get("primary_direction") or "—"
        if s.get("alt_direction"):
            pb += f"/{s['alt_direction']}"
        block_lines.append(
            f"| {r.get('match_num')} | `{s.get('action')}` | {pb} | {s.get('label') or '—'} | {s.get('conflict_n',0)} |"
        )
    acts = dual.get("situation_action_counts") or {}
    block_lines += [
        "",
        f"分布: single={acts.get('single',0)} · dual={acts.get('dual',0)} · observe={acts.get('observe',0)} "
        f"（全部非出胆）",
        "",
        "---",
        "",
    ]
    block = "\n".join(block_lines)
    if marker in text:
        # replace old block until next ## or end
        text = re.sub(
            rf"{re.escape(marker)}[\s\S]*?(?=\n## |\Z)",
            block,
            text,
            count=1,
        )
    else:
        # insert after first --- following title block, or before ## 2
        if "## 2. 双轨对照表" in text:
            text = text.replace("## 2. 双轨对照表", block + "## 2. 双轨对照表")
        else:
            text = text.rstrip() + "\n\n" + block
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--situation", required=True)
    ap.add_argument("--dual-json", required=True)
    ap.add_argument("--dual-report", default="", help="existing 今日双轨报告.md to patch")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--date-label", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sit = load_json(Path(args.situation))
    dual = load_json(Path(args.dual_json))
    dual2 = attach(dual, index_situations(sit))

    out_json = out_dir / "dual_track_with_situation.json"
    out_json.write_text(json.dumps(dual2, ensure_ascii=False, indent=2), encoding="utf-8")

    label = args.date_label or datetime.now().strftime("%Y-%m-%d")
    report = render_integrated_report(dual2, label)
    out_md = out_dir / f"双轨态势对照_{label.replace('-', '')}.md"
    out_md.write_text(report, encoding="utf-8")

    if args.dual_report:
        patched = patch_existing_report(Path(args.dual_report), dual2)
        if patched:
            Path(args.dual_report).write_text(patched, encoding="utf-8")
            # also copy beside
            (out_dir / Path(args.dual_report).name).write_text(patched, encoding="utf-8")
            print("patched", args.dual_report)

    print("wrote", out_json)
    print("wrote", out_md)
    print("attached", dual2.get("situation_attached"), "actions", dual2.get("situation_action_counts"))


if __name__ == "__main__":
    main()

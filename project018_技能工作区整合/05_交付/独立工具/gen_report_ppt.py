#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_report_ppt — 把预测结果 / 回测报告生成 PPT。

用法：
  python gen_report_ppt.py prediction --date 2026-08-12 [--out 报告.pptx]
     扫描 project021/05_交付/每日开售预测/<日期>/ 下的 *_output.json，生成预测报告 PPT。
  python gen_report_ppt.py backtest --input <backtest.json> [--out 报告.pptx]
     从融合全量回测报告 JSON 生成回测 PPT。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

DELIVERY = Path(r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练\05_交付")
# daily_pipeline 的直接产物目录（采集/登记的 input/output json 写在这里）
WORK = Path(r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion/forward")
FONT = "微软雅黑"
DARK = RGBColor(0x1F, 0x3B, 0x57)
ACCENT = RGBColor(0x2E, 0x75, 0xB6)
OK = RGBColor(0x2E, 0x8B, 0x57)
WARN = RGBColor(0xC0, 0x50, 0x0F)


def _style(run, size=14, bold=False, color=None, name=FONT):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def _title(slide, text, size=28):
    box = slide.shapes.title
    box.text = text
    para = box.text_frame.paragraphs[0]
    if para.runs:
        _style(para.runs[0], size=size, bold=True, color=DARK)


def _add_slide(prs, text):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    _title(slide, text)
    return slide


def _bullet(slide, lines, top=1.6):
    box = slide.shapes.add_textbox(Inches(0.6), Inches(top), Inches(9.0), Inches(5.0))
    tf = box.text_frame
    first = True
    for text, size, bold, color in lines:
        if not text:
            continue
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.text = text
        if p.runs:
            _style(p.runs[0], size=size, bold=bold, color=color)
        p.space_after = Pt(6)
    return box


def _table(slide, rows, cols, data, top=1.8, col_w=None, header_fill=DARK):
    shape = slide.shapes.add_table(rows, cols, Inches(0.5), Inches(top),
                                   Inches(9.0), Inches(0.5 * rows))
    table = shape.table
    if col_w:
        for i, w in enumerate(col_w):
            table.columns[i].width = Inches(w)
    for r in range(rows):
        for c in range(cols):
            cell = table.cell(r, c)
            cell.text = str(data[r][c])
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.name = FONT
                    run.font.size = Pt(11 if r else 12)
                    run.font.bold = (r == 0)
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if r == 0 else RGBColor(0x20, 0x20, 0x20)
    return table


def _prediction_rows(date_iso):
    # 两个目录合并扫描：交付目录（人工整理/PPT 输出）+ 流水线产物目录（外部 WORK）
    dirs = [DELIVERY / "每日开售预测" / date_iso, WORK / date_iso]
    existing = [d for d in dirs if d.exists()]
    if not existing:
        for base, label in ((DELIVERY / "每日开售预测", "交付目录"), (WORK, "流水线产物目录")):
            if base.exists():
                avail = sorted(d.name for d in base.iterdir() if d.is_dir())
                print(f"{label} 已有日期：{', '.join(avail[-12:])}")
        print(f"未找到目录：{dirs[0]} 或 {dirs[1]}")
        sys.exit(1)
    outputs, seen_names = [], set()
    for d in existing:
        for p in sorted(d.glob("*_output.json")):
            if p.name.endswith(".registry-core.json") or p.name in seen_names:
                continue
            seen_names.add(p.name)
            outputs.append(p)
    if not outputs:
        print(f"{[str(d) for d in existing]} 下没有 *_output.json 预测产物")
        sys.exit(1)
    rows = []
    # 无赔率场次（predict_no_odds 产物）也并入报告
    for d in existing:
        for p in sorted(d.glob("no_odds_*.json")):
            nd = json.loads(p.read_text(encoding="utf-8"))
            pred = nd.get("prediction") or {}
            probs = pred.get("probs_1x2") or []
            rows.append({
                "num": nd.get("match_num") or p.stem.replace("no_odds_", ""),
                "match": f"{nd.get('home_cn') or nd.get('home')} vs {nd.get('away_cn') or nd.get('away')}",
                "pct": [round(x * 100, 1) for x in probs] if len(probs) == 3 else [],
                "top3": [(s.get("score"), round(s.get("p", 0) * 100, 1))
                         for s in (pred.get("top_scores") or [])[:3]],
                "ou25": round(pred.get("over25", 0) * 100, 1) if pred.get("over25") else None,
                "btts": round(pred.get("btts", 0) * 100, 1) if pred.get("btts") else None,
                "dep": None,
                "gate": f"{nd.get('verdict')}(无赔率)",
                "status": nd.get("market_dependency"),
            })
    for p in outputs:
        d = json.loads(p.read_text(encoding="utf-8"))
        core = d.get("core_output") or {}
        fc = d.get("forecast") or {}
        pct = fc.get("final_1x2_pct") or core.get("final_1x2_pct") or []
        top3 = [(s.get("score"), s.get("prob_pct")) for s in (fc.get("top_scores") or [])[:3]]
        ou = (fc.get("ou_2_5") or core.get("ou_2_5") or {})
        bt = (fc.get("btts") or core.get("btts") or {})
        rows.append({
            "num": p.stem.replace("_output", ""),
            "match": d.get("match") or "",
            "pct": [round(x, 1) for x in pct],
            "top3": top3,
            "ou25": ou.get("over_pct"),
            "btts": bt.get("yes_pct"),
            "dep": d.get("market_dependency_pct"),
            "gate": (d.get("recommendation_gate") or {}).get("confidence_status"),
            "status": d.get("fusion_status"),
        })
    rows.sort(key=lambda r: r["num"])
    return rows, dirs[0]


def build_prediction_ppt(date_iso, out):
    rows, _day_dir = _prediction_rows(date_iso)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # 标题页
    s = prs.slides.add_slide(prs.slide_layouts[0])
    _title(s, f"足球预测报告 · {date_iso}", size=34)
    sub = s.placeholders[1]
    sub.text = f"共 {len(rows)} 场 · 生成时间 {datetime.now():%Y-%m-%d %H:%M}"
    for p in sub.text_frame.paragraphs:
        for run in p.runs:
            _style(run, size=18, color=ACCENT)

    # 汇总表
    s = _add_slide(prs, "预测总览")
    data = [["场次", "对阵", "主胜%", "平%", "客胜%", "比分Top1", "大2.5%", "BTTS%", "市场依赖%", "门控"]]
    for r in rows:
        pct = r["pct"] if len(r["pct"]) == 3 else ["-", "-", "-"]
        data.append([
            r["num"], r["match"][:18], pct[0], pct[1], pct[2],
            (r["top3"][0][0] if r["top3"] else "-"),
            ("-" if r["ou25"] is None else round(r["ou25"], 1)),
            ("-" if r["btts"] is None else round(r["btts"], 1)),
            ("-" if r["dep"] is None else r["dep"]),
            r["gate"] or r["status"] or "-",
        ])
    _table(s, len(data), len(data[0]), data, top=1.4,
           col_w=[1.0, 2.2, 0.85, 0.7, 0.85, 1.1, 0.85, 0.8, 1.1, 1.0])

    # 每场一页
    for r in rows:
        s = _add_slide(prs, f"{r['num']} · {r['match']}")
        pct = r["pct"] if len(r["pct"]) == 3 else []
        lines = []
        if pct:
            lines.append((f"胜平负概率：主胜 {pct[0]}% ｜ 平 {pct[1]}% ｜ 客胜 {pct[2]}%", 22, True, DARK))
        if r["top3"]:
            ts = "  ｜  ".join(f"{sc} ({pb:.1f}%)" for sc, pb in r["top3"])
            lines.append((f"比分 Top3：{ts}", 16, False, ACCENT))
        if r["ou25"] is not None:
            lines.append((f"大小球 2.5：大 {r['ou25']:.1f}% / 小 {100 - r['ou25']:.1f}%", 14, False, None))
        if r["btts"] is not None:
            lines.append((f"两队都进球 BTTS：是 {r['btts']:.1f}% / 否 {100 - r['btts']:.1f}%", 14, False, None))
        dep = r["dep"]
        if dep is not None:
            col = WARN if dep >= 70 else None
            lines.append((f"市场依赖度：{dep}%（{'主要为复述盘口' if dep >= 70 else '正常'}）", 14, False, col))
        lines.append((f"推荐门控状态：{r['gate'] or r['status'] or '-'}", 14, True,
                      OK if (r["gate"] or "") == "VALID" else WARN))
        _bullet(s, lines)
        note = s.shapes.add_textbox(Inches(0.6), Inches(6.6), Inches(12.0), Inches(0.6))
        note.text_frame.text = "概率模型输出，非投注建议。数据来源：中国体彩官方 + 融合引擎。"
        for p in note.text_frame.paragraphs:
            for run in p.runs:
                _style(run, size=10, color=RGBColor(0x88, 0x88, 0x88))

    out = out or (DELIVERY / "每日开售预测" / date_iso / f"预测报告_{date_iso}.pptx")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return out, len(rows)


def build_backtest_ppt(backtest_json, out):
    d = json.loads(Path(backtest_json).read_text(encoding="utf-8"))
    ov = d.get("overall") or {}
    score = ov.get("score") or {}
    gate = d.get("calibration_gate") or {}
    pm = d.get("paired_market") or {}
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # 标题页
    s = prs.slides.add_slide(prs.slide_layouts[0])
    _title(s, "融合模型回测报告", size=34)
    sub = s.placeholders[1]
    sub.text = (f"样本 {d.get('sample_size')} 场（去重 {d.get('unique_match_n')} 场）"
                f" · 生成 {datetime.now():%Y-%m-%d %H:%M}")
    for p in sub.text_frame.paragraphs:
        for run in p.runs:
            _style(run, size=18, color=ACCENT)

    # 总指标
    s = _add_slide(prs, "核心指标")
    data = [["指标", "值"],
            ["1X2 命中率", f"{ov.get('accuracy_pct')}%"],
            ["Brier", f"{ov.get('brier_mean')}"],
            ["Log Loss", f"{ov.get('log_loss')}"],
            ["ECE（校准误差）", f"{ov.get('ece')}"],
            ["比分 Top1 / Top3", f"{score.get('top1_accuracy_pct')}% / {score.get('top3_accuracy_pct')}%"],
            ["大小球 2.5 Brier", f"{ov.get('ou_2_5_brier')}"],
            ["BTTS Brier", f"{ov.get('btts_brier')}"],
            ["CLV 均值", f"{ov.get('clv_mean_pp')}pp（n={ov.get('clv_n')}）"]]
    _table(s, len(data), 2, data, top=1.5, col_w=[4.0, 5.0])

    # 市场配对 + 校准门禁
    s = _add_slide(prs, "市场对比与校准门禁")
    lines = []
    if pm.get("n"):
        lines.append((f"同场配对（n={pm.get('n')}）：模型 Brier 差市场 {pm.get('brier_delta_model_minus_market')}"
                      f"，95%CI {pm.get('brier_delta_95ci')}", 16, True, DARK))
        lines.append(("负值=模型优于市场；95%CI 跨 0 = 无统计证据。", 13, False, None))
    lines.append((f"重校准门槛进度：{gate.get('current_version_n')}/100"
                  f"（可重校准：{'是' if gate.get('ready_for_recalibration') else '否'}）", 16, True,
                  OK if gate.get('ready_for_recalibration') else WARN))
    lines.append((f"审阈值门槛进度：{gate.get('current_version_n')}/200"
                  f"（可审阈值：{'是' if gate.get('ready_for_threshold_review') else '否'}）", 14, False, None))
    lines.append((d.get('warning') or "", 13, False, WARN))
    _bullet(s, lines)

    # 版本归因
    s = _add_slide(prs, "版本归因（by_version_cohort）")
    data = [["cohort", "样本数", "1X2命中%", "Brier", "ECE"]]
    for k, v in (d.get("by_version_cohort") or {}).items():
        data.append([k, v.get("n"), v.get("accuracy_pct"), v.get("brier_mean"), v.get("ece")])
    _table(s, len(data), 5, data, top=1.4, col_w=[2.0, 1.4, 1.7, 2.0, 1.7])

    out = out or Path(backtest_json).with_suffix(".pptx")
    prs.save(str(out))
    return out, d.get("sample_size")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)
    p1 = sub.add_parser("prediction")
    p1.add_argument("--date", required=True, help="YYYY-MM-DD")
    p1.add_argument("--out")
    p2 = sub.add_parser("backtest")
    p2.add_argument("--input", required=True, help="backtest JSON")
    p2.add_argument("--out")
    a = ap.parse_args()

    if a.kind == "prediction":
        out, n = build_prediction_ppt(a.date, a.out)
    else:
        out, n = build_backtest_ppt(a.input, a.out)
    print(f"[PPT 已生成] {out}（{n} 条）")


if __name__ == "__main__":
    main()

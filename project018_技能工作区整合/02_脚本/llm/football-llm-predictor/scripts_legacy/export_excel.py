#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预测结果导出 Excel
==================
解析 predictions_*.txt(预测报告) + raw_*.json(官方赔率) -> 生成带格式的 Excel。

用法:
  python export_excel.py --report data/predictions_2026-08-05.txt \
                         --raw data/raw_2026-08-05.json \
                         --output data/预测报告_2026-08-05.xlsx
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import football_predictor as fp

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "微软雅黑"
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(name=FONT, size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT, size=10)
BOLD_FONT = Font(name=FONT, size=10, bold=True)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)


def parse_report(path):
    """解析预测报告txt, 返回比赛列表。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    matches = []
    # 按 "⚽ 第X场" 分块(每场比赛的头部+详情在同一个块内)
    blocks = re.split(r"(?=⚽ 第\d+/\d+场)", text)
    for blk in blocks:
        blk = blk.strip()
        if "⚽ 第" not in blk:
            continue
        m = re.search(r"⚽ 第\d+/\d+场 \[([^\]]*)\] (.+?) VS (.+?) \| (.+?) \| (.+?)\s*$",
                      blk, re.M)
        if not m:
            continue
        match = {
            "match_num": m.group(1), "home": m.group(2), "away": m.group(3),
            "league": m.group(4), "kickoff": m.group(5).strip(),
            "models": [],
        }
        g = re.search(r"📊 综合预测: .+? (\d+) - (\d+) .+? \(([^,]+), (\d+)/(\d+)票\)", blk)
        if g:
            match.update(hs=int(g.group(1)), as_=int(g.group(2)),
                         result=g.group(3), votes=int(g.group(4)),
                         valid=int(g.group(5)))
        g = re.search(r"🎯 平均置信度: (\d+)%", blk)
        if g:
            match["confidence"] = int(g.group(1))
        g = re.search(r"⚖️ 分歧度: (\d+)%", blk)
        if g:
            match["disagreement"] = int(g.group(1))
        g = re.search(r"🏷️ 官方胜平负: ([\d.]+)/([\d.]+)/([\d.]+)", blk)
        if g:
            match["odds_had"] = [float(g.group(1)), float(g.group(2)), float(g.group(3))]
        g = re.search(r"🏷️ 官方让球\(([+-]?\d*\.?\d*)\): ([\d.]+)/([\d.]+)/([\d.]+)", blk)
        if g:
            match["odds_hhad_line"] = g.group(1)
            match["odds_hhad"] = [float(g.group(2)), float(g.group(3)), float(g.group(4))]
            match["model_hhad"] = {"line": float(g.group(1)),
                                   "odds": list(match["odds_hhad"])}
        for gm in re.finditer(
                r"\[([^\]]+)\] (\d+)-(\d+) \(([^,]+), 置信\s*(\d+)%\) — (.*)",
                blk):
            match["models"].append({
                "model": gm.group(1).strip(), "hs": int(gm.group(2)),
                "as_": int(gm.group(3)), "result": gm.group(4),
                "confidence": int(gm.group(5)), "reasoning": gm.group(6).strip(),
                "total_goals": "", "half_result": "",
            })
        # 新格式模型行: 含 总:X球 半:X 置信:X%
        if not match["models"]:
            for gm in re.finditer(
                    r"\[([^\]]+)\] (\d+)-(\d+) (\S+) 总:(\S+)球 半:(\S+) "
                    r"置信:(\d+)% — (.*)",
                    blk):
                match["models"].append({
                    "model": gm.group(1).strip(), "hs": int(gm.group(2)),
                    "as_": int(gm.group(3)), "result": gm.group(4),
                    "total_goals": gm.group(5),
                    "half_result": "" if gm.group(6) == "-" else gm.group(6),
                    "confidence": int(gm.group(7)),
                    "reasoning": gm.group(8).strip(),
                })
        # 总进球/半全场综合行
        g = re.search(r"🎯 总进球: 预测 (\S+)球.*?官方最低:(\S+)球.*?\| (✅一致|⚠️分歧)", blk)
        if g:
            match["ttg_pred"], match["ttg_official"], match["ttg_agree"] = \
                g.group(1), g.group(2), g.group(3)
        g = re.search(r"🏁 半全场: 预测 (\S+).*?官方最低:(\S+).*?\| (✅一致|⚠️分歧)", blk)
        if g:
            match["hafu_pred"], match["hafu_official"], match["hafu_agree"] = \
                g.group(1), g.group(2), g.group(3)
        matches.append(match)
    return matches


def style_header(ws, ncols, row=1):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cell.border = BORDER


def build_summary_sheet(wb, matches):
    ws = wb.active
    ws.title = "预测汇总"
    headers = ["序号", "场次编号", "联赛", "主队", "客队", "开球时间",
               "官方胜平负(主/平/客)", "官方隐含概率-主", "官方隐含概率-平",
               "官方隐含概率-客", "官方让球线", "让球赔率(主/平/客)",
               "让球结果预测", "官方让球倾向", "模型vs官方",
               "综合预测比分", "综合赛果", "得票", "模型数", "平均置信度",
               "分歧度", "总进球预测", "官方TTG最低", "模型vs官方(TTG)",
               "半全场预测", "官方HAFU最低", "模型vs官方(HAFU)"]
    ws.append(headers)
    style_header(ws, len(headers))
    for i, m in enumerate(matches, 1):
        r = ws.max_row + 1
        had = m.get("odds_had") or []
        hhad = m.get("odds_hhad") or []
        ha = fp.hhad_analysis(m, (m["hs"], m["as_"])) if "model_hhad" in m else None
        ws.append([
            i, m.get("match_num", ""), m.get("league", ""), m["home"], m["away"],
            m.get("kickoff", ""),
            f"{had[0]}/{had[1]}/{had[2]}" if len(had) == 3 else "",
            f"=1/{had[0]}" if len(had) >= 1 else "",
            f"=1/{had[1]}" if len(had) >= 2 else "",
            f"=1/{had[2]}" if len(had) >= 3 else "",
            m.get("odds_hhad_line", ""),
            f"{hhad[0]}/{hhad[1]}/{hhad[2]}" if len(hhad) == 3 else "",
            ha["result"] if ha else "",
            ha["official_dir"] if ha else "",
            "✅一致" if ha and ha["agree"] else ("⚠️分歧" if ha else ""),
            f"{m['home']} {m['hs']}-{m['as_']} {m['away']}",
            m.get("result", ""),
            f"{m.get('votes', 0)}/{m.get('valid', 0)}",
            m.get("valid", 0),
            m.get("confidence", 0) / 100,
            f"{m.get('disagreement', 0)}%",
            m.get("ttg_pred", ""),
            m.get("ttg_official", ""),
            m.get("ttg_agree", ""),
            m.get("hafu_pred", ""),
            m.get("hafu_official", ""),
            m.get("hafu_agree", ""),
        ])
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = BODY_FONT
            cell.border = BORDER
            cell.alignment = CENTER if c not in (3, 4, 5, 7, 12, 13) else LEFT
        ws.cell(row=r, column=20).number_format = "0%"  # 平均置信度
        for c in (8, 9, 10):
            ws.cell(row=r, column=c).number_format = "0.0%"
    widths = [5, 9, 8, 14, 14, 14, 18, 10, 10, 10, 9, 18, 12, 12, 11,
              20, 8, 7, 7, 10, 8, 11, 11, 14, 11, 12, 15]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    return ws


def build_detail_sheet(wb, matches):
    ws = wb.create_sheet("模型明细")
    headers = ["场次编号", "主队", "客队", "模型", "预测比分", "赛果",
               "让球结果", "总进球", "半场结果", "半全场", "置信度", "模型理由"]
    ws.append(headers)
    style_header(ws, len(headers))
    for m in matches:
        for md in m["models"]:
            r = ws.max_row + 1
            hh_res = ""
            if "model_hhad" in m:
                hh_res = fp.hhad_result(md["hs"], md["as_"],
                                        m["model_hhad"]["line"])
            tg = md.get("total_goals") or fp.ttg_from_score(md["hs"], md["as_"])
            hr = md.get("half_result", "")
            hafu = fp.hafu_result(hr, md["result"]) if hr else ""
            ws.append([
                m.get("match_num", ""), m["home"], m["away"], md["model"],
                f"{md['hs']}-{md['as_']}", md["result"], hh_res, tg,
                hr, hafu, md["confidence"] / 100, md["reasoning"],
            ])
            for c in range(1, len(headers) + 1):
                cell = ws.cell(row=r, column=c)
                cell.font = BODY_FONT
                cell.border = BORDER
                cell.alignment = CENTER if c != 12 else LEFT
            ws.cell(row=r, column=11).number_format = "0%"
    widths = [9, 14, 14, 24, 10, 8, 10, 8, 8, 8, 9, 70]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    return ws


def build_notes_sheet(wb, source_report, source_raw):
    ws = wb.create_sheet("说明")
    rows = [
        ["多LLM足球比分预测 — 数据说明", ""],
        ["", ""],
        ["生成时间", "见文件名日期"],
        ["数据来源", "中国体彩网移动端官方链路 (webapi.sporttery.cn)"],
        ["预测方法", "6个免费LLM独立预测后投票聚合 (智谱/千问/Groq/Kimi/Gemini/豆包)"],
        ["", ""],
        ["字段说明", ""],
        ["官方胜平负(主/平/客)", "体彩官方固定奖金赔率"],
        ["官方隐含概率", "= 1/赔率, 未扣除抽水, 仅供方向参考"],
        ["综合预测比分", "模型投票众数比分"],
        ["综合赛果", "模型投票众数赛果(主胜/平局/客胜)"],
        ["分歧度", "不同比分票数占比, 越高说明模型意见越分散"],
        ["", ""],
        ["⚠️ 免责声明", ""],
        ["1. 足球比分预测本质极难, 本报告仅作研究与娱乐用途", ""],
        ["2. 任何声称高正确率的预测均不可作为投注依据", ""],
        ["3. 未完成场次无赛果, 本报告不构成任何投资建议", ""],
    ]
    for row in rows:
        ws.append(row)
    ws.cell(row=1, column=1).font = Font(name=FONT, size=13, bold=True)
    ws.cell(row=14, column=1).font = Font(name=FONT, size=11, bold=True,
                                          color="C00000")
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 90
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="预测报告txt")
    ap.add_argument("--raw", required=True, help="采集原始json")
    ap.add_argument("--output", required=True, help="输出xlsx路径")
    args = ap.parse_args()

    matches = parse_report(args.report)
    if not matches:
        print("未解析到任何比赛, 请检查报告格式")
        return

    with open(args.raw, encoding="utf-8") as f:
        raw = json.load(f)
    raw_by_num = {m.get("match_num"): m for m in raw.get("matches", [])}
    for m in matches:
        r = raw_by_num.get(m.get("match_num"))
        if r and not m.get("odds_had"):
            mo = r.get("model_odds") or []
            if len(mo) >= 3:
                m["odds_had"] = [float(x) for x in mo]
            hh = r.get("model_hhad") or {}
            if hh.get("odds"):
                m["odds_hhad_line"] = f"{hh.get('line', 0):+g}"
                m["odds_hhad"] = [float(x) for x in hh["odds"]]

    wb = Workbook()
    build_summary_sheet(wb, matches)
    build_detail_sheet(wb, matches)
    build_notes_sheet(wb, args.report, args.raw)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    wb.save(args.output)
    print(f"✅ 已生成: {args.output}")
    print(f"   {len(matches)} 场比赛, "
          f"{sum(len(m['models']) for m in matches)} 条模型明细")


if __name__ == "__main__":
    main()

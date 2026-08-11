#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 轨道证据版报告生成器
========================
解析 predictions_*.txt(方向型输出) -> Markdown 报告 + Excel。
"""
import json
import re
import sys

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
    """解析证据版预测报告txt -> 比赛列表。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    matches = []
    blocks = re.split(r"(?=⚽ 第\d+/\d+场)", text)
    for blk in blocks:
        blk = blk.strip()
        if "⚽ 第" not in blk or "综合方向" not in blk:
            continue
        m = re.search(r"⚽ 第(\d+)/\d+场 \[([^\]]*)\] (.+?) VS (.+?) \| (.+?) \| (.+?)\s*$",
                      blk, re.M)
        if not m:
            continue
        idx, num, home, away, league, kickoff = m.groups()
        d = re.search(r"综合方向: (.+?)  \((\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)票, 强度(\d+)%\)", blk)
        sp = re.search(r"比分偏好: (.+)", blk)
        votes = re.search(r"投票分布: (.+)", blk)
        match = {
            "idx": int(idx), "num": num, "home": home.strip(),
            "away": away.strip(), "league": league.strip(),
            "kickoff": kickoff.strip(),
            "direction": d.group(1) if d else "",
            "votes": d.group(2) if d else "",
            "total": d.group(3) if d else "",
            "strength": d.group(4) if d else "",
            "score_pref": sp.group(1).strip() if sp else "",
            "vote_dist": votes.group(1).strip() if votes else "",
            "individual": [],
        }
        for line in blk.splitlines():
            im = re.match(r"\s+\[(.+?)\s*\] (.+?)( 比分:.+?)? — (.+)", line)
            if im and "失败" not in line and "综合方向" not in line:
                match["individual"].append({
                    "model": im.group(1).strip(),
                    "dir": im.group(2).strip(),
                    "reasoning": im.group(4).strip(),
                })
        matches.append(match)
    return matches


def build_markdown(matches, raw_path):
    """生成 Markdown 报告。"""
    with open(raw_path, encoding="utf-8") as f:
        data = json.load(f)
    odds_map = {}
    for m in data["matches"]:
        odds_map[f"{m['home']}|{m['away']}"] = (m.get("model_odds") or [])

    lines = []
    lines.append("# ⚽ LLM 轨道证据驱动预测报告 (2026-08-07)\n")
    lines.append("> 方法: 六类证据(伤停/战意/近况/主客/赔率/身份) 中英双语交叉验证 → 6 免费 LLM 定性判断\n")
    lines.append("| 场次 | 比赛 | 综合方向 | 强度 | 比分偏好 | 官方隐含概率 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|")
    for mt in matches:
        odds = odds_map.get(f"{mt['home']}|{mt['away']}", [])
        if len(odds) >= 3:
            imp = f"主{1/odds[0]*100:.0f}%/平{1/odds[1]*100:.0f}%/客{1/odds[2]*100:.0f}%"
        else:
            imp = "-"
        note = "✅ 与官方一致" if mt["direction"] in ("主胜", "客胜") else "⚠️ 分歧"
        lines.append(f"| {mt['num']} | {mt['home']} vs {mt['away']} | "
                     f"**{mt['direction']}** ({mt['votes']}/{mt['total']}票) | "
                     f"{mt['strength']}% | {mt['score_pref']} | {imp} | {note} |")

    lines.append("\n## 各场模型明细\n")
    for mt in matches:
        lines.append(f"### {mt['num']} {mt['home']} vs {mt['away']} ({mt['league']})\n")
        for ind in mt["individual"]:
            lines.append(f"- **{ind['model']}**: {ind['dir']} — {ind['reasoning']}")
        lines.append("")
    return "\n".join(lines)


def build_excel(matches, raw_path, out_path):
    """生成 Excel 报告。"""
    with open(raw_path, encoding="utf-8") as f:
        data = json.load(f)
    odds_map = {}
    for m in data["matches"]:
        odds_map[f"{m['home']}|{m['away']}"] = m.get("model_odds") or []

    wb = Workbook()
    ws = wb.active
    ws.title = "综合预测"
    headers = ["场次", "比赛", "联赛", "开球时间", "综合方向", "得票",
               "强度", "比分偏好", "官方胜平负", "官方隐含", "备注"]
    ws.append(headers)
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = CENTER
        c.border = BORDER

    for mt in matches:
        odds = odds_map.get(f"{mt['home']}|{mt['away']}", [])
        if len(odds) >= 3:
            imp = f"主{1/odds[0]*100:.0f}% 平{1/odds[1]*100:.0f}% 客{1/odds[2]*100:.0f}%"
            od = f"{odds[0]}/{odds[1]}/{odds[2]}"
        else:
            imp, od = "-", "-"
        agree = "✅ 与官方一致" if mt["direction"] in ("主胜", "客胜") else "⚠️ 分歧"
        row = [mt["num"], f"{mt['home']} vs {mt['away']}", mt["league"],
               mt["kickoff"], mt["direction"], f"{mt['votes']}/{mt['total']}",
               f"{mt['strength']}%", mt["score_pref"], od, imp, agree]
        ws.append(row)
        for c in ws[ws.max_row]:
            c.font = BODY_FONT
            c.alignment = CENTER
            c.border = BORDER

    # 明细 sheet
    ws2 = wb.create_sheet("模型明细")
    ws2.append(["场次", "模型", "判断", "理由"])
    for c in ws2[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = CENTER
        c.border = BORDER
    for mt in matches:
        for ind in mt["individual"]:
            ws2.append([mt["num"], ind["model"], ind["dir"], ind["reasoning"]])
            for c in ws2[ws2.max_row]:
                c.font = BODY_FONT
                c.alignment = LEFT
                c.border = BORDER

    # 列宽
    widths = [10, 26, 12, 16, 12, 12, 8, 12, 18, 24, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws2.column_dimensions["A"].width = 10
    ws2.column_dimensions["B"].width = 24
    ws2.column_dimensions["C"].width = 22
    ws2.column_dimensions["D"].width = 70

    wb.save(out_path)
    return out_path


def main():
    report = sys.argv[1] if len(sys.argv) > 1 else "data/predictions_2026-08-05.txt"
    raw = sys.argv[2] if len(sys.argv) > 2 else "data/raw_2026-08-05.json"
    md_out = sys.argv[3] if len(sys.argv) > 3 else "data/预测报告_2026-08-05.md"
    xlsx_out = sys.argv[4] if len(sys.argv) > 4 else "data/预测报告_2026-08-05.xlsx"

    matches = parse_report(report)
    if not matches:
        print("❌ 解析失败, 无比赛数据")
        return
    print(f"✅ 解析到 {len(matches)} 场比赛")

    md = build_markdown(matches, raw)
    with open(md_out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✅ Markdown: {md_out}")

    build_excel(matches, raw, xlsx_out)
    print(f"✅ Excel: {xlsx_out}")


if __name__ == "__main__":
    main()

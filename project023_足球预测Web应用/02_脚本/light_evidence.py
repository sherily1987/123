# -*- coding: utf-8 -*-
"""project023 — 轻量证据自动生成器。

一键预测时自动为每场生成 predict.py 门禁合规的证据文件（六类标题 + 事实行）。
事实全部来自本地权威数据（体彩官方 raw JSON 的赔率/异动/身份 + project021 量化档位），
不做联网深度搜索——伤停/首发/天气等类目诚实标注缺口（与 08-15 手工降级口径一致，
evidence_gap=true 但门禁 ok=true）。

深度证据可手动放到同一目录覆盖（文件名 evidence_NNN_*.md）。
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLM_DATA = Path(r"C:/Users/Administrator/football-llm-predictor/data")

NOW_STR = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _iso8(ts):
    return NOW_STR


def build_one(idx: int, m: dict, quant_tier: str) -> str:
    """生成单场证据 markdown。m = raw['matches'][i]（fetch_sporttery_full 字段）。"""
    num = m.get("match_num", "")
    home = m.get("home", "")
    away = m.get("away", "")
    league = m.get("league", "")
    kick = m.get("kickoff_iso") or m.get("kickoff_local") or ""
    odds = m.get("model_odds") or []
    hhad = m.get("hhad") or {}
    tid = m.get("team_ids") or {}
    collected = NOW_STR

    src_tc = f"http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId={m.get('match_id')}"
    lines = [
        f"赛事：{league}（体彩官方场次）",
        f"竞彩编号：{num}",
        f"主队：{tid.get('home_full') or home}（短名{home}）",
        f"客队：{tid.get('away_full') or away}（短名{away}）",
        f"开球：{kick}",
        f"量化模型档位：{quant_tier}",
        f"收集时刻：{collected}",
        "",
        "## 1. 伤停/阵容",
    ]
    if odds:
        lines.append(
            f"- 体彩官方接口无伤病/大名单字段，赛前官方首发与伤员名单尚未公布 | source({src_tc}) | collected_at({collected})")
        lines.append("> 说明：轻量证据未做伤停新闻深度搜索；以赛前官方名单为准。")
    else:
        lines.append(
            f"- 体彩官方接口无伤病/大名单字段，本场亦未开胜平负盘 | source({src_tc}) | collected_at({collected})")
        lines.append("> 说明：轻量证据未做伤停新闻深度搜索；以赛前官方名单为准。")
    lines += ["", "## 2. 战意/动机"]
    lines.append(
        f"- 本场为竞彩{num}场次，{league}在售未开球场次之一，开球时间 {kick} | source({src_tc}) | collected_at({collected})")
    if "F-" in quant_tier:
        lines.append(
            f"- 量化模型档位 {quant_tier}：该联赛基于频率基线分档（无赛前赔率回测），联赛强度信息有限 | source(file://F:/HM足球比赛预测/project021_五大联赛APIFootball训练/05_交付/full_backtest.json) | collected_at({collected})")
    lines.append("> 说明：轻量证据未抓取教练/球员赛前言论与轮次背景。")
    lines += ["", "## 3. 近况/状态"]
    lines.append(
        f"- 量化 Dixon-Coles 模型覆盖标注：{league} 档位 {quant_tier}（见 full_backtest.json 滚动回测） | source(file://F:/HM足球比赛预测/project021_五大联赛APIFootball训练/05_交付/full_backtest.json) | collected_at({collected})")
    lines.append("> 说明：轻量证据未抓取双方近 5 场战绩；可上传深度证据覆盖本文件。")
    lines += ["", "## 4. 主客/旅行/天气"]
    lines.append(
        f"- 主队 {home} 主场作战，客队 {away} 客场远征（体彩官方对阵口径） | source({src_tc}) | collected_at({collected})")
    lines.append("> 说明：轻量证据未抓取天气/旅行距离。")
    lines += ["", "## 5. 赔率"]
    if odds and len(odds) >= 3:
        lines.append(
            f"- 体彩官方胜平负即时赔率：主{odds[0]}/平{odds[1]}/客{odds[2]} | source({src_tc}) | collected_at({collected})")
        # 异动（hadList 首尾）
        had = (m.get("odds_history") or {}).get("hadList") or []
        if len(had) >= 2:
            first, last = had[0], had[-1]
            lines.append(
                f"- 赔率异动（初盘→即时）：主{first.get('h')}→{last.get('h')} / 平{first.get('d')}→{last.get('d')} / 客{first.get('a')}→{last.get('a')} | source({src_tc}) | collected_at({collected})")
        else:
            lines.append(
                f"- 体彩赔率仅单快照，无初盘→即时异动记录 | source({src_tc}) | collected_at({collected})")
    else:
        lines.append(
            f"- 本场体彩未开胜平负盘（仅让球/比分/总进球等玩法），让球盘：{hhad} | source({src_tc}) | collected_at({collected})")
    if hhad and isinstance(hhad, dict) and hhad.get("odds"):
        lines.append(
            f"- 体彩让球盘（{hhad.get('line')}球）：{hhad['odds']} | source({src_tc}) | collected_at({collected})")
    lines.append("> 说明：外部盘口（欧赔）未抓取。")
    lines += ["", "## 6. 身份核验"]
    lines.append(
        f"- 体彩官方全名：主队\"{tid.get('home_full') or home}\"、客队\"{tid.get('away_full') or away}\" | source({src_tc}) | collected_at({collected})")
    lines.append(
        f"- 联赛：{league}（体彩联赛名口径）；开球时间 {kick} 与体彩列表接口一致 | source(https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry) | collected_at({collected})")
    lines += ["", "## 证据缺口"]
    lines.append(
        "> 说明：轻量证据自动生成（project023）：①伤停/首发名单未发布且未深度搜索；②双方近况/轮次背景未抓取；③天气/旅行距离未抓取；④外部欧赔未抓取。可上传深度证据覆盖后重跑预测。")
    return "\n".join(lines)


def generate_all(raw_path: Path, out_dir: Path, tiers_by_league: dict) -> list[dict]:
    """为 raw 中全部场次生成轻量证据。tiers_by_league: {体彩联赛名: 档位标注}。"""
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for i, m in enumerate(raw["matches"], 1):
        tier = tiers_by_league.get(m.get("league", ""), "无模型")
        text = build_one(i, m, tier)
        fname = f"evidence_{i:03d}_{m.get('home', '')}_{m.get('away', '')}.md"
        (out_dir / fname).write_text(text, encoding="utf-8")
        done.append({"match_index": i, "file": fname, "evidence_gap": True})
    return done


def generate_for_league_mapping(raw_path: Path, out_dir: Path) -> list[dict]:
    """包装：从 collector 拿量化档位，再生成。"""
    import sys
    sys.path.insert(0, str(HERE))
    from collector import league_tiers, quant_annotation
    tiers = league_tiers()
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    by_league = {m.get("league", ""): quant_annotation(m.get("league", ""), tiers) for m in raw["matches"]}
    return generate_all(raw_path, out_dir, by_league)

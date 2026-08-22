#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集默认：只把真实 API/网页快照写入证据；缺失就记录缺口。

标准全文见 EVIDENCE_COLLECT.md。
计票写入 data/vote_packs/sporttery-<id>.json。
runner.prepare_llm_evidence 调用 evidence_vote.apply_pack_file 套进第 1 / 3 节。
"""
from __future__ import annotations

import evidence_vote as evote
import league_form_sources as lfs

LINEUP_POLICY = "首发只接受带身份、来源和采集时间的真实页面/API快照；未发布就标记 UNAVAILABLE。"
INJURY_POLICY = (
    "伤停只接受带身份、来源和采集时间的真实页面/API快照；无法核验就标记 UNAVAILABLE。"
)
FORM_POLICY = (
    "近5场必须来自可核验的正式比赛页面/API快照，逐场保留日期、对手、比分和来源；"
    "找不到就记录 FORM_UNAVAILABLE，不得用投票或常识补齐。"
)


def lineup_lines(collected_at: str, source: str = "policy://two-media-xi",
                 league: str = "") -> list[str]:
    lines = [
        f"> 采集规则：{LINEUP_POLICY}",
        f"> 采集规则：{INJURY_POLICY}",
        f"> 采集规则：{evote.COLLECT_RULES}",
    ]
    lines.append("> 说明：以上仅为采集规则，不是本场事实；必须由真实快照替换，不能直接喂给模型作为首发/伤停。")
    return lines


def form_lines(league: str, collected_at: str, season_start: int = 2026) -> list[str]:
    spec = lfs.sources_for(league, season_start=season_start)
    src = spec["urls"][0] if spec.get("urls") else "policy://last-5-official"
    lines = [
        f"> 采集规则：{FORM_POLICY} 本场联赛「{league or '未标注'}」检索入口如下。候选入口：{src}",
    ]
    for url in spec.get("urls") or []:
        lines.append(
        f"> 近5场候选来源（待抓取并核验）：{url}"
        )
    blocked = "、".join(spec.get("blocked") or [])
    if blocked:
        lines.append(
            f"> 近5场封锁源不采：{blocked}"
        )
    lines.append(
        "> 说明：候选 URL 不是事实；只有通过快照身份、时间和关键词门禁的页面内容才能进入证据。"
    )
    return lines

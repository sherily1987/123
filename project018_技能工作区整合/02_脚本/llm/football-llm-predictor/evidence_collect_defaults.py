#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集默认：以后每场都按 20 源投票采首发 / 伤停 / 近 5 场。不等官方。

标准全文见 EVIDENCE_COLLECT.md。
计票写入 data/vote_packs/sporttery-<id>.json。
runner.prepare_llm_evidence 调用 evidence_vote.apply_pack_file 套进第 1 / 3 节。
"""
from __future__ import annotations

import evidence_vote as evote
import league_form_sources as lfs

LINEUP_POLICY = (
    "不再等俱乐部官宣。20个独立主机投票，得票最高的名单直接当可用首发。"
    "两个独立媒体对同一位置一致即可写入；平票取票多一侧。不得因官方未出整维弃权。"
)
INJURY_POLICY = (
    "伤停不再等俱乐部或官方名单。20个独立主机投票，得票最高的缺阵名单直接当可用伤停。"
    "至少两家写同一人缺阵即写入；平票取票多一侧。空表/fully fit 票数低于点名缺阵则不采用。"
)
FORM_POLICY = (
    "近5场不再等官方联赛页逐场核验。20个独立主机投票，得票最高的最近最多5场"
    "正式赛果直接当近5场。揭幕战/该队本季第一场取对其他对手的上季或最近正式赛，"
    "不得当「无近5场」。热身票数低于正式赛则不采用。"
)


def lineup_lines(collected_at: str, source: str = "policy://two-media-xi",
                 league: str = "") -> list[str]:
    lines = [
        f"- {LINEUP_POLICY} | source({source}) | collected_at({collected_at})",
        f"- {INJURY_POLICY} | source({source}) | collected_at({collected_at})",
        f"- {evote.COLLECT_RULES} | source({source}) | collected_at({collected_at})",
    ]
    lines.extend(evote.slot_stub_lines(league, collected_at))
    lines.append("> 说明：投票结果就是可用首发和可用伤停，不再等官方名单。20 槽待采必须按 EVIDENCE_COLLECT.md 填完再计票。")
    return lines


def form_lines(league: str, collected_at: str, season_start: int = 2026) -> list[str]:
    spec = lfs.sources_for(league, season_start=season_start)
    src = spec["urls"][0] if spec.get("urls") else "policy://last-5-official"
    lines = [
        f"- {FORM_POLICY} 本场联赛「{league or '未标注'}」检索入口如下。 | source({src}) | collected_at({collected_at})",
    ]
    for url in spec.get("urls") or []:
        lines.append(
            f"- 近5场源：{url} | source({url}) | collected_at({collected_at})"
        )
    blocked = "、".join(spec.get("blocked") or [])
    if blocked:
        lines.append(
            f"- 近5场封锁源不采：{blocked} | source({src}) | collected_at({collected_at})"
        )
    lines.append(
        "> 说明：得票最高的近5场直接当近况，不得把整维近况标不可用。"
    )
    return lines

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史投票包兼容层。

标准全文：EVIDENCE_COLLECT.md
  1) new_pack() 开 20 槽空包 → data/vote_packs/sporttery-<id>.json
  2) 填源、计票后 save_pack()
  3) apply_pack_file() 写入证据第 1 / 3 节
  4) runner.prepare_llm_evidence 自动套包
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK_DIR = Path(os.environ.get("FOOTBALL_VOTE_PACK_DIR") or (HERE / "data" / "vote_packs"))

# 以后每场都用这 20 个独立主机槽。末位按联赛换成官方站。封锁源只占槽、不采正文。
DEFAULT_SLOTS = [
    "sportsmole.co.uk",
    "fotmob.com",
    "flashscore.com",
    "espn.com",
    "skysports.com",
    "transfermarkt.com",
    "sportsgambler.com",
    "footballwhispers.com",
    "livescore.com",
    "squawka.com",
    "predictz.com",
    "understat.com",
    "mightytips.com",
    "soccervital.com",
    "en.wikipedia.org",
    "besoccer.com",
    "sofascore.com",
    "whoscored.com",
]
LALIGA_SLOTS = DEFAULT_SLOTS + ["estadiodeportivo.com", "laliga.com"]

# 第 19–20 槽：地区媒体 + 联赛官网。未列入的联赛用维基占第 20 槽。
LEAGUE_TAIL = {
    "西甲": ("estadiodeportivo.com", "laliga.com"),
    "La Liga": ("estadiodeportivo.com", "laliga.com"),
    "La_liga": ("estadiodeportivo.com", "laliga.com"),
    "英超": ("bbc.co.uk", "premierleague.com"),
    "英冠": ("bbc.co.uk", "efl.com"),
    "德甲": ("kicker.de", "bundesliga.com"),
    "意甲": ("gazzetta.it", "legaseriea.it"),
    "法甲": ("lequipe.fr", "ligue1.com"),
    "荷甲": ("vi.nl", "eredivisie.eu"),
}

BLOCKED = frozenset({"besoccer.com", "whoscored.com", "forebet.com", "fbref.com"})

# 采集硬规则。改这里等于改以后所有场次。
COLLECT_RULES = (
    "历史投票包仅作待采任务清单，不是事实来源。首发、伤停和近5场必须来自"
    "可审计的 API/网页快照；页面身份、来源、采集时间和开球前门禁全部通过后才能写入。"
    "验证码、403、重定向到其他域名或缺少关键词都记为缺口，不绕过。"
)


def pack_path(match_id) -> Path:
    mid = str(match_id).replace("sporttery-", "")
    return PACK_DIR / f"sporttery-{mid}.json"


def load_pack(match_id) -> dict | None:
    path = pack_path(match_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_pack(pack: dict) -> Path:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    mid = pack.get("match_id")
    path = pack_path(mid)
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def tally(ballots: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(ballots.items(), key=lambda kv: (-kv[1], kv[0]))


def pick(ballots: dict[str, int], *, min_votes: int = 2) -> str | None:
    ranked = tally(ballots)
    if not ranked or ranked[0][1] < min_votes:
        return None
    return ranked[0][0]


def render_source_lines(pack: dict) -> list[str]:
    """20 槽逐源事实行。封锁源只占槽。"""
    at = pack.get("collected_at") or ""
    lines = []
    for i, item in enumerate(pack.get("sources") or [], 1):
        host = item.get("host") or ""
        note = item.get("note") or ""
        url = item.get("url") or "policy://vote-20"
        lines.append(f"- 源{i} {host}：{note} | source({url}) | collected_at({at})")
    return lines


def render_voted_facts(pack: dict) -> tuple[list[str], list[str]]:
    """Return verified facts only; legacy vote fields are deliberately ignored."""
    verified = pack.get("verified_facts")
    if not isinstance(verified, list) or not verified:
        return [], []
    at = pack.get("collected_at") or ""
    sec1, sec3 = [], []
    for fact in verified:
        if not isinstance(fact, dict) or fact.get("section") not in (1, 3):
            continue
        source = fact.get("source") or pack.get("canonical_source") or ""
        collected = fact.get("collected_at") or at
        line = f"- {fact.get('text', '').strip()} | source({source}) | collected_at({collected})"
        (sec1 if fact.get("section") == 1 else sec3).append(line)
    return sec1, sec3


def _strip_old_vote_lines(section: str, verified: list[dict] | None = None) -> str:
    verified_texts = {str(item.get("text", "")).strip() for item in (verified or []) if isinstance(item, dict)}
    keep = []
    for line in section.splitlines():
        if line.startswith("- 二十源整合") or line.startswith("- 源"):
            continue
        if "近5场（新到旧，投票结果）" in line:
            continue
        if any(text and text in line for text in verified_texts):
            continue
        keep.append(line)
    return "\n".join(keep).rstrip()


def merge_into_evidence(text: str, pack: dict) -> str:
    """Insert voted facts after each section heading. Idempotent."""
    sec1, sec3 = render_voted_facts(pack)
    if not sec1 and not sec3:
        return text
    parts = re.split(r"(?=^## )", text or "", flags=re.M)
    out = []
    for part in parts:
        if part.startswith("## 1."):
            body = _strip_old_vote_lines(part, pack.get("verified_facts"))
            head, _, rest = body.partition("\n")
            part = head + "\n" + "\n".join(sec1) + (("\n" + rest.lstrip("\n")) if rest else "")
        elif part.startswith("## 3."):
            body = _strip_old_vote_lines(part, pack.get("verified_facts"))
            head, _, rest = body.partition("\n")
            part = head + "\n" + "\n".join(sec3) + (("\n" + rest.lstrip("\n")) if rest else "")
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        if part and not part.endswith("\n"):
            part += "\n"
        out.append(part)
    return "".join(out)


def apply_pack_file(text: str, match_id) -> str:
    pack = load_pack(match_id)
    if not pack:
        return text
    return merge_into_evidence(text, pack)


def apply_to_path(path: Path, match_id) -> bool:
    """把投票包写进已有证据文件。无包或无文件则 False。"""
    p = Path(path)
    if not p.is_file():
        return False
    raw = p.read_text(encoding="utf-8")
    merged = apply_pack_file(raw, match_id)
    if merged == raw:
        return False
    p.write_text(merged, encoding="utf-8")
    return True


def slot_hosts(league: str) -> list[str]:
    """任何联赛都是 20 槽。地区媒体和官网只换最后两槽。"""
    tail = LEAGUE_TAIL.get(str(league or "").strip(), ("en.wikipedia.org", "en.wikipedia.org"))
    slots = list(DEFAULT_SLOTS)
    for host in tail:
        if host not in slots:
            slots.append(host)
    # 维基已在 CORE 里时补一个通用预览站，保证仍是 20 个不同主机。
    extras = ("onefootball.com", "aiscore.com", "soccerway.com")
    i = 0
    while len(slots) < 20 and i < len(extras):
        if extras[i] not in slots:
            slots.append(extras[i])
        i += 1
    return slots[:20]


def skeleton_sources(league: str) -> list[dict]:
    out = []
    for host in slot_hosts(league):
        note = "封锁源占槽、不采正文" if host in BLOCKED else "待采"
        out.append({"host": host, "note": note, "url": f"https://{host}/"})
    return out


def new_pack(*, match_id, home: str, away: str, league: str, collected_at: str,
             canonical_source: str = "policy://vote-20") -> dict:
    """开一场新票的空包。采的人按槽填 note，再 save_pack。"""
    return {
        "match_id": match_id,
        "home": home,
        "away": away,
        "league": league,
        "collected_at": collected_at,
        "canonical_source": canonical_source,
        "home_xi": {"formation": "", "line": "", "tally": ""},
        "away_xi": {"formation": "", "line": "", "tally": ""},
        "injury_line": "",
        "home_form_line": "",
        "away_form_line": "",
        "sources": skeleton_sources(league),
    }


def slot_stub_lines(league: str, collected_at: str) -> list[str]:
    """轻量证据里先写出 20 槽，提醒深采必须填。"""
    pack = {"collected_at": collected_at, "sources": skeleton_sources(league)}
    return render_source_lines(pack)

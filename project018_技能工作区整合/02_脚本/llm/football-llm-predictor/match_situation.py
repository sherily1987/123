# -*- coding: utf-8 -*-
"""
MatchSituation — 足球比赛分析态势模型（最小可运行版）

定位（先搞清概念）:
  态势 ≠ 再算一个胜平负。
  态势 = 把一场球的「局面 / 驱动因素 / 不确定度」结构化，
        再给出动作: single(单选对照) / dual(双选) / observe(仅观察)。

六维:
  form    近况/状态
  lineup  伤停/阵容/首发
  motive  战意/动机
  market  赔率/市场
  env     主客/旅行/天气
  id      身份核验（并入 env 叙述，单独记 flags）

输入（按存在自动用）:
  --evidence-dir  evidence_*.md
  --model-output  量化 fusion model_output.json
  --llm-report    LLM 预测报告 md
  --dual-json     双轨四玩法对照 json（优先）
  --raw           体彩 raw（补编号/开球）

输出:
  situations.json + 态势报告.md

用法:
  python match_situation.py \\
    --evidence-dir data/evidence_2026-08-08 \\
    --model-output "F:/HM足球比赛预测/今日推荐_20260808/model_output.json" \\
    --llm-report data/预测报告_2026-08-08.md \\
    --dual-json "F:/HM足球比赛预测/今日推荐_双轨4玩法_20260808/dual_track_4markets.json" \\
    --out-dir data/situation_2026-08-08
"""
from __future__ import annotations

import argparse
import io
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SIDE_HOME = "home"
SIDE_AWAY = "away"
SIDE_NEUTRAL = "neutral"
SIDE_UNKNOWN = "unknown"

ACTION_SINGLE = "single"
ACTION_DUAL = "dual"
ACTION_OBSERVE = "observe"

DIMS = ("form", "lineup", "motive", "market", "env", "uncertainty")


# ---------------- I/O helpers ----------------

def _read_json(path: Path) -> Any:
    return json.loads(io.open(path, encoding="utf-8-sig").read())


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _norm_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    for a, b in [("·", ""), ("・", ""), (" ", "")]:
        s = s.replace(a, b)
    return s


def _match_key(home: str, away: str) -> str:
    return f"{_norm_name(home)}|{_norm_name(away)}"


# ---------------- evidence parse ----------------

SECTION_MAP = {
    "1": "lineup",
    "伤停": "lineup",
    "阵容": "lineup",
    "首发": "lineup",
    "2": "motive",
    "战意": "motive",
    "动机": "motive",
    "3": "form",
    "近况": "form",
    "状态": "form",
    "4": "env",
    "主客": "env",
    "旅行": "env",
    "天气": "env",
    "5": "market",
    "赔率": "market",
    "6": "identity",
    "身份": "identity",
    "缺口": "gaps",
    "证据缺口": "gaps",
}


def parse_evidence_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = {
        "path": str(path),
        "file": path.name,
        "home": "",
        "away": "",
        "league": "",
        "match_num": "",
        "kickoff": "",
        "sections": {k: [] for k in ("lineup", "motive", "form", "env", "market", "identity", "gaps", "other")},
        "raw_head": text[:200],
    }
    m = re.search(r"证据[:：]\s*(.+?)\s+vs\s+(.+?)\s*[\(（](.+?)[\)）]", text)
    if m:
        meta["home"], meta["away"], meta["league"] = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    m = re.search(r"体彩编号\s*(周[一二三四五六日]\d{3})", text)
    if not m:
        m = re.search(r"(周[一二三四五六日]\d{3})", text)
    if m:
        meta["match_num"] = m.group(1)
    m = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", text)
    if m:
        meta["kickoff"] = m.group(1)

    # from filename evidence_001_home_away.md
    fm = re.match(r"evidence_(\d+)_(.+)_(.+?)(?:_mcp)?\.md$", path.name)
    if fm and not meta["home"]:
        meta["home"] = fm.group(2).replace("_", "")
        meta["away"] = fm.group(3).replace("_", "")

    cur = "other"
    for line in text.splitlines():
        hs = re.match(r"^#{1,3}\s*(.+)$", line.strip())
        if hs:
            title = hs.group(1)
            cur = "other"
            for k, dim in SECTION_MAP.items():
                if k in title:
                    cur = dim
                    break
            if "缺口" in title:
                cur = "gaps"
            continue
        if line.strip().startswith("-") or line.strip().startswith("*"):
            meta["sections"].setdefault(cur, []).append(line.strip().lstrip("-* ").strip())
    return meta


def _sec_text(ev: dict, dim: str) -> str:
    return " ".join(ev.get("sections", {}).get(dim) or [])


def _is_gap_text(t: str) -> bool:
    if not t:
        return True
    keys = ("未检索", "未拿到", "未完成", "未做", "缺口", "缺失", "暂无", "无法", "污染", "勿编造", "未交叉")
    return any(k in t for k in keys)


def _parse_had_odds(text: str) -> list[float] | None:
    # 主 1.9 / 平 3.28 / 客 3.35
    m = re.search(r"主\s*([0-9.]+)\s*/\s*平\s*([0-9.]+)\s*/\s*客\s*([0-9.]+)", text)
    if m:
        return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
    m = re.search(r"HAD[:：]?\s*([0-9.]+)\s*/\s*([0-9.]+)\s*/\s*([0-9.]+)", text)
    if m:
        return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
    return None


def _favorite_from_odds(odds: list[float] | None) -> str:
    if not odds or len(odds) < 3:
        return SIDE_UNKNOWN
    i = min(range(3), key=lambda k: odds[k])
    return [SIDE_HOME, SIDE_NEUTRAL, SIDE_AWAY][i]


def _side_from_keywords(text: str, home: str, away: str) -> str:
    """Very light heuristic: which side text favors."""
    if not text:
        return SIDE_UNKNOWN
    h = home[:2] if home else ""
    a = away[:2] if away else ""
    score_h = score_a = 0
    home_pos = ("主队", "主场", "主胜", home, h)
    away_pos = ("客队", "客胜", away, a)
    pos = ("强势", "连胜", "齐整", "齐全", "升班马战意", "卫冕", "争冠")
    neg = ("伤缺", "缺阵", "停赛", "大面积伤", "客场不利", "轮换", "崩盘", "惨败")
    for p in home_pos:
        if p and p in text:
            score_h += 1
    for p in away_pos:
        if p and p in text:
            score_a += 1
    # missing count signal from lineups block
    mh = re.search(r"缺阵人数\s*主\s*(\d+)\s*/\s*客\s*(\d+)", text)
    if mh:
        hm, am = int(mh.group(1)), int(mh.group(2))
        if hm - am >= 2:
            score_a += 2
        elif am - hm >= 2:
            score_h += 2
    if "主队缺阵明显多于客队" in text:
        score_a += 2
    if "客队缺阵明显多于主队" in text:
        score_h += 2
    for p in pos:
        if p in text:
            # attribute to nearer side mention - crude
            if text.find(p) > 0:
                window = text[max(0, text.find(p) - 20) : text.find(p) + 20]
                if any(x and x in window for x in home_pos):
                    score_h += 1
                if any(x and x in window for x in away_pos):
                    score_a += 1
    for n in neg:
        if n in text:
            window = text[max(0, text.find(n) - 24) : text.find(n) + 24]
            if any(x and x in window for x in home_pos):
                score_h -= 1
            if any(x and x in window for x in away_pos):
                score_a -= 1
    if score_h - score_a >= 2:
        return SIDE_HOME
    if score_a - score_h >= 2:
        return SIDE_AWAY
    if score_h == 0 and score_a == 0:
        return SIDE_UNKNOWN if _is_gap_text(text) else SIDE_NEUTRAL
    return SIDE_NEUTRAL


def score_dimensions(ev: dict) -> dict:
    home, away = ev.get("home") or "", ev.get("away") or ""
    dims = {}

    # lineup
    t = _sec_text(ev, "lineup")
    gap = _is_gap_text(t)
    has_xi = "首发(" in t or "starting" in t.lower() or "get_lineups" in t
    side = _side_from_keywords(t, home, away)
    if gap and not has_xi:
        dims["lineup"] = {"side": SIDE_UNKNOWN, "grade": 0, "notes": ["伤停/首发证据不足"], "gap": True}
    else:
        note = "有首发/缺阵结构化" if has_xi else "有阵容叙述"
        dims["lineup"] = {"side": side, "grade": 2 if has_xi else 1, "notes": [note], "gap": False}

    # form
    t = _sec_text(ev, "form")
    gap = _is_gap_text(t)
    dims["form"] = {
        "side": SIDE_UNKNOWN if gap else _side_from_keywords(t, home, away),
        "grade": 0 if gap else 1,
        "notes": ["近况缺口"] if gap else ["近况有叙述"],
        "gap": gap,
    }

    # motive
    t = _sec_text(ev, "motive")
    gap = _is_gap_text(t) and "联赛" not in t
    side = _side_from_keywords(t, home, away)
    special = []
    if any(k in t for k in ("首回合", "次回合", "净胜", "两回合", "资格赛")):
        special.append("两回合/资格赛动机复杂")
    if any(k in t for k in ("升班", "升级", "保级", "卫冕", "揭幕")):
        special.append("赛季角色信号")
    dims["motive"] = {
        "side": SIDE_UNKNOWN if (gap and not special) else side,
        "grade": 0 if (gap and not special) else (2 if special else 1),
        "notes": special or (["战意缺口"] if gap else ["战意有叙述"]),
        "gap": gap and not special,
    }

    # market
    t = _sec_text(ev, "market")
    odds = _parse_had_odds(t)
    fav = _favorite_from_odds(odds)
    no_had = ("无 HAD" in t) or ("未开售胜平负" in t) or (odds is None and "HAD" not in t and "胜平负" not in t)
    if no_had and odds is None:
        dims["market"] = {"side": SIDE_UNKNOWN, "grade": 0, "notes": ["无可用 HAD"], "gap": True, "odds": None}
    else:
        notes = [f"市场倾向{'主' if fav==SIDE_HOME else ('客' if fav==SIDE_AWAY else '平/均衡')}"]
        if odds:
            notes.append(f"HAD {odds[0]}/{odds[1]}/{odds[2]}")
        # strength by odds gap
        grade = 1
        if odds:
            mx = sorted(odds)[0]
            if mx <= 1.45:
                grade = 2
                notes.append("盘口极热")
            elif mx >= 2.4:
                grade = 1
                notes.append("盘口偏均势")
        dims["market"] = {"side": fav, "grade": grade, "notes": notes, "gap": False, "odds": odds}

    # env
    t = _sec_text(ev, "env")
    gap = _is_gap_text(t) and "主场" not in t
    side = SIDE_HOME if ("主场" in t or "主队" in t) else (_side_from_keywords(t, home, away) if not gap else SIDE_UNKNOWN)
    if "主场" in t and not gap:
        side = SIDE_HOME  # default home edge mention
    env_notes = []
    if "主场" in t:
        env_notes.append("主场作战")
        side = SIDE_HOME
    if any(k in t for k in ("旅行", "客场长途", "时差", "人工草皮", "天气")):
        env_notes.append("含旅行/环境因子")
    if gap and not env_notes:
        env_notes.append("环境信息薄（默认主场身份）")
        side = SIDE_HOME
        gap = True
    dims["env"] = {
        "side": side if side != SIDE_UNKNOWN else SIDE_HOME,
        "grade": 0 if gap and not env_notes else 1,
        "notes": env_notes or ["环境中性"],
        "gap": gap and "主场" not in t,
    }

    # identity flags
    t = _sec_text(ev, "identity")
    id_ok = (not _is_gap_text(t)) or bool(t)
    id_warn = any(k in t for k in ("勿与", "混淆", "短名", "⚠️"))
    dims["identity"] = {
        "side": SIDE_NEUTRAL,
        "grade": 0 if id_warn else (1 if id_ok else 0),
        "notes": (["身份需警惕重名"] if id_warn else ["身份已核验或可追溯"]),
        "gap": bool(id_warn),
    }

    # uncertainty aggregate
    gaps = list(ev.get("sections", {}).get("gaps") or [])
    gap_n = sum(1 for d in ("lineup", "form", "motive") if dims[d].get("gap"))
    if gaps:
        gap_n += 1
    unc_grade = min(2, gap_n)  # higher = more uncertain
    dims["uncertainty"] = {
        "side": SIDE_NEUTRAL,
        "grade": unc_grade,  # 0 low, 2 high uncertainty
        "notes": [f"关键维缺口数≈{gap_n}"] + gaps[:3],
        "gap": gap_n >= 2,
        "gap_count": gap_n,
    }
    return dims


# ---------------- tracks ----------------

def load_quant(path: Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    data = _read_json(path)
    results = data.get("results") if isinstance(data, dict) else data
    out = {}
    for r in results or []:
        if not isinstance(r, dict):
            continue
        match = r.get("match")
        if isinstance(match, dict):
            home, away = match.get("home") or "", match.get("away") or ""
            mnum = match.get("match_num") or match.get("num") or ""
        else:
            # "A vs B"
            s = str(match or "")
            parts = re.split(r"\s+vs\s+", s, flags=re.I)
            home, away = (parts[0], parts[1]) if len(parts) == 2 else (s, "")
            mnum = ""
        co = r.get("core_output") or {}
        fd = r.get("fusion_decision") or {}
        gate = r.get("recommendation_gate") or {}
        final = co.get("final_1x2") or []
        primary = (fd.get("primary_outcome") or "").upper()
        dir_map = {"H": "主胜", "D": "平局", "A": "客胜"}
        direction = dir_map.get(primary)
        if not direction and len(final) == 3:
            direction = ["主胜", "平局", "客胜"][max(range(3), key=lambda i: final[i])]
        pct = None
        if len(final) == 3:
            pct = [round(float(x) * 100, 1) for x in final]
        key = _match_key(home, away)
        out[key] = {
            "home": home,
            "away": away,
            "match_num": mnum,
            "direction": direction,
            "pct": pct,
            "mode": (co.get("mode") or r.get("mode") or ""),
            "dependency": co.get("market_dependency_pct") or fd.get("market_dependency_pct"),
            "banker_allowed": bool(gate.get("banker_allowed")),
            "gate_reasons": gate.get("reasons") or [],
            "action_note": fd.get("action") or "",
        }
        if mnum:
            out[f"num:{mnum}"] = out[key]
    return out


def load_llm_report(path: Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    t = path.read_text(encoding="utf-8")
    out = {}
    for line in t.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 5:
            continue
        if not re.match(r"周[一二三四五六日]\d{3}", cols[0]):
            continue
        m = re.match(r"(.+?)\s+vs\s+(.+)", cols[1])
        if not m:
            continue
        dm = re.search(r"(主胜|平局|客胜)", cols[2])
        sm = re.search(r"(\d+)%", cols[3])
        score = cols[4].replace("**", "").strip()
        home, away = m.group(1).strip(), m.group(2).strip()
        item = {
            "match_num": cols[0],
            "home": home,
            "away": away,
            "direction": dm.group(1) if dm else "",
            "strength": int(sm.group(1)) if sm else None,
            "score_pref": score,
        }
        out[_match_key(home, away)] = item
        out[f"num:{cols[0]}"] = item
    return out


def load_dual(path: Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    data = _read_json(path)
    rows = data.get("rows") if isinstance(data, dict) else data
    out = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        home, away = r.get("home") or "", r.get("away") or ""
        key = _match_key(home, away)
        out[key] = r
        if r.get("match_num"):
            out[f"num:{r['match_num']}"] = r
    return out


def load_raw(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    data = _read_json(path)
    if isinstance(data, list):
        return data
    return data.get("matches") or data.get("results") or []


# ---------------- situation core ----------------

def _dir_to_side(d: str | None) -> str:
    if d in ("主胜", "H", "home"):
        return SIDE_HOME
    if d in ("客胜", "A", "away"):
        return SIDE_AWAY
    if d in ("平局", "D", "draw"):
        return SIDE_NEUTRAL
    return SIDE_UNKNOWN


def _side_label(side: str) -> str:
    return {
        SIDE_HOME: "偏主",
        SIDE_AWAY: "偏客",
        SIDE_NEUTRAL: "中性/均衡",
        SIDE_UNKNOWN: "未知",
    }.get(side, side)


def detect_conflicts(dims: dict, quant: dict | None, llm: dict | None) -> list[str]:
    conflicts = []
    # dim vs market
    mside = (dims.get("market") or {}).get("side")
    for name in ("form", "lineup", "motive"):
        s = (dims.get(name) or {}).get("side")
        if s in (SIDE_HOME, SIDE_AWAY) and mside in (SIDE_HOME, SIDE_AWAY) and s != mside:
            conflicts.append(f"{name}倾向{_side_label(s)} 与 market倾向{_side_label(mside)} 冲突")
    # quant vs llm
    if quant and llm:
        qd, ld = quant.get("direction"), llm.get("direction")
        if qd and ld and qd != ld:
            conflicts.append(f"双轨方向冲突: 量化={qd} vs LLM={ld}")
    # uncertainty
    if (dims.get("uncertainty") or {}).get("gap_count", 0) >= 2:
        conflicts.append("关键证据维缺口≥2，信息态势脆弱")
    if (dims.get("identity") or {}).get("gap"):
        conflicts.append("身份核验存疑")
    # two-leg
    for n in (dims.get("motive") or {}).get("notes") or []:
        if "两回合" in n or "资格赛" in n:
            conflicts.append("两回合/资格赛：首回合冷门风险升高")
    return conflicts


def decide_action(dims: dict, conflicts: list[str], quant: dict | None, llm: dict | None) -> tuple[str, list[str], str | None, str | None]:
    """
    Returns action, reasons, primary_dir, alt_dir
    Never sets banker.
    """
    reasons = []
    unc = (dims.get("uncertainty") or {}).get("gap_count", 0)
    mside = (dims.get("market") or {}).get("side", SIDE_UNKNOWN)
    qdir = (quant or {}).get("direction")
    ldir = (llm or {}).get("direction")
    lstr = (llm or {}).get("strength")

    primary = ldir or qdir
    alt = None

    # hard observe
    if (dims.get("market") or {}).get("gap") and unc >= 2:
        reasons.append("无HAD且证据薄 → 仅观察")
        return ACTION_OBSERVE, reasons, primary, None
    if any("身份核验存疑" in c for c in conflicts):
        reasons.append("身份存疑 → 仅观察")
        return ACTION_OBSERVE, reasons, primary, None

    # dual conditions
    need_dual = False
    if qdir and ldir and qdir != ldir:
        need_dual = True
        reasons.append("量化与LLM方向不一致 → 双选")
        primary, alt = qdir, ldir  # keep both; primary=quant as market anchor default
        # actually prefer market-aligned as primary
        if mside == _dir_to_side(ldir):
            primary, alt = ldir, qdir
        elif mside == _dir_to_side(qdir):
            primary, alt = qdir, ldir
    if lstr is not None and lstr < 60:
        need_dual = True
        reasons.append(f"LLM强度{lstr}%<60 → 强制双选")
    if unc >= 2:
        need_dual = True
        reasons.append("证据缺口多 → 双选或降级")
    if any("两回合" in c for c in conflicts):
        need_dual = True
        reasons.append("两回合/资格赛风险 → 倾向双选")
    if any("冲突" in c for c in conflicts):
        need_dual = True
        reasons.append("维度冲突 → 双选")

    # single only if agree + low unc + not special risk
    agree = bool(qdir and ldir and qdir == ldir) or (ldir and not qdir) or (qdir and not ldir)
    if agree and not need_dual and unc <= 1:
        # still avoid single on extreme thin evidence
        if (dims.get("lineup") or {}).get("gap") and (dims.get("form") or {}).get("gap"):
            reasons.append("阵容+近况皆缺，即使方向一致也只双选/观察")
            # pick alt as draw often
            primary = ldir or qdir
            alt = "平局" if primary != "平局" else "客胜"
            return ACTION_DUAL, reasons, primary, alt
        reasons.append("双轨一致且缺口可控 → 单选对照（非出胆）")
        return ACTION_SINGLE, reasons, primary, None

    if need_dual:
        if not alt:
            # synthesize alt: second best market or draw
            if primary == "主胜":
                alt = "平局"
            elif primary == "客胜":
                alt = "平局"
            else:
                alt = "主胜"
            reasons.append(f"自动补双选备选={alt}")
        return ACTION_DUAL, reasons, primary, alt

    reasons.append("默认仅观察")
    return ACTION_OBSERVE, reasons, primary, alt


def build_situation(
    ev: dict,
    quant_map: dict,
    llm_map: dict,
    dual_map: dict,
) -> dict:
    dims = score_dimensions(ev)
    home, away = ev.get("home") or "", ev.get("away") or ""
    mnum = ev.get("match_num") or ""
    key = _match_key(home, away)

    dual = dual_map.get(f"num:{mnum}") or dual_map.get(key)
    quant = quant_map.get(f"num:{mnum}") or quant_map.get(key)
    llm = llm_map.get(f"num:{mnum}") or llm_map.get(key)

    # enrich from dual if present
    if dual:
        q = dual.get("quant") or {}
        l = dual.get("llm") or {}
        if not quant and q:
            quant = {
                "direction": q.get("1x2"),
                "pct": q.get("1x2_pct"),
                "mode": q.get("mode"),
                "dependency": q.get("dependency"),
                "banker_allowed": q.get("banker"),
                "score": q.get("score"),
                "ou25": q.get("ou25"),
                "hafu": q.get("hafu"),
            }
        if not llm and l:
            llm = {
                "direction": l.get("1x2"),
                "score_pref": l.get("score"),
                "strength": None,
                "ou25": l.get("ou25"),
                "hafu": l.get("hafu"),
                "confidence": l.get("confidence"),
            }
        if not mnum:
            mnum = dual.get("match_num") or mnum

    conflicts = detect_conflicts(dims, quant, llm)
    action, reasons, primary, alt = decide_action(dims, conflicts, quant, llm)

    # lean summary from dims (non-market)
    lean_scores = Counter()
    for name in ("form", "lineup", "motive", "env"):
        s = (dims.get(name) or {}).get("side")
        g = (dims.get(name) or {}).get("grade") or 0
        if s == SIDE_HOME:
            lean_scores["home"] += g
        elif s == SIDE_AWAY:
            lean_scores["away"] += g
        elif s == SIDE_NEUTRAL:
            lean_scores["neutral"] += g
    if lean_scores:
        fund_side = lean_scores.most_common(1)[0][0]
    else:
        fund_side = "unknown"

    label = {
        "home": "基本面偏主",
        "away": "基本面偏客",
        "neutral": "基本面均衡",
        "unknown": "基本面不明",
    }[fund_side]
    if (dims.get("uncertainty") or {}).get("gap_count", 0) >= 2:
        label = "证据薄 / " + label
    if any("双轨方向冲突" in c for c in conflicts):
        label = "双轨分歧 / " + label

    return {
        "schema": "match_situation.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "match_num": mnum,
        "home": home,
        "away": away,
        "league": ev.get("league") or "",
        "kickoff": ev.get("kickoff") or "",
        "label": label,
        "dimensions": dims,
        "conflicts": conflicts,
        "fund_lean": fund_side,
        "tracks": {
            "quant": quant,
            "llm": llm,
        },
        "action": action,
        "primary_direction": primary,
        "alt_direction": alt,
        "action_reasons": reasons,
        "banker_allowed": False,
        "banker_note": "态势层永不直接出胆；出胆仅看量化 recommendation_gate.banker_allowed",
        "evidence_file": ev.get("file"),
    }


def render_report(situations: list[dict], title: str) -> str:
    lines = [
        f"# 比赛态势分析报告",
        f"",
        f"> {title}",
        f"> 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | schema: match_situation.v1",
        f"> 动作含义: **single**=单选对照(非出胆) / **dual**=双选 / **observe**=仅观察",
        f"",
        f"## 总览",
        f"",
        f"| 场次 | 对阵 | 态势标签 | 动作 | 主方向 | 备选 | 冲突数 |",
        f"|---|---|---|---|---|---|---:|",
    ]
    for s in situations:
        lines.append(
            f"| {s.get('match_num','')} | {s.get('home')} vs {s.get('away')} | {s.get('label')} | "
            f"**{s.get('action')}** | {s.get('primary_direction') or '-'} | {s.get('alt_direction') or '-'} | {len(s.get('conflicts') or [])} |"
        )

    # counts
    c = Counter(s.get("action") for s in situations)
    lines += [
        f"",
        f"- 动作分布: single={c.get(ACTION_SINGLE,0)} / dual={c.get(ACTION_DUAL,0)} / observe={c.get(ACTION_OBSERVE,0)}",
        f"- **全部 banker_allowed=false**（态势层不设胆）",
        f"",
        f"## 逐场",
        f"",
    ]
    for s in situations:
        lines.append(f"### {s.get('match_num','')} {s.get('home')} vs {s.get('away')} ({s.get('league','')})")
        lines.append(f"")
        lines.append(f"- **标签**: {s.get('label')}")
        lines.append(f"- **动作**: `{s.get('action')}` → 主方向 **{s.get('primary_direction') or '—'}**"
                     + (f" / 备选 **{s.get('alt_direction')}**" if s.get("alt_direction") else ""))
        lines.append(f"- 理由: " + "；".join(s.get("action_reasons") or []) )
        d = s.get("dimensions") or {}
        lines.append(f"- 六维:")
        for name in DIMS:
            dim = d.get(name) or {}
            if name == "uncertainty":
                lines.append(
                    f"  - `{name}`: 不确定度等级={dim.get('grade')} | "
                    + "；".join(dim.get("notes") or [])
                )
            else:
                lines.append(
                    f"  - `{name}`: {_side_label(dim.get('side', SIDE_UNKNOWN))} (grade={dim.get('grade')})"
                    + (" ⚠️gap" if dim.get("gap") else "")
                    + " | "
                    + "；".join(dim.get("notes") or [])
                )
        idim = d.get("identity") or {}
        if idim:
            lines.append(f"  - `identity`: " + "；".join(idim.get("notes") or []))
        if s.get("conflicts"):
            lines.append(f"- **冲突**:")
            for cfl in s["conflicts"]:
                lines.append(f"  - {cfl}")
        tr = s.get("tracks") or {}
        q, l = tr.get("quant"), tr.get("llm")
        if q:
            lines.append(f"- 量化: {q.get('direction')} pct={q.get('pct')} mode={q.get('mode')} dep={q.get('dependency')}")
        if l:
            lines.append(f"- LLM: {l.get('direction')} 强度={l.get('strength')} 比分={l.get('score_pref')}")
        lines.append("")
    lines += [
        f"## 使用说明",
        f"",
        f"1. 态势层是**风控与解释中间层**，不替代量化概率，不替代人工终审。",
        f"2. `single` 只表示「双轨一致可对照」，**不等于** `banker_allowed`。",
        f"3. 证据缺口多或双轨冲突时，优先 `dual`/`observe`。",
        f"4. 回测应切片: action类型 × 有无lineups × 冲突有无。",
        f"",
    ]
    return "\n".join(lines)


def collect_evidence(evidence_dir: Path) -> list[dict]:
    files = sorted(evidence_dir.glob("evidence_*.md"))
    # prefer non-_mcp if both; keep all unique by home-away from filename
    by_key = {}
    for f in files:
        if f.name.endswith("_mcp.md"):
            # mcp is supplementary — merge later
            continue
        ev = parse_evidence_md(f)
        by_key[_match_key(ev.get("home"), ev.get("away")) or f.name] = ev
    # merge mcp sections into matching
    for f in files:
        if not f.name.endswith("_mcp.md"):
            continue
        mcp = parse_evidence_md(f)
        key = _match_key(mcp.get("home"), mcp.get("away"))
        # try strip _mcp naming
        fm = re.match(r"evidence_\d+_(.+)_mcp\.md", f.name)
        if not key and fm:
            pass
        target = by_key.get(key)
        if not target:
            # attach by sequence number
            m = re.match(r"evidence_(\d+)_", f.name)
            if m:
                for k, ev in by_key.items():
                    if ev.get("file", "").startswith(f"evidence_{m.group(1)}_"):
                        target = ev
                        break
        if not target:
            by_key[key or f.name] = mcp
            continue
        # merge lineup-rich mcp into target
        for sec, lines in (mcp.get("sections") or {}).items():
            if not lines:
                continue
            target.setdefault("sections", {}).setdefault(sec, [])
            # prepend mcp structured lines if not duplicate
            for ln in lines:
                if ln not in target["sections"][sec]:
                    target["sections"][sec].insert(0, ln)
    return list(by_key.values())


def main():
    ap = argparse.ArgumentParser(description="MatchSituation 态势模型 v1")
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--model-output", default="")
    ap.add_argument("--llm-report", default="")
    ap.add_argument("--dual-json", default="")
    ap.add_argument("--raw", default="")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    ev_dir = Path(args.evidence_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    evidences = collect_evidence(ev_dir)
    quant_map = load_quant(Path(args.model_output) if args.model_output else None)
    llm_map = load_llm_report(Path(args.llm_report) if args.llm_report else None)
    dual_map = load_dual(Path(args.dual_json) if args.dual_json else None)

    # fill match_num from raw if missing
    raw = load_raw(Path(args.raw) if args.raw else None)
    raw_by_ha = {}
    for m in raw:
        h, a = m.get("home") or "", m.get("away") or ""
        raw_by_ha[_match_key(h, a)] = m

    situations = []
    for ev in evidences:
        key = _match_key(ev.get("home"), ev.get("away"))
        if not ev.get("match_num") and key in raw_by_ha:
            ev["match_num"] = raw_by_ha[key].get("match_num") or ""
            if not ev.get("kickoff"):
                ev["kickoff"] = raw_by_ha[key].get("kickoff_local") or ""
            if not ev.get("league"):
                ev["league"] = raw_by_ha[key].get("league") or ""
        situations.append(build_situation(ev, quant_map, llm_map, dual_map))

    # sort by match_num
    def sort_key(s):
        mn = s.get("match_num") or "周日999"
        return mn

    situations.sort(key=sort_key)

    payload = {
        "schema": "match_situation_batch.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(situations),
        "action_counts": dict(Counter(s["action"] for s in situations)),
        "note": "态势层不设胆；single仅对照",
        "situations": situations,
    }
    _write_json(out_dir / "situations.json", payload)
    report = render_report(situations, title=f"evidence={ev_dir.name} n={len(situations)}")
    (out_dir / "态势报告.md").write_text(report, encoding="utf-8")

    print(f"✅ situations: {len(situations)} -> {out_dir}")
    print(f"   actions: {payload['action_counts']}")
    for s in situations:
        print(
            f"  - {s.get('match_num')} {s.get('home')}vs{s.get('away')}: "
            f"{s.get('action')} {s.get('primary_direction')}/{s.get('alt_direction')} | {s.get('label')}"
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""体彩相对国际盘的中文凯利指数。只作 hybrid-shadow 研究特征。

G_i = 体彩赔率_i × 国际共识去水概率_i。
绝对水平几乎永远 < 1（体彩抽水更狠）；有信息的是三个方向的相对差。
不计算仓位，不进生产概率，不进推荐门控。校准状态固定 UNFITTED。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from odds_api_adapter import name_hits

DIRECTIONS = ("主胜", "平局", "客胜")
_STAKE_KEYS = ("kelly_fraction", "f_star", "f*", "stake", "recommended_stake")
_DRAW_NAMES = {"draw", "tie", "x", "平", "平局"}


def _skip(reason: str) -> dict[str, Any]:
    return {
        "research_only": True,
        "calibration": "UNFITTED",
        "status": "skipped",
        "reason": reason,
    }


def proportional_devig(odds: list[float]) -> list[float] | None:
    if len(odds) != 3 or any(not isinstance(o, (int, float)) or o <= 1.0 for o in odds):
        return None
    implied = [1.0 / float(o) for o in odds]
    total = sum(implied)
    if total <= 0:
        return None
    return [x / total for x in implied]


def _h2h_odds(bookmaker: dict, home_names: list[str], away_names: list[str]) -> list[float] | None:
    markets = bookmaker.get("markets") or []
    h2h = next((m for m in markets if m.get("key") == "h2h"), None)
    if not h2h:
        return None
    home_o = draw_o = away_o = None
    for outcome in h2h.get("outcomes") or []:
        name = str(outcome.get("name") or "")
        price = outcome.get("price")
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if name.lower() in _DRAW_NAMES:
            draw_o = price
        elif name_hits(name, home_names):
            home_o = price
        elif name_hits(name, away_names):
            away_o = price
    if None in (home_o, draw_o, away_o):
        return None
    return [home_o, draw_o, away_o]


def _names_from_intl_match(intl_match: str | None) -> tuple[str | None, str | None]:
    text = str(intl_match or "")
    if " vs " not in text.lower():
        return None, None
    # 保留原大小写；按不区分大小写的分隔符切
    idx = text.lower().find(" vs ")
    return text[:idx].strip() or None, text[idx + 4:].strip() or None


def consensus_from_bookmakers(
    bookmakers: list[dict],
    home_names: list[str],
    away_names: list[str],
) -> dict[str, Any]:
    parsed: list[dict[str, Any]] = []
    pinnacle = None
    for book in bookmakers or []:
        odds = _h2h_odds(book, home_names, away_names)
        if not odds:
            continue
        probs = proportional_devig(odds)
        if not probs:
            continue
        row = {
            "key": str(book.get("key") or "").lower(),
            "title": book.get("title"),
            "odds": odds,
            "probs": probs,
        }
        parsed.append(row)
        if row["key"] == "pinnacle":
            pinnacle = row
    if pinnacle:
        return {
            "probs": pinnacle["probs"],
            "source": "pinnacle",
            "n_books": 1,
            "intl_odds": pinnacle["odds"],
        }
    if not parsed:
        return {"error": "no_complete_h2h"}
    mean = [sum(row["probs"][i] for row in parsed) / len(parsed) for i in range(3)]
    total = sum(mean)
    return {
        "probs": [x / total for x in mean],
        "source": "equal_weight_mean",
        "n_books": len(parsed),
        "intl_odds": None,
    }


def chinese_kelly_index(
    sporttery_odds: list[float],
    intl_probs: list[float],
) -> dict[str, Any]:
    triple = [float(sporttery_odds[i]) * float(intl_probs[i]) for i in range(3)]
    labeled = {DIRECTIONS[i]: triple[i] for i in range(3)}
    ranked = sorted(triple)
    softest_i = max(range(3), key=lambda i: triple[i])
    return {
        "index": labeled,
        "gap_max_minus_mid": ranked[-1] - ranked[-2],
        "softest_direction": DIRECTIONS[softest_i],
    }


def _ledger_entry(payload: dict[str, Any], collected_at: str | None) -> dict[str, Any]:
    labeled = payload.get("index") or {}
    return {
        "field": "intl_kelly_index",
        "fact": (
            f"体彩相对国际盘凯利指数 "
            f"主{labeled.get('主胜', 0):.3f}/平{labeled.get('平局', 0):.3f}/"
            f"客{labeled.get('客胜', 0):.3f}，最松 {payload.get('softest_direction')}，"
            f"max-mid {payload.get('gap_max_minus_mid', 0):.3f}"
        ),
        "source": f"odds-intl/{payload.get('intl_source')}",
        "collected_at": collected_at,
        "mapped": {
            "index": labeled,
            "gap_max_minus_mid": payload.get("gap_max_minus_mid"),
            "softest_direction": payload.get("softest_direction"),
        },
        "basis": "G=sporttery_odd*intl_consensus_p；只作盘口形状特征，不是仓位",
        "backtested": False,
        "calibration": "UNFITTED",
    }


def audit_from_intl_row(
    sporttery_odds: list[float],
    intl_row: dict,
    *,
    home: str | None = None,
    away: str | None = None,
    match_id: str | None = None,
) -> dict[str, Any]:
    if not sporttery_odds or len(sporttery_odds) < 3:
        return _skip("sporttery_odds_missing")
    intl_home, intl_away = _names_from_intl_match(intl_row.get("intl_match"))
    home_names = [n for n in (home, intl_home) if n]
    away_names = [n for n in (away, intl_away) if n]
    consensus = consensus_from_bookmakers(
        intl_row.get("bookmakers") or [], home_names, away_names)
    if consensus.get("error"):
        return _skip(str(consensus["error"]))
    shape = chinese_kelly_index(list(sporttery_odds)[:3], consensus["probs"])
    collected_at = intl_row.get("last_update") or intl_row.get("commence_time")
    out = {
        "research_only": True,
        "calibration": "UNFITTED",
        "status": "ok",
        "match_id": match_id or intl_row.get("match_id"),
        "sporttery_odds": [float(x) for x in sporttery_odds[:3]],
        "intl_probs": {DIRECTIONS[i]: consensus["probs"][i] for i in range(3)},
        "intl_source": consensus["source"],
        "n_books": consensus["n_books"],
        "collected_at": collected_at,
        **shape,
    }
    out["ledger_entry"] = _ledger_entry(out, collected_at)
    return out


def load_latest_intl_row(store: Path, match_id: str) -> dict | None:
    path = Path(store)
    if not path.exists():
        return None
    found = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                batch = json.loads(line)
            except json.JSONDecodeError:
                continue
            for row in batch.get("matches") or []:
                if row.get("match_id") == match_id:
                    found = row
    return found


def intl_kelly_for_match(match: dict, store: Path | None) -> dict[str, Any]:
    """给一场体彩输入算研究侧车。缺国际盘时 skip，不抛错。"""
    odds = match.get("odds") or match.get("model_odds")
    meta = match.get("sporttery_meta") or {}
    raw_id = meta.get("match_id") or match.get("match_id")
    match_id = None
    if raw_id is not None:
        text = str(raw_id).strip()
        match_id = text if text.startswith("sporttery-") else f"sporttery-{text}"
    if store is None or match_id is None:
        return _skip("intl_odds_unavailable")
    row = load_latest_intl_row(store, match_id)
    if row is None:
        return _skip("intl_odds_unavailable")
    return audit_from_intl_row(
        list(odds or []),
        row,
        home=match.get("home"),
        away=match.get("away"),
        match_id=match_id,
    )


def assert_no_stake_fields(blob: Any) -> None:
    if isinstance(blob, dict):
        overlap = [k for k in _STAKE_KEYS if k in blob]
        if overlap:
            raise AssertionError(f"stake fields not allowed: {overlap}")
        for value in blob.values():
            assert_no_stake_fields(value)
    elif isinstance(blob, list):
        for value in blob:
            assert_no_stake_fields(value)

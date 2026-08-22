"""Deterministic settlement and evaluation for the LLM research track."""

from __future__ import annotations

from collections import Counter
from typing import Any

from llm_track_contract import normalize_match_id


def _score(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        home, away = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    return (home, away) if home >= 0 and away >= 0 else None


def _result(score: tuple[int, int]) -> str:
    if score[0] > score[1]:
        return "主胜"
    if score[0] < score[1]:
        return "客胜"
    return "平局"


def _hafu(half: tuple[int, int], full: tuple[int, int]) -> str:
    return f"{_result(half)}{_result(full)}"


def _direction(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in {"主胜", "平局", "客胜"}:
        return text
    if text in {"胜", "平", "负"}:
        return {"胜": "主胜", "平": "平局", "负": "客胜"}[text]
    return None


def _ou(value: Any) -> str | None:
    text = str(value or "").lower()
    if any(token in text for token in ("大", "over", "上")):
        return "大"
    if any(token in text for token in ("小", "under", "下")):
        return "小"
    return None


def settle_llm_records(records: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Join predictions to verified 90-minute results, excluding unsafe rows."""
    rows: list[dict[str, Any]] = []
    audit: Counter[str] = Counter()
    seen: set[str] = set()
    for record in records:
        match_id = normalize_match_id(record.get("match_id"))
        if match_id is None:
            audit["missing_match_id"] += 1
            continue
        if match_id in seen:
            audit["duplicate_match_id"] += 1
            continue
        seen.add(match_id)
        result = results.get(match_id) or results.get(match_id.removeprefix("sporttery-"))
        if not result:
            audit["missing_result"] += 1
            continue
        if str(result.get("score_90_status") or "").lower() not in {"verified", "valid", "verified_90"}:
            audit["score_90_not_verified"] += 1
            continue
        full = _score(result.get("score_90"))
        if full is None:
            audit["invalid_score_90"] += 1
            continue
        half = _score(result.get("half_score"))
        rows.append({
            "match_id": match_id,
            "predicted_direction": _direction(record.get("direction") or record.get("result")),
            "top_scores": list(record.get("top_scores") or record.get("top3_scores") or []),
            "predicted_ou25": _ou(record.get("top_ou25") or record.get("ou25")),
            "predicted_hafu": str(record.get("top_hafu") or record.get("hafu") or "") or None,
            "actual_score": list(full),
            "actual_result": _result(full),
            "actual_ou25": "大" if sum(full) >= 3 else "小",
            "actual_hafu": _hafu(half, full) if half is not None else None,
        })
    return {"rows": rows, "audit": dict(audit)}


def evaluate_llm_records(records: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Evaluate 1X2, draw, score, OU2.5 and HAFU independently."""
    settled = settle_llm_records(records, results)
    rows = settled["rows"]
    n = len(rows)
    direction_rows = [r for r in rows if r["predicted_direction"] is not None]
    direction_hits = sum(r["predicted_direction"] == r["actual_result"] for r in direction_rows)
    draw_actual = sum(r["actual_result"] == "平局" for r in rows)
    draw_predicted = sum(r["predicted_direction"] == "平局" for r in rows)
    draw_hits = sum(r["predicted_direction"] == r["actual_result"] == "平局" for r in rows)
    score_rows = [r for r in rows if r["top_scores"]]
    # Accept the common "1-1" representation without making score parsing a
    # second prediction engine.
    score_hits = sum(
        any(str(score) == f"{r['actual_score'][0]}-{r['actual_score'][1]}" for score in r["top_scores"])
        for r in score_rows
    )
    ou_rows = [r for r in rows if r["predicted_ou25"] is not None]
    hafu_rows = [r for r in rows if r["predicted_hafu"] and r["actual_hafu"]]
    pct = lambda hits, count: round(hits / count * 100, 3) if count else None
    return {
        "n": n,
        "audit": settled["audit"],
        "one_x_two": {"n": len(direction_rows), "hits": direction_hits,
                       "accuracy_pct": pct(direction_hits, len(direction_rows))},
        "draw": {"actual_draws": draw_actual, "predicted_draws": draw_predicted,
                 "hits": draw_hits, "precision_pct": pct(draw_hits, draw_predicted),
                 "recall_pct": pct(draw_hits, draw_actual)},
        "score": {"n": len(score_rows), "top1_hits": score_hits,
                  "top1_accuracy_pct": pct(score_hits, len(score_rows))},
        "ou25": {"n": len(ou_rows), "hits": sum(r["predicted_ou25"] == r["actual_ou25"] for r in ou_rows),
                 "accuracy_pct": pct(sum(r["predicted_ou25"] == r["actual_ou25"] for r in ou_rows), len(ou_rows))},
        "hafu": {"n": len(hafu_rows), "hits": sum(r["predicted_hafu"] == r["actual_hafu"] for r in hafu_rows),
                 "accuracy_pct": pct(sum(r["predicted_hafu"] == r["actual_hafu"] for r in hafu_rows), len(hafu_rows))},
    }

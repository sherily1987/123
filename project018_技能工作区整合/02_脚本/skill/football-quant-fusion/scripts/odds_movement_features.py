"""只读体彩 HAD 移动特征；严格限制在预测时点之前。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


CN_TZ = timezone(timedelta(hours=8))


def _time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=CN_TZ) if parsed.tzinfo is None else parsed


def _match_id(value):
    text = str(value or "")
    return text.split("-", 1)[1] if text.startswith("sporttery-") else text


def _devig(odds):
    try:
        inverse = [1 / float(odds[key]) for key in ("h", "d", "a")]
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    total = sum(inverse)
    return [value / total for value in inverse] if total else None


def movement_feature(match: dict, rows: list[dict]) -> dict:
    """返回 earliest→latest 安全快照的去水概率变化，不足两条时 fail closed。"""
    as_of = _time(match.get("prediction_as_of") or match.get("collected_at"))
    target = _match_id(match.get("match_id") or (match.get("sporttery_meta") or {}).get("match_id"))
    safe, after = [], 0
    for row in rows:
        if _match_id(row.get("match_id")) != target or row.get("pool") != "HAD":
            continue
        observed = _time(row.get("collected_at") or row.get("updated_at") or row.get("observed_at"))
        probs = _devig(row.get("odds"))
        if as_of is None or observed is None or probs is None:
            continue
        if observed > as_of:
            after += 1
            continue
        safe.append((observed, row, probs))
    safe.sort(key=lambda item: item[0])
    if len(safe) < 2:
        return {"research_only": True, "status": "UNAVAILABLE",
                "reason": "insufficient_safe_had_snapshots", "safe_snapshot_count": len(safe),
                "excluded_after_prediction": after}
    first, last = safe[0], safe[-1]
    return {"research_only": True, "status": "VALID", "safe_snapshot_count": len(safe),
            "excluded_after_prediction": after, "from_updated_at": first[1].get("updated_at"),
            "to_updated_at": last[1].get("updated_at"), "from_prob_pct": [round(v * 100, 4) for v in first[2]],
            "to_prob_pct": [round(v * 100, 4) for v in last[2]],
            "prob_shift_pp": [round((end - start) * 100, 4) for start, end in zip(first[2], last[2])]}

#!/usr/bin/env python3
"""Build the Web workbench's read-only daily fixed-budget strategy view."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import store_view as sv


CST = timezone(timedelta(hours=8))
if str(sv.FUSION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(sv.FUSION_SCRIPTS))

from daily_strategy_planner import build_daily_strategy  # noqa: E402
from recommendation_policy import load_policy  # noqa: E402


def _validated_day(day: str | None, now: datetime) -> str:
    selected = day or now.astimezone(CST).date().isoformat()
    try:
        parsed = datetime.strptime(selected, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("day must use YYYY-MM-DD") from exc
    if parsed.isoformat() != selected:
        raise ValueError("day must use YYYY-MM-DD")
    return selected


def _load_jobs(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8-sig"))
        for path in sorted(folder.glob("sporttery-*.json"))
    ]


def daily_strategy(
    day: str | None = None,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Return a fresh, non-persisted strategy projection for one sales day."""
    current = now or datetime.now(CST)
    selected_day = _validated_day(day, current)
    store = root or sv.store_root()
    jobs = _load_jobs(store / "jobs" / selected_day)
    plan = build_daily_strategy(
        jobs,
        load_policy(),
        bankroll=100.0,
        execution_mode="budgeted_action",
        as_of=current,
    )
    return {
        **plan,
        "selected_day": selected_day,
        "source_job_count": len(jobs),
        "display": {
            "strategy_type": "固定娱乐预算",
            "edge_label": "未验证正EV",
            "decision_time": current.astimezone(CST).isoformat(),
            "warning": "这是用户授权的每日固定预算清单，不是已通过样本外验证的生产胆项或凯利仓位。",
        },
    }

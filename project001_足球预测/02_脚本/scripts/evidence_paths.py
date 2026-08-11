"""Canonical paths for current-day pre-match evidence files."""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(r"F:\HM足球比赛预测")
_WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_component(value: object) -> str:
    """Return a non-empty Windows-safe filename component."""
    cleaned = _WINDOWS_UNSAFE.sub("_", str(value)).strip().rstrip(". ")
    return cleaned or "unknown"


def evidence_path(sales_day: object, ordinal: int, home: object, away: object) -> Path:
    """Build the evidence markdown path for one ordered match."""
    day = re.sub(r"\D", "", str(sales_day))
    if len(day) != 8:
        raise ValueError("sales_day must contain exactly eight digits")
    return (
        PROJECT_ROOT
        / f"今日推荐_双轨四玩法_{day}"
        / "evidence"
        / f"evidence_{int(ordinal):03d}_{_safe_component(home)}_{_safe_component(away)}.md"
    )

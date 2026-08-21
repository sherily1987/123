"""团队强度模型参数的保守治理策略。

半衰期可以按联赛调整，但必须有明确的留出集证据和人工审核记录；没有这些，
任何看似更优的数值都会退回默认值。rho 仍由核心 DC 实现锁定，改它会改变概率，
只能在单独的 m4 候选实验中处理，不能由本策略静默覆盖。
"""
from __future__ import annotations

import math
from typing import Any


DEFAULT_HALF_LIFE = 500.0
MIN_OOS_N = 120

# 生产默认无覆盖。新增项必须保留对应 OOS 报告路径，且经人工审核后才可放在此处。
LEAGUE_HALF_LIFE_POLICIES: dict[str, dict[str, Any]] = {}


def resolve_half_life(slug: str, policies: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    policy = (policies if policies is not None else LEAGUE_HALF_LIFE_POLICIES).get(slug)
    if not isinstance(policy, dict):
        return {"half_life": DEFAULT_HALF_LIFE, "status": "DEFAULT_LOCKED"}
    value = policy.get("half_life")
    oos = policy.get("oos")
    approved = policy.get("approved_by") == "human_review"
    valid_value = (isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) and value > 0)
    valid_oos = (isinstance(oos, dict) and oos.get("split") == "held_out"
                 and isinstance(oos.get("n"), int) and oos["n"] >= MIN_OOS_N
                 and isinstance(oos.get("brier_delta"), (int, float))
                 and oos["brier_delta"] < 0)
    if valid_value and valid_oos and approved:
        return {"half_life": float(value), "status": "OOS_APPROVED"}
    return {"half_life": DEFAULT_HALF_LIFE, "status": "DEFAULT_LOCKED"}


def rho_policy() -> dict[str, str]:
    return {"status": "LOCKED", "reason": "rho changes probability output; require a separate versioned experiment"}

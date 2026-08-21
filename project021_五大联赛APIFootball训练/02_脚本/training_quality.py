"""训练产物的最小质量门禁。

这里仅判断优化是否产出可消费的数值模型；它不代替赛后 OOS 评分，也不把候选
自动升级为生产模型。这样可把“优化跑完了”与“模型值得使用”两个结论分开。
"""
from __future__ import annotations

import math
from typing import Any


VECTOR_FIELDS = ("alpha", "beta", "weighted_n")
SCALAR_FIELDS = ("home_adv", "rho", "fun")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def assess(model: dict[str, Any]) -> dict[str, Any]:
    """返回可序列化的训练质量结论，不以任意样本量阈值替代 OOS 证据。"""
    reasons: list[str] = []
    if model.get("converged") is not True:
        reasons.append("optimizer_not_converged")

    teams = model.get("teams")
    if not isinstance(teams, list) or not teams:
        reasons.append("missing_teams")
        expected = None
    else:
        expected = len(teams)

    for name in SCALAR_FIELDS:
        if not _finite(model.get(name)):
            reasons.append(f"nonfinite_{name}")
    for name in VECTOR_FIELDS:
        values = model.get(name)
        if not isinstance(values, list) or expected is None or len(values) != expected:
            reasons.append(f"invalid_{name}_shape")
        elif not all(_finite(value) for value in values):
            reasons.append(f"nonfinite_{name}")

    status = "PASS" if not reasons else "REJECTED"
    return {
        "status": status,
        "eligible_for_candidate": status == "PASS",
        "reasons": reasons,
        "team_count": expected or 0,
    }

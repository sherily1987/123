#!/usr/bin/env python3
"""可切换赔率去水方法。

默认 proportional 与历史行为一致。其余方法必须通过输入 devig_method 显式启用，
并在输出中保留方法名，方便按联赛/盘口/快照回测。
"""
import math

METHODS = ("proportional", "additive", "power", "shin")


# [中文功能] 校验赔率合法（有限且>1）
def _validate(odds):
    vals = [float(x) for x in odds]
    if not vals or any((not math.isfinite(x) or x <= 1.0) for x in vals):
        raise ValueError("odds must be finite numbers > 1")
    return vals


# [中文功能] 比例去水（默认方法）
def proportional(odds):
    q = [1.0 / x for x in odds]
    s = sum(q)
    return [x / s for x in q], s - 1.0


# [中文功能] 等额边际去水
def additive(odds):
    """Equal absolute margin removal; protects probabilities at zero."""
    q = [1.0 / x for x in odds]
    margin = sum(q) - 1.0
    if margin <= 0:
        return proportional(odds)
    z = margin / len(q)
    p = [max(0.0, x - z) for x in q]
    s = sum(p)
    return [x / s for x in p], margin


# [中文功能] 幂方法去水（数值求解k）
def power(odds):
    """Power method: find k with sum((1/odds)^k)=1."""
    q = [1.0 / x for x in odds]
    margin = sum(q) - 1.0
    if margin <= 0:
        return proportional(odds)
    lo, hi = 0.05, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        s = sum(x ** mid for x in q)
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2.0
    p = [x ** k for x in q]
    s = sum(p)
    return [x / s for x in p], margin


# [中文功能] Shin模型去水（数值求解内幕份额z）
def shin(odds):
    """Shin no-vig probabilities with a numerically solved insider share z.

    Formula follows the standard Shin implied-probability transformation:
      p_i = (sqrt(z² + 4(1-z)q_i²/S) - z) / (2(1-z))
    where q_i=1/odds_i, S=sum(q), and z is solved so sum(p)=1.
    """
    q = [1.0 / x for x in odds]
    s = sum(q)
    margin = s - 1.0
    if margin <= 0:
        return proportional(odds)

    # [中文功能] Shin概率解析式（含数值保护分支）
    def probs(z):
        if z >= 1.0 - 1e-10:
            # Stable limiting form; this branch is only a numerical guard.
            return [x * x / max(sum(y * y for y in q), 1e-15) for x in q]
        den = 2.0 * (1.0 - z)
        return [(math.sqrt(z * z + 4.0 * (1.0 - z) * x * x / s) - z) / den for x in q]

    lo, hi = 0.0, min(0.999999, max(0.05, 2.0 * margin / max(s, 1e-12)))
    # In unusual books the first upper bound may not bracket; expand safely.
    while sum(probs(hi)) > 1.0 and hi < 0.999999:
        hi = min(0.999999, hi * 1.8 + 0.01)
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if sum(probs(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
    p = probs((lo + hi) / 2.0)
    total = sum(p)
    return [x / total for x in p], margin


# [中文功能] 按名称分发去水方法（含别名）
def devig(odds, method="proportional"):
    method = str(method or "proportional").lower().replace("-", "_")
    aliases = {"multiplicative": "proportional", "normalize": "proportional",
               "normalise": "proportional", "power_method": "power",
               "shin_method": "shin"}
    method = aliases.get(method, method)
    if method not in METHODS:
        raise ValueError(f"unsupported devig_method: {method}; choose {','.join(METHODS)}")
    vals = _validate(odds)
    p, margin = globals()[method](vals)
    # Enforce a clean simplex after numerical root solving.
    total = sum(p)
    p = [x / total for x in p]
    return p, margin


# [中文功能] 返回可用去水方法列表
def available_methods():
    return list(METHODS)


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("odds", nargs="+", type=float)
    ap.add_argument("--method", default="proportional", choices=METHODS)
    a = ap.parse_args()
    p, margin = devig(a.odds, a.method)
    print(json.dumps({"method": a.method, "probabilities": p, "margin": margin}, ensure_ascii=False))

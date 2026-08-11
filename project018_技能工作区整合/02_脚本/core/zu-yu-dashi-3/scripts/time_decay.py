#!/usr/bin/env python3
"""近期比赛的指数时间衰减攻防估计。

这是独立候选，不覆盖官方 getMatchFeatureV1 的默认 strength。
半衰期用 days_half_life 表示：距目标开球每增加一个半衰期，权重减半。
"""
import math
from datetime import datetime, timezone


# [中文功能] 从多种结构解析比分
def parse_score(value):
    if isinstance(value, dict):
        for hk, ak in (("home", "away"), ("h", "a")):
            if hk in value and ak in value:
                try:
                    return int(value[hk]), int(value[ak])
                except (TypeError, ValueError):
                    return None
    text = str(value or "").strip().replace("：", ":").replace("-", ":")
    bits = text.split(":")
    if len(bits) != 2:
        return None
    try:
        return int(bits[0]), int(bits[1])
    except (TypeError, ValueError):
        return None


# [中文功能] 解析时间字符串
def parse_dt(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


# [中文功能] 取指定球队在一行赛果中的进失球
def _row_score_for_team(row, team_id=None, team_name=None):
    hs = row.get("home_team_id")
    as_ = row.get("away_team_id")
    is_home = team_id not in (None, "", 0) and str(hs) == str(team_id)
    is_away = team_id not in (None, "", 0) and str(as_) == str(team_id)
    if not is_home and not is_away and team_name:
        is_home = str(row.get("home", "")) == str(team_name)
        is_away = str(row.get("away", "")) == str(team_name)
    score = parse_score(row.get("score_90") or row.get("fullCourtGoal"))
    if not score:
        return None
    h, a = score
    if is_home:
        return h, a
    if is_away:
        return a, h
    return None


# [中文功能] 按半衰期衰减计算球队近期攻防速率
def decayed_team_rates(rows, team_id=None, team_name=None, target_dt=None, days_half_life=30.0):
    """返回 {attack, defense, sample, effective_sample, weights}。"""
    target = parse_dt(target_dt) or datetime.now(timezone.utc)
    half = max(float(days_half_life), 1e-6)
    weighted_attack = weighted_defense = total_weight = 0.0
    used = []
    for row in rows or []:
        pair = _row_score_for_team(row, team_id, team_name)
        dt = parse_dt(row.get("date") or row.get("matchDateTime") or row.get("matchDate"))
        if pair is None or dt is None:
            continue
        age_days = max(0.0, (target - dt).total_seconds() / 86400.0)
        weight = math.exp(-math.log(2.0) * age_days / half)
        attack, defense = pair
        weighted_attack += weight * attack
        weighted_defense += weight * defense
        total_weight += weight
        used.append({"date": row.get("date") or row.get("matchDateTime") or row.get("matchDate"),
                     "age_days": round(age_days, 2), "weight": round(weight, 5),
                     "attack": attack, "defense": defense})
    if total_weight <= 0:
        return {"status": "UNAVAILABLE", "attack": None, "defense": None,
                "sample": 0, "effective_sample": 0.0, "weights": []}
    return {"status": "VALID", "attack": round(weighted_attack / total_weight, 4),
            "defense": round(weighted_defense / total_weight, 4),
            "sample": len(used), "effective_sample": round(total_weight, 4),
            "weights": used}


# [中文功能] 用两队近期衰减均值交叉生成λ候选
def build_decay_strength(home_rows, away_rows, home_id=None, away_id=None,
                         home_name=None, away_name=None, target_dt=None,
                         days_half_life=30.0):
    """用两队自身近期攻防衰减均值交叉生成 λ 候选。"""
    home = decayed_team_rates(home_rows, home_id, home_name, target_dt, days_half_life)
    away = decayed_team_rates(away_rows, away_id, away_name, target_dt, days_half_life)
    if home["attack"] is None or home["defense"] is None or away["attack"] is None or away["defense"] is None:
        return {"status": "UNAVAILABLE", "days_half_life": days_half_life,
                "home": home, "away": away}
    return {
        "status": "VALID",
        "lambda_home": round((home["attack"] + away["defense"]) / 2.0, 4),
        "lambda_away": round((away["attack"] + home["defense"]) / 2.0, 4),
        "days_half_life": float(days_half_life),
        "home": home, "away": away,
        "note": "指数时间衰减攻防候选；未做对手强度调整，必须时间切分回测。"
    }

# -*- coding: utf-8 -*-
"""
EV (期望值) 计算与下注推荐模块
================================
EV = (校准概率 × 赔率) - 1

**2026-08-15 方法论修复**：本模块此前把 LLM 投票计数归一化后直接当成概率代入 EV
（`votes_to_probabilities()`）。那是错的，而且是系统性的错：

  - 3 个模型投票时，票比的取值只能是 0、1/3、2/3、1。3:0 一致时票比 = 1.0，
    EV 直接变成「赔率 - 1」，任何冷门赔率都会算出巨额正 EV；
  - 票比衡量的是「模型之间有多一致」，不是「事件有多可能发生」。一致 ≠ 高概率，
    三个模型可以一致地错；
  - 该量从未做过任何校准，没有「票比 x% 时实际命中 y%」的实测支撑。

结果就是**罕见/分歧场次的期望值被系统性高估**。现改为：没有外部校准概率来源时
**拒绝计算 EV**（fail closed），只输出明确标注的投票比例；要出 EV 必须显式传入
`calibrated_probs` 并声明 `prob_source`。

这与融合技能 SKILL.md 的两条硬边界一致：
  6. 投票比例、数据质量、模型概率和推荐置信度是四个不同量，禁止互相替代；
  7. `action=skip` 的结果不得进入推荐表；LLM轨的票数不能用于EV计算。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

DIRECTIONS = ["主胜", "平局", "客胜"]

NO_PROB_SOURCE_REASON = (
    "无校准概率来源：LLM 投票比例不是概率，禁止据此计算 EV"
    "（需显式传入 calibrated_probs 并声明 prob_source）"
)


def votes_to_probabilities(votes: Dict[str, float]) -> Dict[str, float]:
    """已废弃：票比不是概率，调用即报错，不静默返回一个假概率。"""
    raise NotImplementedError(
        "votes_to_probabilities() 已于 2026-08-15 移除：投票比例不是校准概率，"
        "不得代入 EV。需要票比请用 votes_to_vote_share()，需要 EV 请提供 calibrated_probs。"
    )


def votes_to_vote_share(votes: Dict[str, float]) -> Dict[str, float]:
    """把投票计数归一化成**投票比例**。

    这是「模型之间的一致程度」，**不是**事件发生概率，不得代入 EV 或当作置信度。

    输入: {"主胜": 3.2, "平局": 1.5, "客胜": 0.8}
    输出: {"主胜": 0.58, "平局": 0.27, "客胜": 0.15}
    """
    total = sum(votes.values())
    if total == 0:
        return {k: 0.0 for k in votes} or {d: 0.0 for d in DIRECTIONS}
    return {k: v / total for k, v in votes.items()}


def odds_to_implied_prob(odds: float) -> float:
    """赔率转化为隐含概率（含博彩公司水位，未去水）。

    例: 赔率 2.0 → 隐含概率 0.5 (50%)
    """
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds


def calculate_ev(predicted_prob: float, odds: float) -> float:
    """计算期望值 EV = (校准概率 × 赔率) - 1。

    调用方负责保证 `predicted_prob` 来自已校准的概率来源；本函数不做来源校验。
    """
    return (predicted_prob * odds) - 1.0


def calculate_all_ev(
    probabilities: Dict[str, float],
    model_odds: List[float],
) -> Dict[str, Dict[str, float]]:
    """为 1X2 三个方向计算 EV。

    `probabilities` 必须是校准概率（如轨道A融合引擎的 `final_1x2_pct`/100），
    **不接受投票比例**。model_odds 为 [主胜赔率, 平赔率, 客胜赔率]。
    """
    if not model_odds or len(model_odds) < 3:
        return {}
    if not probabilities:
        return {}

    result = {}
    for i, direction in enumerate(DIRECTIONS):
        odds = model_odds[i]
        pred_prob = probabilities.get(direction, 0)
        result[direction] = {
            "predicted_prob": pred_prob,
            "odds": odds,
            "ev": calculate_ev(pred_prob, odds),
        }
    return result


def vote_share_table(
    votes: Dict[str, float],
    model_odds: List[float],
) -> Dict[str, Dict[str, float]]:
    """无概率来源时的替代输出：只给投票比例和赔率，**不含 EV 字段**。

    刻意不带 `ev` 键——下游若误当成 `ev_analysis` 使用会 KeyError 报错，
    而不是拿到一个看起来合理的假数字。
    """
    share = votes_to_vote_share(votes)
    table = {}
    for i, direction in enumerate(DIRECTIONS):
        table[direction] = {
            "vote_share": share.get(direction, 0.0),
            "odds": model_odds[i] if len(model_odds) > i else None,
        }
    return table


def find_positive_ev_bets(
    ev_results: Dict[str, Dict[str, float]],
    min_ev_threshold: float = 0.05,
) -> List[Dict[str, Any]]:
    """筛选达到 EV 阈值的方向，按 EV 降序。

    2026-08-15：原签名有个 `max_strength_threshold` 参数，函数体里从未使用——
    调用方以为传了强度门槛其实没有生效。强度门槛真正生效的地方在
    `generate_betting_recommendation()` 的 `min_strength`，这里删掉以免再误导。
    """
    opportunities = [
        {
            "direction": direction,
            "predicted_prob": data["predicted_prob"],
            "odds": data["odds"],
            "ev": data["ev"],
            "recommendation": "下注",
        }
        for direction, data in ev_results.items()
        if data["ev"] >= min_ev_threshold
    ]
    opportunities.sort(key=lambda x: x["ev"], reverse=True)
    return opportunities


def generate_betting_recommendation(
    votes: Dict[str, float],
    model_odds: List[float],
    strength: float,
    evidence_gap: bool = False,
    min_ev: float = 0.05,
    min_strength: float = 0.6,
    calibrated_probs: Optional[Dict[str, float]] = None,
    prob_source: Optional[str] = None,
    prob_calibration_status: str = "UNFITTED",
    market_derived: bool = False,
) -> Dict[str, Any]:
    """生成下注推荐；无校准概率来源时 fail closed。

    参数:
      votes: LLM 投票计数（只用于展示投票比例与强度门槛，不参与 EV）
      calibrated_probs: {"主胜": 0.52, "平局": 0.26, "客胜": 0.22} 形式的**校准概率**
      prob_source: 概率来源标识（如 "fusion-m2-final_1x2_pct"），与 calibrated_probs 必须同时提供
      prob_calibration_status: "VALID" 表示该概率来源做过校准；其余值一律不得出胆
      market_derived: 概率是否由**同一个盘口**去水反解而来。若是，EV 量到的是庄家水位
        而非独立信息带来的 edge，因此照常给数字但拒绝出胆（与融合技能 edge_min_pp=5 /
        max_market_dependency_pct 的判断一致）。

    返回: {
      "action": "bet" | "skip",
      "reason": str,
      "recommended_bets": [...],
      "ev_analysis": {...},            # 无概率来源时为空 dict
      "vote_share_analysis": {...},    # 无概率来源时给出，不含 ev 字段
      "probability_source": str | None,
      "probability_calibration_status": str,
      "market_derived": bool,
    }
    """
    base = {
        "recommended_bets": [],
        "ev_analysis": {},
        "vote_share_analysis": {},
        "probability_source": prob_source,
        "probability_calibration_status": prob_calibration_status,
        "market_derived": bool(market_derived),
    }

    if not model_odds or len(model_odds) < 3:
        return {**base, "action": "skip", "reason": "缺少赔率数据，无法计算 EV"}

    # ---- 方法论闸门：没有校准概率来源就不产出 EV ----
    if not calibrated_probs or not prob_source:
        return {
            **base,
            "action": "skip",
            "reason": NO_PROB_SOURCE_REASON,
            "vote_share_analysis": vote_share_table(votes, model_odds),
            "probability_source": None,
        }

    ev_results = calculate_all_ev(calibrated_probs, model_odds)
    if not ev_results:
        return {**base, "action": "skip", "reason": "校准概率为空，无法计算 EV"}
    base["ev_analysis"] = ev_results
    base["vote_share_analysis"] = vote_share_table(votes, model_odds)

    # 概率来源本身未校准 → 出数字供研究，但不得出胆
    if str(prob_calibration_status).upper() != "VALID":
        return {**base, "action": "skip",
                "reason": f"概率来源未校准（calibration_status={prob_calibration_status}），"
                          "EV 仅供研究，不构成推荐"}

    # 概率由同一个盘口去水而来 → EV 量的是水位不是 edge，同样不得出胆
    if market_derived:
        return {**base, "action": "skip",
                "reason": "概率来源为市场去水反解（market_only），对同一盘口算 EV 量到的是"
                          "庄家水位而非独立信息 edge，不构成推荐"}

    if evidence_gap:
        return {**base, "action": "skip", "reason": "证据存在缺口，风险过高"}

    if strength < min_strength:
        return {**base, "action": "skip",
                "reason": f"投票强度 {strength:.1%} < {min_strength:.1%}，共识不足"}

    opportunities = find_positive_ev_bets(ev_results, min_ev_threshold=min_ev)
    if not opportunities:
        return {**base, "action": "skip",
                "reason": f"无正期望值机会（所有方向 EV < {min_ev:.0%}）"}

    return {**base, "action": "bet",
            "reason": f"发现 {len(opportunities)} 个正 EV 机会（概率来源：{prob_source}）",
            "recommended_bets": opportunities}


def format_betting_advice(recommendation: Dict[str, Any]) -> str:
    """格式化下注建议；skip 时必须同时显示判定结果和理由，不得只摘数字。"""
    lines = []
    action = recommendation["action"]
    reason = recommendation["reason"]
    ev_analysis = recommendation.get("ev_analysis") or {}
    vote_shares = recommendation.get("vote_share_analysis") or {}
    source = recommendation.get("probability_source")

    if action == "skip":
        lines.append(f"🚫 不下注 — {reason}")
        lines.append("")
        if ev_analysis:
            status = recommendation.get("probability_calibration_status", "?")
            flag = "，市场去水反解" if recommendation.get("market_derived") else ""
            lines.append(f"EV 分析（概率来源：{source}，校准状态 {status}{flag}）:")
            for direction, data in ev_analysis.items():
                ev = data.get("ev", 0)
                symbol = "✅" if ev >= 0 else "❌"
                lines.append(f"  {direction}: 概率 {data.get('predicted_prob', 0):.1%}"
                             f" × 赔率 {data.get('odds', 0):.2f} = EV {ev:+.1%} {symbol}")
        elif vote_shares:
            lines.append("投票比例（非概率，不可用于 EV）:")
            for direction, data in vote_shares.items():
                odds = data.get("odds")
                odds_text = f"{odds:.2f}" if isinstance(odds, (int, float)) else "?"
                lines.append(f"  {direction}: 票比 {data.get('vote_share', 0):.1%} | 赔率 {odds_text}")
        return "\n".join(lines)

    lines.append(f"✅ 推荐下注 — {reason}")
    lines.append("")
    lines.append("正 EV 机会:")
    for bet in recommendation["recommended_bets"]:
        lines.append(f"  🎯 {bet['direction']}: 概率 {bet['predicted_prob']:.1%}"
                     f" × 赔率 {bet['odds']:.2f} = EV {bet['ev']:+.1%}")
    picked = {b["direction"] for b in recommendation["recommended_bets"]}
    others = [(d, data) for d, data in ev_analysis.items() if d not in picked]
    if others:
        lines.append("")
        lines.append("其他方向:")
        for direction, data in others:
            lines.append(f"  {direction}: 概率 {data.get('predicted_prob', 0):.1%}"
                         f" × 赔率 {data.get('odds', 0):.2f} = EV {data.get('ev', 0):+.1%}")
    return "\n".join(lines)

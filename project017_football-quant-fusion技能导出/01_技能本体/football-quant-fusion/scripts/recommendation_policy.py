#!/usr/bin/env python3
"""Production recommendation gates shared by fusion and Sporttery workflows.

This module deliberately refuses to invent calibrated confidence. Until a
chronological calibration artifact is approved, confidence_pct is None and a
prediction cannot be promoted to a banker.
"""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY_FILE = HERE.parent / 'config' / 'recommendation_policy.json'


# [中文功能] 加载推荐策略配置，缺失时返回默认策略
def load_policy():
    if POLICY_FILE.exists():
        try:
            return json.loads(POLICY_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'calibration_status': 'UNFITTED',
        'min_samples_for_recalibration': 100,
        'target_samples_for_threshold_review': 200,
        'one_goal_draw_risk_pct': 18.0,
        'stale_market_factor': {'fresh_hours': 6, 'half_hours': 12, 'max_hours': 24},
    }


# [中文功能] 汇总输出的可靠性旗标列表
def _flags(output):
    return list(output.get('reliability_flags') or []) + list(output.get('flags') or [])


# [中文功能] 从输出中取核心预测对象（兼容新旧结构）
def _forecast(output):
    return output.get('core_output', output)


# [中文功能] 取市场新鲜度信息
def _market_freshness(output):
    return output.get('market_freshness') or output.get('core_output', {}).get('market_freshness') or {}


# [中文功能] 读取已批准的主概率校准值（未批准返回None）
def _calibrated_primary(output, policy):
    status = str(policy.get('calibration_status') or 'UNFITTED').upper()
    core = _forecast(output)
    probs = core.get('final_1x2_pct') or []
    if status not in ('VALID', 'APPROVED') or len(probs) != 3:
        return None, status
    params = policy.get('calibration_params')
    if not isinstance(params, dict):
        return None, status
    art = params.get('primary_probability')
    if art is None:
        return None, status
    if isinstance(art, (int, float)):
        return float(art), status
    if not (isinstance(art, dict) and art.get('method') == 'band_table_plus_edge'):
        return None, status
    # 主方向概率分档校准（2026-08-03 批准工件）：final_1x2_pct 为百分数。
    primary = max(range(3), key=lambda j: probs[j])
    max_prob = probs[primary] / 100.0
    mkt = core.get('market_prob_pct') or []
    if len(mkt) != 3:
        return None, status  # 缺市场概率无法判 edge，失败关闭
    edge_pp = probs[primary] - mkt[primary]
    if edge_pp < float(art.get('edge_min_pp', 0)):
        return None, status  # 低于 edge 门槛不给 confidence
    for b in art.get('bands') or []:
        lo = float(b.get('lo', 0.0))
        hi = float(b.get('hi', 1.01))
        if lo <= max_prob < hi and b.get('prob') is not None:
            return float(b['prob']), status
    return None, status


# [中文功能] 计算推荐门控与可审计的风险详情
def evaluate(output, market_freshness=None):
    """Return a hard recommendation gate and auditable risk details."""
    policy = load_policy()
    core = _forecast(output)
    decision = output.get('fusion_decision') or core.get('fusion_decision') or {}
    flags = _flags(output)
    status = str(decision.get('status') or '')
    dependency = float(decision.get('market_dependency_pct') or core.get('market_dependency_pct') or 0)
    significant = decision.get('edge_significant_vs_sensitivity') is True
    unfit = (
        status in ('UNFITTED_NO_VALUE', 'EDGE_BELOW_UNCERTAINTY')
        or any(str(x).startswith(('UNFITTED', 'AUTO_MARKET_WEIGHTS')) for x in flags)
        or not significant
    )
    cal_prob, cal_status = _calibrated_primary(output, policy)

    hhad = core.get('sporttery_hhad_3way') or {}
    hhad_probs = hhad.get('model_prob_pct') or []
    line = hhad.get('line')
    one_goal_risk = None
    if len(hhad_probs) == 3 and line is not None and abs(float(line) + 1.0) < 1e-9:
        # For Sporttery HHAD -1, let-draw means the home side wins exactly
        # one goal. Do not apply this rule to +1 or non-integer lines.
        one_goal_risk = float(hhad_probs[1])
    freshness = market_freshness or _market_freshness(output)
    stale_pools = []
    if isinstance(freshness, dict):
        for pool, meta in freshness.items():
            if isinstance(meta, dict) and meta.get('status') in ('OUTDATED', 'STALE'):
                stale_pools.append(pool)

    # 用户裁定 2026-08-12：概率 >= 50% 即允许出胆（market_only 跟随市场，
    # 接受足球不确定性；AVOID_DATA_RISK/让球险/陈旧盘保留为标注不阻断）。
    probs = core.get('final_1x2_pct') or []
    primary = max(range(3), key=lambda j: probs[j]) if len(probs) == 3 else None
    max_prob = probs[primary] / 100.0 if primary is not None else 0.0
    prob_threshold = float(policy.get('banker_prob_threshold', 0.50))
    banker_allowed = bool(
        max_prob >= prob_threshold
        and status not in ('UNFITTED_NO_VALUE', 'UNAVAILABLE')  # 占位/无输出仍阻断
        and not stale_pools
    )
    confidence = round(max_prob, 3) if banker_allowed else None
    reasons = []
    if status in ('UNFITTED_NO_VALUE', 'UNAVAILABLE'):
        reasons.append('UNFITTED_OR_NO_SIGNIFICANT_EDGE')
    if max_prob < prob_threshold:
        reasons.append(f'PROB_BELOW_BANKER_THRESHOLD:{round(max_prob * 100, 1)}%')
    if stale_pools:
        reasons.append('STALE_MARKET:' + ','.join(sorted(stale_pools)))
    if one_goal_risk is not None and one_goal_risk >= float(policy.get('one_goal_draw_risk_pct', 18.0)):
        reasons.append('ONE_GOAL_OR_PUSH_RISK')

    # 让球推荐（体彩让球胜平负 HHAD，三项：让胜/让平/让负）——跟1X2用同一套阈值逻辑，
    # 不是另起一套标准。之前 hhad 只作为1X2出胆的风险标注（ONE_GOAL_OR_PUSH_RISK），
    # 没有自己的推荐结论；用户 2026-08-13 要求补上。
    # 注意：这是体彩 HHAD（固定让球线的三项盘），不是真正的亚洲盘（win/push/half
    # 结算）；两者结算规则不同，见 asian_handicap_home 字段的单独说明，不能混用。
    hhad_primary = max(range(3), key=lambda j: hhad_probs[j]) if len(hhad_probs) == 3 else None
    hhad_max_prob = hhad_probs[hhad_primary] / 100.0 if hhad_primary is not None else 0.0
    hhad_labels = ['让胜', '让平', '让负']
    hhad_banker_allowed = bool(
        hhad_primary is not None
        and hhad_max_prob >= prob_threshold
        and status not in ('UNFITTED_NO_VALUE', 'UNAVAILABLE')
        and not stale_pools
    )
    hhad_recommendation = {
        'available': hhad_primary is not None,
        'line': line,
        'primary_pick': hhad_labels[hhad_primary] if hhad_primary is not None else None,
        'confidence_pct': round(hhad_max_prob, 3) if hhad_banker_allowed else None,
        'banker_allowed': hhad_banker_allowed,
        'market_type': 'sporttery_hhad_3way',
        'note': '体彩让球胜平负三项盘推荐，跟1X2共用同一置信阈值；不是亚洲盘（win/push/half），'
                '结算规则不同。calibration_status 未独立验证，参照整体calibration_status字段。',
    }

    return {
        'banker_allowed': banker_allowed,
        'confidence_pct': confidence,
        'confidence_status': 'CALIBRATED' if confidence is not None else cal_status,
        'calibration_status': cal_status,
        'primary_edge_significant': significant,
        'market_dependency_pct': dependency,
        'hhad': {'line': line, 'model_prob_pct': hhad_probs,
                 'let_win_pct': hhad_probs[0] if len(hhad_probs) == 3 else None,
                 'let_draw_or_one_goal_pct': hhad_probs[1] if len(hhad_probs) == 3 else None,
                 'let_loss_pct': hhad_probs[2] if len(hhad_probs) == 3 else None},
        'hhad_recommendation': hhad_recommendation,
        'one_goal_risk_pct': one_goal_risk,
        'stale_pools': sorted(stale_pools),
        'reasons': reasons,
        'thresholds': {
            'one_goal_draw_risk_pct': float(policy.get('one_goal_draw_risk_pct', 18.0)),
            'min_samples_for_recalibration': int(policy.get('min_samples_for_recalibration', 100)),
            'target_samples_for_threshold_review': int(policy.get('target_samples_for_threshold_review', 200)),
        },
        'note': '用户裁定 2026-08-12：主方向概率>=50%即允许出胆（market_only 跟随市场，接受不确定性）；UNFITTED_NO_VALUE/无输出/陈旧盘仍阻断。',
    }


# [中文功能] 严格校验组合腿ID（缺失/重复即无效）
def validate_combo_ids(combo, prediction_ids, cover_ids=()):
    """Strictly validate all combo legs against registered prediction/cover IDs."""
    valid = set(prediction_ids) | set(cover_ids)
    legs = list(combo.get('legs') or [])
    missing = [x for x in legs if x not in valid]
    duplicate = sorted({x for x in legs if legs.count(x) > 1})
    return {
        'valid': bool(legs) and not missing and not duplicate,
        'missing_leg_ids': missing,
        'duplicate_leg_ids': duplicate,
        'total_legs': len(legs),
    }


if __name__ == '__main__':
    print(json.dumps(load_policy(), ensure_ascii=False, indent=2))
    

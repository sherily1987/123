#!/usr/bin/env python3
"""足预大师 3.1 — 校准回测工具

解决的问题：predict.py 自称「校准导向」，但此前没有任何代码能验证这一点。
校准是可测量的性质——说 60% 的那批场次，实际赢了多少？

用法：
    python backtest.py history.json

输入格式（在 predict.py 的正常输入基础上，每场加一个 actual 真实比分）：
{
  "matches": [
    {"home":"A","away":"B","stage":"联赛","kickoff":"2026-01-01",
     "odds":[2.1,3.4,3.5], "actual":[2,1]},
    ...
  ]
}

输出四组指标：
  1. Brier score  — 概率预测的均方误差，越低越好
  2. Log loss     — 对自信错误惩罚更重，越低越好
  3. 校准表       — 分档对比「预测概率」与「实际频率」，这是校准的直接证据
  4. 基线对比     — 跟「always 基础频率」和「直接抄盘口」比，模型有没有价值

⚠️ 关键判据：模型必须同时打败「基础频率基线」和「市场基线」才算有价值。
   打不过市场，说明它只是在复述盘口 + 引入噪声。
"""
import argparse
import json
import math
import sys

from predict import predict


def outcome_index(actual):
    """真实比分 → 0=主胜 1=平 2=客胜"""
    h, a = actual
    return 0 if h > a else (1 if h == a else 2)


def brier(probs, idx):
    """多分类 Brier score：sum((p_i - y_i)^2)，范围 0（完美）到 2（最差）。"""
    return sum((p - (1 if i == idx else 0)) ** 2 for i, p in enumerate(probs))


def logloss(probs, idx, eps=1e-15):
    """对数损失。预测 0% 却发生了 → 惩罚趋于无穷，故做截断。"""
    return -math.log(max(eps, min(1 - eps, probs[idx])))


def calibration_table(records, bins=5):
    """把所有「概率-结果」对按预测概率分档，比较预测值与实际频率。

    完美校准的表现：每一档的「平均预测概率」≈「实际发生频率」。
    """
    edges = [i / bins for i in range(bins + 1)]
    table = []
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        sel = [(p, y) for p, y in records if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if not sel:
            table.append({'bin': f'{lo:.0%}-{hi:.0%}', 'n': 0,
                          'avg_pred_pct': None, 'actual_pct': None, 'gap_pp': None})
            continue
        avg_p = sum(p for p, _ in sel) / len(sel)
        act = sum(y for _, y in sel) / len(sel)
        table.append({
            'bin': f'{lo:.0%}-{hi:.0%}',
            'n': len(sel),
            'avg_pred_pct': round(avg_p * 100, 1),
            'actual_pct': round(act * 100, 1),
            'gap_pp': round((avg_p - act) * 100, 1),
        })
    return table


def run(matches):
    model_briers, model_lls = [], []
    market_briers, market_lls = [], []
    base_briers = []
    cal_records = []          # (预测概率, 是否发生) 用于校准表
    counts = [0, 0, 0]        # 主/平/客 实际次数
    skipped = []

    evaluated = []
    for i, m in enumerate(matches):
        actual = m.get('actual')
        if not (isinstance(actual, list) and len(actual) == 2):
            skipped.append({'index': i, 'reason': 'actual 缺失或格式错误'})
            continue
        res = predict({k: v for k, v in m.items() if k != 'actual'})
        if res.get('status') != 'ok':
            skipped.append({'index': i, 'reason': f"predict 返回 {res.get('status')}",
                            'detail': res.get('missing') or res.get('errors')})
            continue
        idx = outcome_index(actual)
        counts[idx] += 1
        probs = [x / 100 for x in res['final_1x2_pct']]
        evaluated.append((probs, idx, res))

    if not evaluated:
        return {'status': 'no_data', 'skipped': skipped,
                'hint': '没有任何一场通过 predict 校验并带有 actual，无法回测。'}

    # 基础频率基线：用全样本的实际分布当预测（这是「什么都不学」的下限）
    n = len(evaluated)
    base = [c / n for c in counts]

    for probs, idx, res in evaluated:
        model_briers.append(brier(probs, idx))
        model_lls.append(logloss(probs, idx))
        base_briers.append(brier(base, idx))
        mk = res.get('market_prob_pct')
        if mk:
            mkp = [x / 100 for x in mk]
            market_briers.append(brier(mkp, idx))
            market_lls.append(logloss(mkp, idx))
        for k in range(3):
            cal_records.append((probs[k], 1 if k == idx else 0))

    def avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    model_b, base_b = avg(model_briers), avg(base_briers)
    market_b = avg(market_briers)

    verdict = []
    if model_b is not None and base_b is not None:
        if model_b < base_b:
            verdict.append(f'✅ 打败基础频率基线（{model_b} < {base_b}）')
        else:
            verdict.append(f'❌ 未打败基础频率基线（{model_b} >= {base_b}）——模型没有学到任何有效信息')
    if market_b is not None:
        if model_b < market_b:
            verdict.append(f'✅ 打败市场基线（{model_b} < {market_b}）')
        else:
            verdict.append(f'❌ 未打败市场基线（{model_b} >= {market_b}）'
                           '——直接抄盘口比用模型更准，模型在引入噪声')

    if n < 50:
        verdict.append(f'⚠️ 样本量仅 {n} 场，统计噪声很大。Brier 差异小于 0.02 时不要当真。'
                       '建议至少 200 场再下结论。')

    return {
        'status': 'ok',
        'n_evaluated': n,
        'n_skipped': len(skipped),
        'actual_distribution_pct': [round(x * 100, 1) for x in base],
        'scores': {
            'model_brier': model_b,
            'model_logloss': avg(model_lls),
            'market_brier': market_b,
            'market_logloss': avg(market_lls),
            'baseline_brier': base_b,
        },
        'calibration_table': calibration_table(cal_records),
        'verdict': verdict,
        'skipped_detail': skipped[:10],
        'how_to_read': {
            'brier': '0 = 完美，越低越好。三分类随机猜约 0.67。',
            'calibration_table': 'gap_pp 接近 0 表示校准良好。'
                                 '正值 = 模型过于自信，负值 = 过于保守。',
            'next_step': '若某档 gap_pp 系统性偏正，说明模型高估了自己；'
                         '可回到 predict.py 顶部调整 [UNFITTED] 常数后重跑本脚本。',
        },
    }


def main():
    ap = argparse.ArgumentParser(description='足预大师 3.1 校准回测')
    ap.add_argument('input', help='历史比赛 JSON（每场需含 actual 真实比分）')
    a = ap.parse_args()
    raw = json.load(open(a.input, encoding='utf-8-sig'))
    matches = raw['matches'] if isinstance(raw, dict) and 'matches' in raw else raw
    if not isinstance(matches, list):
        print(json.dumps({'status': 'invalid', 'error': '输入应为 {"matches":[...]} 或数组'},
                         ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps(run(matches), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

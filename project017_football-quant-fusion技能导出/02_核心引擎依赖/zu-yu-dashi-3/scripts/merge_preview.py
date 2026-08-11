#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把前瞻强度锚合并进模型输入，并与本地登记库赛果去重。

去重规则：前瞻的近N场统计与本地 registry 里已结算的同场比赛可能重叠。
    以 (home_team_id, away_team_id, 日期) 为键比对，重叠场次记入 overlap_note，
    避免同一场真实赛果既进前瞻统计又进本地样本，导致重复计权。

模式升级：有 strength 时把 lambda_home/lambda_away 写进输入，模式由
    market_only 升为 hybrid，引擎据此做市场λ与独立λ的加权融合。
    LOW_SAMPLE（<8场）默认降权，可用 --allow-low-sample 强制启用。

用法：
  python3 merge_preview.py --input model_input.json --preview prev.json \
      --output model_input_hybrid.json [--market-weight 0.65]
"""
import argparse, json
from pathlib import Path

STORE = 'H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/backtest'


# [中文功能] 读取本地已结算比赛用于去重比对
def local_results(store):
    """本地登记库已结算比赛 → {(home_id, away_id, date): score}，用于去重比对。"""
    out = {}
    rd = Path(store) / 'results'
    if not rd.exists(): return out
    for p in rd.glob('*.json'):
        try:
            r = json.load(open(p, encoding='utf-8'))
        except ValueError:
            continue
        s = r.get('score_90') or {}
        out[r.get('match_id')] = f"{s.get('home')}-{s.get('away')}"
    return out


# [中文功能] 标准化日期为YYYY-MM-DD
def norm_date(x):
    return str(x or '')[:10]


# [中文功能] 把官方前瞻合并进模型输入
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--preview', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--store', default=STORE)
    ap.add_argument('--market-weight', type=float, default=0.65,
                    help='hybrid 时市场权重，默认0.65（市场仍占主导，独立锚只做修正）')
    ap.add_argument('--prior-weight', type=float, default=0.02,
                    help='前瞻λ软约束权重，默认0.02（λ可见位移，盘口拟合代价+7%%）')
    ap.add_argument('--allow-low-sample', action='store_true')
    a = ap.parse_args()

    data = json.load(open(a.input, encoding='utf-8'))
    prev = {m['match_id']: m for m in json.load(open(a.preview, encoding='utf-8'))['matches']}
    local = local_results(a.store)

    matches = data.get('matches') or [data]
    report = []
    for m in matches:
        mid = (m.get('sporttery_meta') or {}).get('match_id')
        p = prev.get(mid)
        row = {'match': f"{m.get('home')} vs {m.get('away')}", 'match_id': mid}
        if not p or not p.get('strength'):
            row['status'] = 'no_preview'; report.append(row); continue

        st = p['strength']
        if st['status'] == 'LOW_SAMPLE' and not a.allow_low_sample:
            row['status'] = 'low_sample_skipped'; row['legs'] = st['sample_legs']
            report.append(row); continue

        # 去重：前瞻近N场里若出现本地已登记过的同场比赛，标注但不剔除
        # （前瞻是聚合统计，无法逐场剔除，只能记录重叠程度供审计）
        seen = set()
        for side in ('recent_home', 'recent_away'):
            for x in p.get(side) or []:
                seen.add((norm_date(x.get('date')), x.get('home'), x.get('away')))
        row['preview_legs'] = st['sample_legs']
        row['local_settled'] = len(local)
        row['overlap_note'] = ('前瞻统计为官方聚合值，无法逐场剔除；'
                               '本地已结算%d场，若与前瞻窗口重叠则该信息被计两次' % len(local))

        # 写成软约束先验，不直接覆盖 λ：
        # 有赔率时 λ 仍由多市场拟合决定，先验只在目标函数里加一项偏离惩罚，
        # 把结果往球队历史攻防均值方向"轻推"。
        m['lambda_prior'] = {
            'lambda_home': st['lambda_home'], 'lambda_away': st['lambda_away'],
            'weight': a.prior_weight, 'sample_legs': st['sample_legs'],
            'source': '中国体彩网官方前瞻(getMatchFeatureV1)'}
        m['mode'] = 'hybrid'
        m['market_weight'] = a.market_weight
        m.setdefault('field_meta', {})['lambda_prior'] = {
            'status': st['status'], 'source': '中国体彩网官方前瞻(getMatchFeatureV1)',
            'sample_legs': st['sample_legs'], 'note': st['note']}
        m.setdefault('assumptions', []).append(
            'λ锚来自官方近%d场攻防均值，未做对手强度调整' % st['sample_legs'])
        # 伤停：官方名单按位置/出场率折算的攻防缺阵，是唯一独立于赔率的信息
        inj = p.get('injuries') or {}
        applied = {}
        for side, sfx in (('home', 'home'), ('away', 'away')):
            s = inj.get(side) or {}
            if not s.get('count'):
                continue
            for fld in ('attack_absence', 'defense_absence', 'gk_absence'):
                v = s.get(fld) or 0
                if v > 0:
                    m[f'{fld}_{sfx}'] = v
                    applied[f'{fld}_{sfx}'] = v
            m.setdefault('field_meta', {})[f'injury_{sfx}'] = {
                'status': s.get('status', 'VALID'), 'source': '中国体彩网官方伤停(getInjurySuspensionV1)',
                'count': s['count'], 'confirmed_no_absence': s.get('confirmed_no_absence', False),
                'players': [f"{x['name']}({x['pos']},{x['type']},{x['apps']}场)" for x in s.get('players', [])]}
        if applied:
            m.setdefault('assumptions', []).append(
                '伤停冲击由官方名单按位置与出场率折算，系数未经回测拟合')
            row['injury_applied'] = applied
            # System-generated ledger entries so fusion_predict does not treat
            # official injury mappings as unledgered user adjustments.
            ledger = m.setdefault('adjustment_ledger', [])
            existing = {x.get('field') for x in ledger if isinstance(x, dict)}
            for fld, val in applied.items():
                if fld in existing:
                    continue
                side = 'home' if fld.endswith('_home') else 'away'
                s = inj.get(side) or {}
                players = s.get('players') or []
                fact = '官方伤停名单映射' + (f"：{', '.join(p.get('name','?') for p in players[:5])}" if players else '')
                ledger.append({
                    'field': fld,
                    'value': val,
                    'fact': fact,
                    'source': '中国体彩网官方伤停(getInjurySuspensionV1)',
                    'mapping_basis': 'position_and_start_rate_heuristic',
                    'calibration': 'UNFITTED',
                    'system_generated': True,
                    'note': '自动由merge_preview写入；系数未经回测拟合'
                })
        for side in ('home', 'away'):
            s = inj.get(side) or {}
            # Do not overwrite a richer injury_* meta written above when count>0.
            if f'injury_{side}' in (m.get('field_meta') or {}) and s.get('count'):
                continue
            m.setdefault('field_meta', {})[f'injury_{side}'] = {
                'status': s.get('status', 'UNAVAILABLE'),
                'source': '中国体彩网官方伤停(getInjurySuspensionV1)',
                'count': s.get('count', 0),
                'confirmed_no_absence': s.get('confirmed_no_absence', False),
                'note': '接口无名单不等于确认无伤停。'
            }
        row['injury_count'] = {'home': (inj.get('home') or {}).get('count', 0),
                               'away': (inj.get('away') or {}).get('count', 0),
                               'home_status': (inj.get('home') or {}).get('status', 'UNAVAILABLE'),
                               'away_status': (inj.get('away') or {}).get('status', 'UNAVAILABLE')}
        row['status'] = 'merged'
        row['prior_lambda'] = [st['lambda_home'], st['lambda_away']]
        row['prior_weight'] = a.prior_weight
        report.append(row)

    out = {'matches': matches} if 'matches' in data else matches[0]
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({'status': 'ok', 'output': a.output,
                      'merged': sum(1 for r in report if r['status'] == 'merged'),
                      'skipped': sum(1 for r in report if r['status'] != 'merged'),
                      'market_weight': a.market_weight, 'report': report},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

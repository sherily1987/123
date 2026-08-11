#!/usr/bin/env python3
"""把时间衰减候选写入输入，默认仅作为 lambda_prior 对照。"""
import argparse
import json
from pathlib import Path
from time_decay import build_decay_strength


# [中文功能] 给预览强度应用时间衰减并输出新预览
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--preview', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--days-half-life', type=float, default=30.0)
    ap.add_argument('--prior-weight', type=float, default=0.02)
    ap.add_argument('--activate', action='store_true', help='将候选写为lambda_prior；默认只写candidate metadata')
    a = ap.parse_args()
    data = json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
    prev = json.loads(Path(a.preview).read_text(encoding='utf-8-sig'))
    pm = {str(x.get('match_id')): x for x in prev.get('matches', [])}
    matches = data.get('matches') if isinstance(data, dict) and 'matches' in data else [data]
    report = []
    for m in matches:
        mid = str((m.get('sporttery_meta') or {}).get('match_id') or m.get('match_id') or '')
        p = pm.get(mid)
        if not p:
            report.append({'match_id': mid, 'status': 'no_preview'}); continue
        result = build_decay_strength(
            p.get('recent_home') or [], p.get('recent_away') or [],
            (p.get('team_ids') or {}).get('home'), (p.get('team_ids') or {}).get('away'),
            p.get('home'), p.get('away'), m.get('kickoff') or p.get('kickoff'), a.days_half_life)
        m.setdefault('time_decay_candidate', result)
        if a.activate and result.get('status') == 'VALID':
            m['lambda_prior'] = {
                'lambda_home': result['lambda_home'], 'lambda_away': result['lambda_away'],
                'weight': a.prior_weight, 'source': 'time_decay_recent_attack_defense',
                'days_half_life': a.days_half_life,
                'sample_legs': min(result['home']['sample'], result['away']['sample'])}
            m.setdefault('field_meta', {})['lambda_prior'] = {
                'status': 'VALID', 'source': 'time_decay_recent_attack_defense',
                'note': result['note']}
            m.setdefault('assumptions', []).append(
                f'时间衰减λ先验已启用，半衰期{a.days_half_life:g}天；系数未经回测拟合')
        report.append({'match_id': mid, 'status': result.get('status'),
                       'lambda': [result.get('lambda_home'), result.get('lambda_away')],
                       'activated': bool(a.activate and result.get('status') == 'VALID')})
    out = {'matches': matches} if isinstance(data, dict) and 'matches' in data else matches[0]
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'ok', 'output': a.output, 'report': report}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

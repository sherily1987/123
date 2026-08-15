#!/usr/bin/env python3
"""解析 predict.py 输出，生成 PPT/报告用的 parsed JSON。

用法: python parse_predictions.py <predict_txt> [<predict_txt2> ...] --out <parsed.json> --raw <raw.json>
从每个 .txt 提取每场的 audit JSON 行（build_audit_record 输出），
结合 raw 的联赛/开球信息生成汇总。"""

import json
import re
import sys


def extract_audit_lines(path):
    """predict.py 输出中每场一条 JSON（顶层含 direction/votes/strength 的 audit record）。"""
    rows = []
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and 'direction' in obj and 'all_votes' in obj and 'match_index' not in obj and 'status' not in obj:
            if obj.get('single_pick'):
                rows.append(obj)
    return rows


def main():
    args = [a for a in sys.argv[1:]]
    out_path = None
    raw_path = None
    start_index = 1
    txts = []
    i = 0
    while i < len(args):
        if args[i] == '--out':
            out_path = args[i + 1]; i += 2
        elif args[i] == '--raw':
            raw_path = args[i + 1]; i += 2
        elif args[i] == '--start-index':
            start_index = int(args[i + 1]); i += 2
        else:
            txts.append(args[i]); i += 1
    raw = json.load(open(raw_path, encoding='utf-8'))
    # audit 记录无场次标识，按输出顺序映射 raw[start_index-1:]

    audits = []
    for t in txts:
        audits.extend(extract_audit_lines(t))
    print(f'提取 audit 记录: {len(audits)} 条（起始序号 {start_index}）')

    parsed = []
    for j, a in enumerate(audits):
        meta = raw['matches'][start_index - 1 + j] if start_index - 1 + j < len(raw['matches']) else {}
        sp = a.get('single_pick') or {}
        evs = {}
        eva = (a.get('ev_recommendation') or {}).get('ev_analysis') or {}
        for d, v in eva.items():
            evs[d] = round(v['ev'], 4)
        num = meta.get('match_num', '')
        parsed.append({
            'num': num,
            'home': meta.get('home', a.get('home', '')),
            'away': meta.get('away', a.get('away', '')),
            'league': meta.get('league', ''),
            'kickoff': meta.get('kickoff_iso', ''),
            'dir': a.get('direction'),
            'alt': a.get('alt_direction'),
            'strength': round((a.get('strength') or 0) * 100),
            'votes': a.get('votes'),
            'total_votes': a.get('total_votes'),
            'sp': sp.get('pick'),
            'sp_conf': round((sp.get('confidence') or 0) * 100),
            'sp_skip': sp.get('skip'),
            'score': a.get('top_score_pref'),
            'score_prefs': a.get('score_prefs'),
            'ou25': a.get('top_ou25'),
            'hafu': a.get('top_hafu'),
            'evs': evs,
            'ev_action': (a.get('ev_recommendation') or {}).get('action'),
            'ev_reason': (a.get('ev_recommendation') or {}).get('reason'),
            'caution': a.get('caution'),
            'collapse_flags': a.get('collapse_flags'),
            'evidence_gap': a.get('evidence_gap'),
            'model_dirs': {k.split('/')[-1]: v.get('direction') for k, v in (a.get('individual') or {}).items()},
        })
    parsed.sort(key=lambda p: p['num'])
    if out_path:
        json.dump(parsed, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'写出: {out_path} 共 {len(parsed)} 场')
    else:
        print(json.dumps(parsed, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

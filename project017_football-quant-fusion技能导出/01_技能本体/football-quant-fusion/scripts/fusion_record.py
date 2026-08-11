#!/usr/bin/env python3
"""fusion_record — 融合登记（REBUILT 2026-08-02）

移植自 zu-yu-dashi-3/scripts/record_prediction.py，登记完整融合 payload。
match_id 优先用 sporttery_meta.match_id（如 sporttery-2040688），
回退为 comp/season/kickoff/队名拼接。同一 (match_id, snapshot_type) 幂等。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, 'H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts')
from backtest_lib import slug, sha, atomic_json, load_jsonl, append_jsonl

DEFAULT_STORE = 'H:\claude AI自媒体\project017_football-quant-fusion技能导出\03_共享数据\football-quant-fusion/backtest'


# [中文功能] 解析ISO时间字符串（兼容Z后缀）
def parse_dt(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


# [中文功能] 把融合预测输出登记进回测注册库
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True, help='registry-compatible core output (fusion payload)')
    ap.add_argument('--store', default=DEFAULT_STORE)
    ap.add_argument('--snapshot', default='unspecified')
    ap.add_argument('--allow-past', action='store_true')
    ap.add_argument('--predict', action='store_true', help='compatibility flag; prediction already generated')
    ap.add_argument('--replace-snapshot', action='store_true')
    a = ap.parse_args()

    inp = json.load(open(a.input, encoding='utf-8'))
    out = json.load(open(a.output, encoding='utf-8'))
    if isinstance(inp, dict) and 'matches' in inp:
        sys.exit('record one match per invocation; input must be a bare match dict')
    if out.get('fusion_status') != 'ok':
        sys.exit(f"refuse registration: fusion_status={out.get('fusion_status')}")

    ko = inp.get('kickoff')
    if not ko:
        sys.exit('kickoff required')
    kd = parse_dt(ko)
    if kd.tzinfo is None:
        sys.exit('kickoff timezone required')
    if kd.astimezone(timezone.utc) <= datetime.now(timezone.utc) and not a.allow_past:
        sys.exit('kickoff already passed; refuse retrospective prediction')

    sm = inp.get('sporttery_meta') or {}
    if sm.get('match_id'):
        mid = f"sporttery-{sm['match_id']}"
    else:
        comp = slug(inp.get('competition', inp.get('stage', 'match')))
        season = slug(inp.get('season', 'na'))
        ds = kd.strftime('%Y%m%dT%H%MZ')
        mid = f"{comp}_{season}_{ds}_{slug(inp['home'])}__{slug(inp['away'])}"

    # 版本戳修复（2026-08-03）：输出顶层没有 engine_version 字段（历史 bug 导致预测ID全落
    # vunknown，1445 条 8/2 回填样本无法版本归因）。改为取 core_output.engine_version
    # + 融合层版本（与 config/version_manifest.json 的 fusion_version 保持同步）。
    core_ver = str((out.get('core_output') or {}).get('engine_version')
                   or out.get('core_engine_version') or 'unknown')
    version = f"fusion-1.4.0-core-{core_ver}"
    vslug = slug(version)
    created = datetime.now(timezone.utc)
    pid = f"{mid}__v{vslug}__{created.strftime('%Y%m%dT%H%M%SZ')}__{slug(a.snapshot)}"

    if not a.replace_snapshot:
        for e in load_jsonl(Path(a.store) / 'registry.jsonl'):
            if e.get('match_id') != mid:
                continue
            ep = Path(e['path'])
            if not ep.exists():
                continue
            if json.load(open(ep, encoding='utf-8')).get('snapshot_type') == a.snapshot:
                print(json.dumps({
                    'status': 'skipped_duplicate_snapshot', 'match_id': mid,
                    'snapshot_type': a.snapshot, 'existing_prediction_id': e.get('prediction_id'),
                    'note': '同一比赛同一快照已登记；如确需覆盖用 --replace-snapshot'},
                    ensure_ascii=False))
                sys.exit(0)

    engine = Path('H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts/predict.py').read_bytes()
    rec = {
        'schema_version': 'fusion-1.0',
        'prediction_id': pid,
        'match_id': mid,
        'created_at': created.isoformat(),
        'snapshot_type': a.snapshot,
        'model': {'name': 'football-quant-fusion', 'version': version,
                  'engine_sha256': sha(engine)},
        'match': {'competition': inp.get('competition'), 'season': inp.get('season'),
                  'stage': inp.get('stage'), 'kickoff': ko,
                  'home': inp['home'], 'away': inp['away'],
                  'sporttery_meta': sm},
        'input': inp,
        'output': out,
        'hashes': {'input_sha256': sha(inp), 'output_sha256': sha(out)},
    }
    p = Path(a.store) / 'predictions' / created.strftime('%Y/%m') / (pid + '.json')
    if p.exists():
        sys.exit('prediction exists; no overwrite')
    atomic_json(p, rec)
    reg = Path(a.store) / 'registry.jsonl'
    prev = load_jsonl(reg)
    prevhash = prev[-1].get('entry_hash', '') if prev else ''
    entry = {'prediction_id': pid, 'match_id': mid, 'path': str(p),
             'record_hash': sha(rec), 'previous_hash': prevhash,
             'created_at': rec['created_at']}
    entry['entry_hash'] = sha(prevhash + entry['record_hash'])
    append_jsonl(reg, entry)
    print(json.dumps({'status': 'recorded', 'prediction_id': pid, 'match_id': mid,
                      'path': str(p)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

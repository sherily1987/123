#!/usr/bin/env python3
"""审计融合预测的独立比赛分母、版本纯度和玩法可结算数。"""
import argparse
import json
from pathlib import Path

from fusion_backtest import (dedupe_snapshot_rows, load_jsonl, resolve_path,
                             select_primary_rows, version_cohort)
from runtime_paths import backtest_store
from fusion_predict_core import build_identity


def main():
    ap = argparse.ArgumentParser()
    # 2026-08-16：默认值原指向外部套件（物理拷贝、比仓库内旧），改走仓库内唯一事实源
    ap.add_argument('--store', default=str(backtest_store()))
    ap.add_argument('--snapshot')
    ap.add_argument('--league')
    ap.add_argument('--snapshot-policy', choices=('latest_before_kickoff', 'prematch', 'closing'),
                    default='latest_before_kickoff')
    ap.add_argument('--output', required=True)
    a = ap.parse_args()
    root = Path(a.store)

    raw_rows = []
    missing_records = 0
    for entry in load_jsonl(root / 'registry.jsonl'):
        path = resolve_path(entry.get('path', ''), root)
        if not path.exists():
            missing_records += 1
            continue
        record = json.loads(path.read_text(encoding='utf-8-sig'))
        if a.snapshot and record.get('snapshot_type') != a.snapshot:
            continue
        if a.league and a.league not in str((record.get('match') or {}).get('competition', '')):
            continue
        model = record.get('model') or {}
        raw_rows.append({
            'match_id': record.get('match_id'),
            'snapshot_type': record.get('snapshot_type'),
            'prediction_id': record.get('prediction_id'),
            'created_at': record.get('created_at') or '',
            'prediction_as_of': record.get('prediction_as_of') or '',
            'version': model.get('version') if isinstance(model, dict) else str(model or ''),
            'model': model if isinstance(model, dict) else {},
            '_record': record,
        })

    snapshot_rows, dropped = dedupe_snapshot_rows(raw_rows)
    primary = select_primary_rows(snapshot_rows, a.snapshot_policy)
    current = build_identity()
    cohorts = {'current': 0, 'legacy': 0, 'unknown': 0}
    settled = 0
    settled_current = 0
    eligible = {k: 0 for k in ['1x2', 'hhad', 'ou25', 'btts', 'score', 'hafu', 'clv']}
    exclusions = {}
    for row in primary:
        cohort = version_cohort(row, current)
        cohorts[cohort] += 1
        record = row['_record']
        result_path = root / 'results' / (str(row['match_id']) + '.json')
        if not result_path.exists():
            exclusions['no_result'] = exclusions.get('no_result', 0) + 1
            continue
        result = json.loads(result_path.read_text(encoding='utf-8-sig'))
        score = result.get('score_90')
        if not isinstance(score, dict) or score.get('home') is None:
            exclusions['invalid_or_pending_result'] = exclusions.get('invalid_or_pending_result', 0) + 1
            continue
        settled += 1
        settled_current += int(cohort == 'current')
        output = record.get('output', {})
        core = output.get('core_output', output)
        forecast = output.get('forecast') or core.get('forecast') or {}
        if len(core.get('final_1x2_pct') or core.get('final_1x2') or []) == 3:
            eligible['1x2'] += 1
        if forecast.get('sporttery_hhad_3way') or core.get('sporttery_hhad_3way'):
            eligible['hhad'] += 1
        if forecast.get('ou_2_5') or core.get('ou_2_5'):
            eligible['ou25'] += 1
        if forecast.get('btts') or core.get('btts'):
            eligible['btts'] += 1
        if forecast.get('score_matrix') or core.get('score_matrix'):
            eligible['score'] += 1
        if forecast.get('hafu_model') or core.get('hafu_model'):
            eligible['hafu'] += 1
        if output.get('clv') or core.get('clv'):
            eligible['clv'] += 1

    report = {
        'schema_version': 'sample-audit-2.0',
        'snapshot': a.snapshot,
        'league': a.league,
        'snapshot_policy': a.snapshot_policy,
        'registered_snapshots': len(snapshot_rows),
        'registered_unique_matches': len({r['match_id'] for r in snapshot_rows}),
        'primary_evaluation_matches': len(primary),
        'registered_unique': len(primary),
        'deduped_duplicates': len(dropped),
        'missing_record_files': missing_records,
        'settled': settled,
        'by_version_cohort': cohorts,
        'eligible_by_market': eligible,
        'exclusions': exclusions,
        'current_identity': current,
        'calibration_gate': {
            'min_recalibration': 100,
            'threshold_review': 200,
            'current_version_settled': settled_current,
            'ready_for_recalibration': settled_current >= 100,
            'ready_for_threshold_review': settled_current >= 200,
        },
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

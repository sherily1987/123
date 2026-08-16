#!/usr/bin/env python3
"""fusion_record — 融合登记（REBUILT 2026-08-02）

移植自 zu-yu-dashi-3/scripts/record_prediction.py，登记完整融合 payload。
match_id 优先用 sporttery_meta.match_id（如 sporttery-2040688），
回退为 comp/season/kickoff/队名拼接。同一 (match_id, snapshot_type) 幂等。
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from runtime_paths import core_scripts_dir, data_root
from job_ticket import (
    identity_from,
    jobs_root,
    normalize_match_id,
    quant_from_fusion_output,
    upsert_job,
)

sys.path.insert(0, str(core_scripts_dir()))
from backtest_lib import slug, sha, atomic_json, load_jsonl, append_jsonl

DEFAULT_STORE = str(data_root() / "backtest")


# [中文功能] 解析ISO时间字符串（兼容Z后缀）
def parse_dt(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def raw_sha256(payload):
    """Hash the exact JSON file bytes, rather than its parsed representation."""
    return hashlib.sha256(payload).hexdigest()


def is_complete_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value.lower())


def formal_prediction_as_of(inp, kickoff):
    """Return a timezone-aware, strictly pre-kickoff formal as-of timestamp."""
    value = inp.get('prediction_as_of')
    if not value:
        sys.exit('prediction_as_of required for formal snapshot=prematch registration')
    try:
        as_of = parse_dt(value)
    except (TypeError, ValueError):
        sys.exit('prediction_as_of must be an ISO-8601 timestamp with timezone')
    if as_of.tzinfo is None:
        sys.exit('prediction_as_of timezone required for formal snapshot=prematch registration')
    if as_of.astimezone(timezone.utc) >= kickoff.astimezone(timezone.utc):
        sys.exit('prediction_as_of must be strictly before kickoff for formal snapshot=prematch registration')
    return value


def cohort_key(model_version, probability_signature, route, mode, llm_model_pool_sha256=None):
    """Stable cohort identity keyed by semantic model_version (primary anchor).

    语义版本 model_version 是 cohort 主锚（只有概率数值变更才 bump），
    probability_signature 是概率文件组的哈希审计。旧记录无这两个字段时
    传 'unknown'，天然落 legacy/unknown，不参与 current 归因。
    """
    parts = [
        str(model_version),
        str(probability_signature),
        str(route),
        str(mode),
    ]
    if llm_model_pool_sha256:
        parts.append(llm_model_pool_sha256)
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


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

    input_raw = Path(a.input).read_bytes()
    output_raw = Path(a.output).read_bytes()
    inp = json.loads(input_raw.decode('utf-8-sig'))
    out = json.loads(output_raw.decode('utf-8-sig'))
    if isinstance(inp, dict) and 'matches' in inp:
        sys.exit('record one match per invocation; input must be a bare match dict')
    if out.get('fusion_status') != 'ok':
        sys.exit(f"refuse registration: fusion_status={out.get('fusion_status')}")
    if out.get('research_only') is True:
        sys.exit('refuse registration: research_only output cannot enter formal registry')

    ko = inp.get('kickoff')
    if not ko:
        sys.exit('kickoff required')
    kd = parse_dt(ko)
    if kd.tzinfo is None:
        sys.exit('kickoff timezone required')
    if kd.astimezone(timezone.utc) <= datetime.now(timezone.utc) and not a.allow_past:
        sys.exit('kickoff already passed; refuse retrospective prediction')

    sm = inp.get('sporttery_meta') or {}
    mid = normalize_match_id(sm.get('match_id') or inp.get('match_id') or out.get('match_id'))
    if not mid:
        comp = slug(inp.get('competition', inp.get('stage', 'match')))
        season = slug(inp.get('season', 'na'))
        ds = kd.strftime('%Y%m%dT%H%MZ')
        mid = f"{comp}_{season}_{ds}_{slug(inp['home'])}__{slug(inp['away'])}"

    # 版本戳修复（2026-08-03）：输出顶层没有 engine_version 字段（历史 bug 导致预测ID全落
    # vunknown，1445 条 8/2 回填样本无法版本归因）。改为取 core_output.engine_version
    # + 融合层版本（与 config/version_manifest.json 的 fusion_version 保持同步）。
    build = out.get('build_identity') or {}
    core_ver = str(build.get('core_version')
                   or (out.get('core_output') or {}).get('engine_version')
                   or out.get('core_engine_version') or 'unknown')
    fusion_ver = str(build.get('fusion_version') or 'unknown')
    frozen_hashes = {
        key: build.get(key, 'unknown')
        for key in ('engine_bundle_sha256', 'prediction_code_sha256', 'config_sha256')
    }
    # 语义版本主锚 + 概率签名（版本管理方案：cohort 主键不再依赖全量字节哈希）
    model_version = str(build.get('model_version') or 'unknown')
    probability_signature = str(build.get('probability_signature') or 'unknown')
    governance_signatures = {
        key: build.get(key, 'unknown')
        for key in ('decision_policy_signature', 'evidence_pipeline_signature')
    }
    if a.snapshot == 'prematch':
        if not all(is_complete_sha256(value) for value in frozen_hashes.values()):
            sys.exit('complete build hashes required for formal snapshot=prematch registration')
        if not is_complete_sha256(probability_signature):
            sys.exit('complete probability_signature required for formal snapshot=prematch registration')
        if model_version == 'm2' and not all(
                is_complete_sha256(value) for value in governance_signatures.values()):
            sys.exit('complete decision/evidence signatures required for formal model m2 registration')
    created = datetime.now(timezone.utc)
    if a.snapshot == 'prematch':
        prediction_as_of = formal_prediction_as_of(inp, kd)
    else:
        prediction_as_of = inp.get('prediction_as_of') or created.isoformat()

    route = inp.get('route') or out.get('route') or 'unknown'
    mode = inp.get('mode') or out.get('mode') or 'unknown'
    llm_audit_keys = ('llm_model_pool_sha256', 'evidence_file_sha256')
    has_llm_audit = any(key in inp for key in llm_audit_keys)
    is_llm_registration = has_llm_audit or 'llm' in f'{route} {mode}'.lower()
    llm_audit = {key: inp.get(key) for key in llm_audit_keys}
    has_complete_llm_audit = all(is_complete_sha256(value) for value in llm_audit.values())
    if has_llm_audit and not has_complete_llm_audit:
        sys.exit('LLM audit hashes required: llm_model_pool_sha256 and evidence_file_sha256 must both be complete SHA-256 values')
    if a.snapshot == 'prematch' and is_llm_registration and not has_complete_llm_audit:
        sys.exit('LLM audit hashes required for formal production LLM prematch registration')
    version = f"fusion-{fusion_ver}-core-{core_ver}"
    vslug = slug(version)
    pid = f"{mid}__v{vslug}__{created.strftime('%Y%m%dT%H%M%SZ')}__{slug(a.snapshot)}"

    if a.snapshot == 'prematch' and a.replace_snapshot:
        sys.exit('prematch snapshots are immutable; use an explicit distinct experiment snapshot')
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

    engine = (core_scripts_dir() / "predict.py").read_bytes()
    rec = {
        'schema_version': 'fusion-1.1',
        'prediction_id': pid,
        'match_id': mid,
        'created_at': created.isoformat(),
        'prediction_as_of': prediction_as_of,
        'snapshot_type': a.snapshot,
        'route': route,
        'mode': mode,
        'cohort_key': cohort_key(model_version, probability_signature, route, mode,
                                 llm_audit['llm_model_pool_sha256']),
        'model': {
            'name': 'football-quant-fusion',
            'version': version,
            'fusion_version': fusion_ver,
            'core_version': core_ver,
            'fusion_schema_version': str(build.get('fusion_schema_version') or
                                         out.get('fusion_schema_version') or 'unknown'),
            'model_version': model_version,
            'probability_signature': probability_signature,
            'decision_policy_signature': governance_signatures['decision_policy_signature'],
            'evidence_pipeline_signature': governance_signatures['evidence_pipeline_signature'],
            'engine_sha256': sha(engine),
            'engine_bundle_sha256': frozen_hashes['engine_bundle_sha256'],
            'prediction_code_sha256': frozen_hashes['prediction_code_sha256'],
            'config_sha256': frozen_hashes['config_sha256'],
        },
        'match': {'competition': inp.get('competition'), 'season': inp.get('season'),
                  'stage': inp.get('stage'), 'kickoff': ko,
                  'home': inp['home'], 'away': inp['away'],
                  'sporttery_meta': sm},
        'input': inp,
        'output': out,
        'hashes': {
            'input_sha256': sha(inp), 'output_sha256': sha(out),
            'input_raw_sha256': raw_sha256(input_raw), 'output_raw_sha256': raw_sha256(output_raw),
        },
    }
    if has_llm_audit:
        rec.update(llm_audit)
    if is_llm_registration and not has_complete_llm_audit:
        rec['llm_registration_class'] = 'experimental_unverified'
    elif is_llm_registration:
        rec['llm_registration_class'] = 'audited'
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
    job_file = None
    try:
        ident = identity_from(inp, out)
        ident['match_id'] = mid
        job_file = str(upsert_job(
            jobs_root(Path(a.store)),
            ident,
            input_obj=inp,
            quant=quant_from_fusion_output(out, prediction_id=pid),
        ))
    except Exception as exc:
        job_file = f"job_upsert_failed:{exc}"
    print(json.dumps({'status': 'recorded', 'prediction_id': pid, 'match_id': mid,
                      'path': str(p), 'job': job_file}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

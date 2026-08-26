#!/usr/bin/env python3
"""fusion_record — 融合登记（REBUILT 2026-08-02）

移植自 zu-yu-dashi-3/scripts/record_prediction.py，登记完整融合 payload。
match_id 优先用 sporttery_meta.match_id（如 sporttery-2040688），
回退为 comp/season/kickoff/队名拼接。同一 (match_id, snapshot_type) 幂等。
"""
import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from release_governance import ReleaseGovernanceError, assert_output_matches_release_lock
from direction_policy import build_direction_policy, load_policy

HERE = Path(__file__).resolve().parent
LOCK_FILE = HERE.parent / 'config' / 'release_lock.json'

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


def _final_probabilities(out):
    """Read the registry-compatible probability vector without deriving it."""
    direct = out.get('final_1x2_pct')
    if direct is not None:
        return direct
    forecast = out.get('forecast') or {}
    if forecast.get('final_1x2_pct') is not None:
        return forecast.get('final_1x2_pct')
    core_output = out.get('core_output') or {}
    return core_output.get('final_1x2_pct')


def _aware_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = parse_dt(value.strip())
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _direction_policy_claims(value, path='$'):
    """Collect every persisted direction-policy copy with its JSON path."""
    claims = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f'{path}.{key}'
            if key == 'direction_policy':
                claims.append({'path': child_path, 'value': child})
            claims.extend(_direction_policy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_direction_policy_claims(child, f'{path}[{index}]'))
    return claims


def _direction_claims_sha256(claims):
    hash_input = claims or [{'path': '$.direction_policy', 'value': '<missing>'}]
    canonical = json.dumps(
        hash_input, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=True,
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def _replace_direction_policies(value, replacement):
    """Replace all nested policy claims in a JSON-compatible object in place."""
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key == 'direction_policy':
                value[key] = copy.deepcopy(replacement)
            else:
                _replace_direction_policies(child, replacement)
    elif isinstance(value, list):
        for child in value:
            _replace_direction_policies(child, replacement)


def _direction_validation_error(candidate, expected, *, probabilities,
                                build, prediction_as_of, kickoff):
    """Return a stable error code, or None when a policy is safe to persist."""
    if not isinstance(candidate, dict):
        return 'direction_policy_must_be_object'
    if set(candidate) != set(expected):
        return 'schema_fields_mismatch'
    raw_probabilities = candidate.get('probabilities')
    expected_probabilities = (
        dict(zip(('H', 'D', 'A'), probabilities))
        if isinstance(probabilities, (list, tuple)) and len(probabilities) == 3
        else None
    )
    if raw_probabilities != expected_probabilities:
        return 'probabilities_mismatch'
    if (candidate.get('model_version') != build.get('model_version')
            or candidate.get('probability_signature') != build.get('probability_signature')):
        return 'model_identity_mismatch'
    policy_time = _aware_datetime(candidate.get('prediction_as_of'))
    if policy_time is None or policy_time >= kickoff.astimezone(timezone.utc):
        return 'prediction_as_of_not_aware_prematch'
    if candidate.get('prediction_as_of') != prediction_as_of:
        return 'prediction_as_of_mismatch'
    if candidate.get('schema_version') != expected.get('schema_version'):
        return 'schema_version_mismatch'
    if candidate.get('rule_version') != expected.get('rule_version'):
        return 'rule_version_mismatch'
    if candidate.get('policy_version') != expected.get('policy_version'):
        return 'policy_version_mismatch'
    signature = candidate.get('decision_policy_signature')
    if (not is_complete_sha256(signature)
            or signature != expected.get('decision_policy_signature')):
        return 'decision_policy_signature_mismatch'
    components = candidate.get('decision_policy_signature_components')
    if (not isinstance(components, dict)
            or set(components) != {'policy_canonical_sha256', 'implementation_sha256'}
            or not all(is_complete_sha256(value) for value in components.values())
            or components != expected.get('decision_policy_signature_components')):
        return 'decision_policy_signature_components_mismatch'
    for field in ('classification', 'primary_direction', 'alternative_direction',
                  'status', 'probability_unit', 'probability_source', 'trigger',
                  'gap_pp', 'reason'):
        if candidate.get(field) != expected.get(field):
            return f'{field}_mismatch'
    return None


def _unavailable_direction_policy(expected, *, error, rejected_sha256):
    """Remove every direction claim while retaining auditable policy identity."""
    unavailable = copy.deepcopy(expected) if isinstance(expected, dict) else {}
    unavailable.update({
        'status': 'UNAVAILABLE',
        'classification': 'UNAVAILABLE',
        'primary_direction': None,
        'alternative_direction': None,
        'trigger': None,
        'gap_pp': None,
        'reason': 'validation_error',
        'validation_error': error,
        'rejected_direction_policy_sha256': rejected_sha256,
    })
    return unavailable


def validate_direction_registration(out, *, build, prediction_as_of, kickoff):
    """Validate a supplied policy; never synthesize a missing historical one."""
    probabilities = _final_probabilities(out)
    claims = _direction_policy_claims(out)
    rejected_sha256 = _direction_claims_sha256(claims)
    try:
        policy_config = load_policy()
    except Exception as exc:
        return 'UNAVAILABLE', _unavailable_direction_policy(
            {}, error=f'policy_validation_failed:{type(exc).__name__}',
            rejected_sha256=rejected_sha256,
        )
    activation = _aware_datetime(policy_config.get('activation_timestamp'))
    prediction_time = _aware_datetime(prediction_as_of)
    if activation is None or prediction_time is None:
        return 'UNAVAILABLE', _unavailable_direction_policy(
            {}, error='policy_activation_timestamp_invalid',
            rejected_sha256=rejected_sha256,
        )

    top_level_present = isinstance(out, dict) and 'direction_policy' in out
    if not top_level_present and not claims and prediction_time < activation:
        return 'NOT_REGISTERED', None

    expected = build_direction_policy(
        probabilities,
        prediction_as_of=prediction_as_of,
        model_identity=build,
        policy=policy_config,
    )
    if not top_level_present:
        error = ('direction_policy_top_level_missing' if claims
                 else 'direction_policy_missing_after_activation')
        return 'UNAVAILABLE', _unavailable_direction_policy(
            expected, error=error, rejected_sha256=rejected_sha256,
        )
    if expected.get('status') != 'AVAILABLE':
        return 'UNAVAILABLE', _unavailable_direction_policy(
            expected, error='expected_policy_unavailable',
            rejected_sha256=rejected_sha256,
        )
    for claim in claims:
        error = _direction_validation_error(
            claim['value'], expected, probabilities=probabilities, build=build,
            prediction_as_of=prediction_as_of, kickoff=kickoff,
        )
        if error is not None:
            return 'UNAVAILABLE', _unavailable_direction_policy(
                expected, error=error, rejected_sha256=rejected_sha256,
            )
    return 'REGISTERED', copy.deepcopy(expected)


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
        try:
            assert_output_matches_release_lock(build, LOCK_FILE)
        except ReleaseGovernanceError as exc:
            sys.exit(str(exc))
    created = datetime.now(timezone.utc)
    # Every record in the formal registry, including an explicitly named
    # T-minus snapshot, must prove it was generated before kickoff.  Labels
    # are not a waiver for the no-future-leakage boundary.
    prediction_as_of = formal_prediction_as_of(inp, kd)
    direction_policy_status, registered_direction_policy = validate_direction_registration(
        out, build=build, prediction_as_of=prediction_as_of, kickoff=kd,
    )
    persisted_out = copy.deepcopy(out)
    if registered_direction_policy is not None:
        _replace_direction_policies(persisted_out, registered_direction_policy)
        persisted_out['direction_policy'] = copy.deepcopy(registered_direction_policy)

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
    # 同一秒内的跨版本重预测必须物理分文件；否则不同概率 cohort 会碰撞到
    # 同一路径，即使登记去重已正确放行也无法留档。
    cohort_slug = f"m{slug(model_version)}-p{slug(probability_signature[:12])}"
    pid = (f"{mid}__v{vslug}__{cohort_slug}__{created.strftime('%Y%m%dT%H%M%SZ')}"
           f"__{slug(a.snapshot)}")

    if a.snapshot == 'prematch' and a.replace_snapshot:
        sys.exit('prematch snapshots are immutable; use an explicit distinct experiment snapshot')
    if not a.replace_snapshot:
        for e in load_jsonl(Path(a.store) / 'registry.jsonl'):
            if e.get('match_id') != mid:
                continue
            ep = Path(e['path'])
            if not ep.exists():
                continue
            existing = json.load(open(ep, encoding='utf-8'))
            existing_model = existing.get('model') or {}
            same_probability_version = (
                str(existing_model.get('model_version') or 'unknown') == model_version
                and str(existing_model.get('probability_signature') or 'unknown') == probability_signature
            )
            if existing.get('snapshot_type') == a.snapshot and same_probability_version:
                print(json.dumps({
                    'status': 'skipped_duplicate_snapshot', 'match_id': mid,
                    'snapshot_type': a.snapshot, 'existing_prediction_id': e.get('prediction_id'),
                    'note': '同一比赛同一快照同一概率版本已登记；如确需覆盖用 --replace-snapshot'},
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
        'output': persisted_out,
        'direction_policy_status': direction_policy_status,
        'hashes': {
            'input_sha256': sha(inp), 'output_sha256': sha(out),
            'persisted_output_sha256': sha(persisted_out),
            'input_raw_sha256': raw_sha256(input_raw), 'output_raw_sha256': raw_sha256(output_raw),
        },
    }
    if registered_direction_policy is not None:
        rec['direction_policy'] = registered_direction_policy
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
        ident = identity_from(inp, persisted_out)
        ident['match_id'] = mid
        job_file = str(upsert_job(
            jobs_root(Path(a.store)),
            ident,
            input_obj=inp,
            quant=quant_from_fusion_output(persisted_out, prediction_id=pid),
        ))
    except Exception as exc:
        job_file = f"job_upsert_failed:{exc}"
    print(json.dumps({'status': 'recorded', 'prediction_id': pid, 'match_id': mid,
                      'path': str(p), 'job': job_file}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

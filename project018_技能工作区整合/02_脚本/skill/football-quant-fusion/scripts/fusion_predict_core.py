#!/usr/bin/env python3
"""Football Quant Fusion: one numerical outlet plus decision audit.

本文件由 fusion_predict_core.cpython-312.pyc 反编译重建（2026-08-02），
行为与字节码一致；并顺带修复了字节码里的两个缺陷：
1. 模块级 market_freshness_meta 未赋值导致的 NameError（此处显式初始化为 {}）；
2. CORE_DIR 默认值由容器路径改为本机路径（仍支持 FUSION_CORE_DIR 覆盖）。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

from production_router import load_event_rows, route_matches
from job_ticket import stamp_identity

from runtime_paths import core_scripts_dir, data_root

CORE_DIR = core_scripts_dir()
CORE_FILE = CORE_DIR / "predict.py"
HERE = Path(__file__).resolve().parent
WEIGHTS_FILE = HERE.parent / "config" / "market_weights.json"
VERSION_FILE = HERE.parent / "config" / "version_manifest.json"
EXPECTED_MAJOR_MINOR = "3.4"
ADJUSTMENT_FIELDS = frozenset(
    {
        "lambda_prior", "home_adv",
        "attack_motive_home", "attack_motive_away",
        "attack_absence_home", "attack_absence_away",
        "defense_absence_home", "defense_absence_away",
        "gk_absence_home", "gk_absence_away",
        "rotation_home", "rotation_away",
        "defense_risk_home", "defense_risk_away",
    }
)
SEVERE_PREFIXES = ("DOUBLE_HOME_ADV", "EXTREME_LAMBDA_ASYMMETRY", "EXTREME_CLEAN_SHEET")
DERIVATIVE_PREFIXES = ("TTG_SCORE_CONFLICT", "HHAD_CONFLICT")
# 字节码缺陷修复：market_freshness 分支曾引用未赋值的模块级变量
market_freshness_meta = {}

EVIDENCE_FIELDS = ("team_stats", "recent_form", "injury", "suspensions", "starting_xi")
# PREDICTED is an explicit, time-stamped probable-XI state.  It clears the
# field-presence gate but remains distinguishable from an official XI so
# downstream reports can apply a risk tag and refresh it near kickoff.
_EVIDENCE_VALID = {"VALID", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING", "IMAGE_EXTRACTED", "PROXY_XG", "EXPLICIT_XG"}
_EVIDENCE_BAD = {"MISSING", "UNAVAILABLE", "UNVERIFIED", "OUTDATED", "ASSUMED", "POST_KICKOFF"}


def _parse_evidence_time(value):
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _evidence_candidate(data, name, api_features, api):
    direct = data.get(name)
    evidence = data.get("evidence_chain") or data.get("evidence") or {}
    meta = data.get("field_meta") or {}
    candidate = direct if direct not in (None, "", [], {}) else evidence.get(name)
    if candidate in (None, "", [], {}):
        candidate = meta.get(name)
    if candidate in (None, "", [], {}):
        mapped = {
            "team_stats": ("team_strength", "rolling_statistics", "standings"),
            "recent_form": ("rolling_statistics",),
            "injury": (),
            "suspensions": (),
            "starting_xi": ("lineups",),
        }
        for key in mapped.get(name, ()):
            candidate = api_features.get(key)
            if candidate not in (None, "", [], {}):
                break
    if candidate in (None, "", [], {}):
        if name in ("starting_xi", "suspensions"):
            candidate = (api.get("lineups") if isinstance(api, dict) else None)
        elif name == "injury":
            candidate = meta.get("injury_home") or meta.get("injury_away")
    return candidate


def _evidence_entry(data, name, api_features, api, kickoff):
    candidate = _evidence_candidate(data, name, api_features, api)
    meta = (data.get("field_meta") or {}).get(name) or {}
    if not isinstance(meta, dict):
        meta = {}
    if isinstance(candidate, dict):
        status = str(candidate.get("status") or candidate.get("state") or meta.get("status") or "").upper()
        refreshed = (candidate.get("refreshed_at") or candidate.get("updated_at") or
                     candidate.get("observed_at") or candidate.get("collected_at") or
                     candidate.get("as_of"))
        source_id = candidate.get("source_id") or candidate.get("source") or candidate.get("provider")
        source_url = candidate.get("source_url") or candidate.get("url")
    else:
        status = str(meta.get("status") or "").upper()
        refreshed = meta.get("refreshed_at") or meta.get("updated_at") or meta.get("observed_at") or meta.get("collected_at")
        source_id = meta.get("source_id") or meta.get("source") or meta.get("provider")
        source_url = meta.get("source_url") or meta.get("url")
    if isinstance(refreshed, dict):
        refreshed = refreshed.get("collected_at") or refreshed.get("observed_at") or refreshed.get("as_of")
    present = candidate not in (None, "", [], {})
    reasons = []
    if not status and present:
        status = "VALID"
    if not status:
        status = "MISSING"
    refreshed_dt = _parse_evidence_time(refreshed)
    age_hours = None
    kickoff_dt = _parse_evidence_time(kickoff)
    if refreshed_dt:
        reference = kickoff_dt or datetime.now(timezone.utc)
        age_hours = round(max(0.0, (reference - refreshed_dt).total_seconds() / 3600.0), 2)
        if kickoff_dt and refreshed_dt > kickoff_dt:
            status = "POST_KICKOFF"
            reasons.append("POST_KICKOFF")
    elif present:
        status = "UNVERIFIED"
        reasons.append("REFRESHED_AT_MISSING")
    if status in _EVIDENCE_BAD or status not in _EVIDENCE_VALID:
        if status not in reasons:
            reasons.append(status)
    return {
        "status": status,
        "source_id": source_id or "unknown",
        "source_url": source_url,
        "refreshed_at": refreshed,
        "age_hours": age_hours,
        "missing_reason": ";".join(reasons) if reasons else None,
    }


def build_evidence_audit(data):
    """统一赛前证据审计；缺关键字段时明确 evidence_gap，不作常识回填。"""
    api_features = data.get("api_features") or {}
    api = data.get("api_football") or {}
    match_meta = data.get("match") if isinstance(data.get("match"), dict) else {}
    kickoff = data.get("kickoff") or data.get("kickoff_at") or match_meta.get("kickoff")
    entries = {name: _evidence_entry(data, name, api_features, api, kickoff) for name in EVIDENCE_FIELDS}
    missing = [name for name, entry in entries.items() if entry["status"] not in _EVIDENCE_VALID]
    reasons = []
    for name in missing:
        reason = entries[name].get("missing_reason") or entries[name].get("status") or "MISSING"
        reasons.append(f"{name.upper()}_{reason}")
    ages = [v["age_hours"] for v in entries.values() if v.get("age_hours") is not None]
    return {
        "schema_version": "evidence-audit-1.0",
        "critical_fields": list(EVIDENCE_FIELDS),
        "entries": entries,
        "missing_fields": missing,
        "evidence_gap": bool(missing),
        "evidence_gap_reasons": reasons,
        "evidence_status": "GAP" if missing else "OK",
        "evidence_freshness_hours": max(ages) if ages else None,
        "kickoff": kickoff,
        "market_source_policy": {
            "HAD": "Sporttery official odds",
            "TTG": "Sporttery official odds",
            "HAFU": "Sporttery official odds",
            "CRS": "Sporttery official odds",
            "international_odds": "research_only",
        },
    }


def _hash_files(paths):
    """按文件名+内容生成稳定的组合SHA256；缺失文件也进入哈希。"""
    digest = hashlib.sha256()
    for path in sorted((Path(p) for p in paths), key=lambda p: str(p).lower()):
        digest.update(str(path.name).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def build_identity():
    """返回本次预测可复现所需的版本、代码包和配置哈希。"""
    policy_file = HERE.parent / "config" / "recommendation_policy.json"
    manifest = {}
    if VERSION_FILE.exists():
        manifest = json.loads(VERSION_FILE.read_text(encoding="utf-8-sig"))
    prediction_code = [HERE / "fusion_predict.py", HERE / "fusion_predict_core.py",
                       HERE / "recommendation_policy.py", HERE / "apifootball_model_features.py",
                       HERE / "production_router.py"]
    core_code = [CORE_FILE, CORE_DIR / "market_fit.py", CORE_DIR / "odds_methods.py"]
    config_files = [VERSION_FILE, WEIGHTS_FILE, policy_file]
    # 概率签名：只哈希「影响概率数值输出」的文件组，与全量 engine_bundle 分离。
    # 语义版本 model_version 作 cohort 主锚，概率签名作审计（见版本管理方案）。
    probability_code = [HERE / "fusion_predict_core.py", HERE / "production_router.py",
                        CORE_FILE, CORE_DIR / "market_fit.py",
                        CORE_DIR / "odds_methods.py", CORE_DIR / "team_strength.py"]
    probability_config = [WEIGHTS_FILE]
    decision_policy_files = [HERE / "recommendation_policy.py", policy_file]
    evidence_pipeline_files = [HERE / "sales_day_collect.py", HERE / "apifootball_model_features.py",
                               HERE / "mcp_model_adapter.py"]
    return {
        "skill_version": str(manifest.get("skill_version") or "unknown"),
        "fusion_version": str(manifest.get("fusion_version") or "unknown"),
        "core_version": str(manifest.get("core_version") or "unknown"),
        "fusion_schema_version": str(manifest.get("fusion_schema_version") or "1.3.0"),
        "model_version": str(manifest.get("model_version") or "unknown"),
        "probability_signature": _hash_files(probability_code + probability_config),
        "decision_policy_signature": _hash_files(decision_policy_files),
        "evidence_pipeline_signature": _hash_files(evidence_pipeline_files),
        "prediction_code_sha256": _hash_files(prediction_code),
        "config_sha256": _hash_files(config_files),
        "engine_bundle_sha256": _hash_files(prediction_code + core_code + config_files),
    }

# 兼容旧入口：允许环境变量覆盖核心引擎目录
_override = os.environ.get("FUSION_CORE_DIR")
if _override:
    CORE_DIR = Path(_override).resolve()
    CORE_FILE = CORE_DIR / "predict.py"
    _candidate = CORE_DIR.parent / "config" / "version_manifest.json"
    if _candidate.exists():
        VERSION_FILE = _candidate


def load_core():
    """加载核心引擎 predict.py，返回 (module, version)。"""
    if not CORE_FILE.exists():
        raise RuntimeError(f"core engine missing: {CORE_FILE}")
    sys.path.insert(0, str(CORE_DIR))
    spec = importlib.util.spec_from_file_location("fusion_core_predict", CORE_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    version = str(getattr(module, "ENGINE_VERSION", "unknown"))
    if not version.startswith(EXPECTED_MAJOR_MINOR + "."):
        raise RuntimeError(f"unsupported core engine {version}; expected {EXPECTED_MAJOR_MINOR}.x")
    return module, version


def load_default_market_weights():
    """读取 config/market_weights.json；缺失或异常返回 None。"""
    if not WEIGHTS_FILE.exists():
        return None
    try:
        cfg = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        weights = cfg.get("weights")
        if not isinstance(weights, dict):
            return None
        return {
            "weights": weights,
            "profile": cfg.get("profile") or "default_unfitted",
            "status": cfg.get("status") or "UNFITTED",
            "source": str(WEIGHTS_FILE),
            "note": cfg.get("note") or "auto-loaded default market weights",
        }
    except Exception:
        return None


def ensure_market_weights(data):
    """给输入补市场权重配置；返回 (data, weights_loaded)。"""
    if data.get("market_weights"):
        meta = dict(data.get("market_weights_meta") or {})
        meta.setdefault("source", "input")
        data["market_weights_meta"] = meta
        return data, False
    loaded = load_default_market_weights()
    if not loaded:
        return data, False
    data = dict(data)
    data["market_weights"] = loaded["weights"]
    data["market_weights_meta"] = {
        "profile": loaded["profile"],
        "status": loaded["status"],
        "source": loaded["source"],
        "note": loaded["note"],
    }
    assumptions = list(data.get("assumptions") or [])
    assumptions.append(f"已自动加载市场权重配置 {loaded['profile']}（{loaded['status']}）")
    data["assumptions"] = assumptions
    return data, True


def parse_score_key(key):
    """把比分键规范化：'1：2'/'1:2' → '1-2'；'其他' 或非法返回 None。"""
    text = str(key).replace("：", "-").replace(":", "-").strip()
    if text in ("胜其他", "平其他", "负其他", "other_home", "other_draw", "other_away"):
        return None
    if "-" not in text:
        return None
    a, b = text.split("-", 1)
    try:
        return f"{int(a)}-{int(b)}"
    except Exception:
        return None


def crs_overlap_audit(data, core_out, top_n=3):
    """CRS 与模型 Top 比分重合度审计；CRS 只作相对排序对照。"""
    crs = data.get("crs") or data.get("crs_market") or data.get("sporttery_crs")
    if not crs:
        return None
    if isinstance(crs, dict) and "scores" in crs:
        crs = crs.get("scores") or {}
    pairs = []
    if isinstance(crs, list):
        for row in crs:
            if not isinstance(row, dict):
                continue
            sc = parse_score_key(row.get("score") or row.get("name"))
            od = row.get("odds") or row.get("price")
            if sc is None or od in (None, ""):
                continue
            try:
                pairs.append((sc, float(od)))
            except Exception:
                continue
    elif isinstance(crs, dict):
        for k, v in crs.items():
            sc = parse_score_key(k)
            if sc is None:
                continue
            try:
                pairs.append((sc, float(v)))
            except Exception:
                continue
    else:
        return None
    if not pairs:
        return None
    crs_top = [sc for sc, _ in sorted(pairs, key=lambda x: x[1])[:top_n]]
    model_top = []
    for row in (core_out.get("top_scores") or [])[:top_n]:
        sc = parse_score_key(row.get("score") if row else {})
        if sc:
            model_top.append(sc)
    if not model_top:
        return None
    inter = sorted(set(crs_top) & set(model_top))
    overlap = round(len(inter) / float(top_n), 3)
    out = {
        "top_n": top_n,
        "crs_top": crs_top,
        "model_top": model_top,
        "overlap_count": len(inter),
        "overlap_ratio": overlap,
        "intersection": inter,
        "method": "rank_overlap_by_lowest_odds",
        "note": "CRS样本空间不完整，仅作相对排序重合度审计，不直接归一化进拟合。",
    }
    if overlap <= 0:
        out["flag"] = "CRS_SCORE_LOW_OVERLAP"
    elif overlap < 0.34:
        out["flag"] = "CRS_SCORE_WEAK_OVERLAP"
    return out


def supplied_adjustments(data):
    """返回实际提供了数值修正的调整字段集合（排除 0/1/None/False 等无效值）。"""
    out = set()
    for field in ADJUSTMENT_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "lambda_prior" or value not in (None, 0, 0.0, 1, 1.0, False):
            out.add(field)
    return out


def ledger_audit(data):
    """审计 adjustment_ledger 完整性与系统生成条目。"""
    ledger = data.get("adjustment_ledger") or []
    ledger_fields = {x.get("field") for x in ledger if isinstance(x, dict)}
    meta = data.get("field_meta") or {}
    system_entries = []
    if "lambda_prior" in supplied_adjustments(data) and "lambda_prior" not in ledger_fields:
        lm = meta.get("lambda_prior") or {}
        if lm.get("source"):
            system_entries.append({
                "field": "lambda_prior",
                "fact": "官方前瞻近况攻防均值生成λ软先验",
                "source": lm.get("source"),
                "mapping_basis": "merge_preview soft prior",
                "calibration": "UNFITTED",
                "system_generated": True,
                "note": lm.get("note"),
            })
            ledger_fields.add("lambda_prior")
    unledgered = sorted(supplied_adjustments(data) - ledger_fields)
    invalid = []
    for i, item in enumerate(ledger):
        if not isinstance(item, dict):
            invalid.append(f"ledger[{i}] is not an object")
            continue
        missing = [k for k in ("field", "fact", "source", "mapping_basis", "calibration") if not item.get(k)]
        if missing:
            invalid.append(f"ledger[{i}] missing {','.join(missing)}")
    status = "ok" if not unledgered and not invalid else "warning"
    return {
        "entries": ledger,
        "system_generated_entries": system_entries,
        "unledgered_adjustments": unledgered,
        "invalid_entries": invalid,
        "status": status,
    }


def range_width(sensitivity, idx):
    """取 sensitivity 中某项区间宽度（高-低，1 位小数）。"""
    key = ("home_range_pct", "draw_range_pct", "away_range_pct")[idx]
    values = sensitivity.get(key) or [0, 0]
    return round(float(values[1]) - float(values[0]), 1)


def decision(core_out, ledger, data=None):
    """融合决策：状态、方向、不确定性分级与动作。"""
    probs = core_out.get("final_1x2_pct") or []
    if len(probs) != 3:
        return {"status": "UNAVAILABLE", "reason": "missing final_1x2_pct"}
    labels = ["H", "D", "A"]
    order = sorted(range(3), key=lambda i: probs[i], reverse=True)
    top, second = order[0], order[1]
    sensitivity = core_out.get("sensitivity") or {}
    result_widths = [range_width(sensitivity, i) for i in range(3)]
    width = result_widths[top]

    def _width(key):
        vals = sensitivity.get(key)
        if not vals or len(vals) != 2 or vals[0] is None or vals[1] is None:
            return 0.0
        return round(max(0.0, float(vals[1]) - float(vals[0])), 1)

    derivative_widths = {
        "ou_2_5": _width("over_2_5_range_pct"),
        "btts_yes": _width("btts_yes_range_pct"),
        "ah_effective_cover": _width("ah_effective_cover_range_pct"),
    }
    usable = [
        v for k, v in derivative_widths.items()
        if not (k == "ah_effective_cover" and v == 0.0 and not sensitivity.get("ah_effective_cover_range_pct"))
    ]
    derivative_width = max(usable) if usable else 0.0
    flags = list(core_out.get("reliability_flags") or [])
    if ledger["unledgered_adjustments"]:
        flags.append("UNLEDGERED_ADJUSTMENT: numeric adjustment lacks evidence ledger")
    severe = [f for f in flags if f.startswith(SEVERE_PREFIXES)]
    derivative_risks = [f for f in flags if f.startswith(DERIVATIVE_PREFIXES)]
    hhad = core_out.get("sporttery_hhad_3way") or {}
    hhad_probs = hhad.get("model_prob_pct") or []
    if len(hhad_probs) == 3 and float(hhad.get("line", 999)) == -1.0 and hhad_probs[1] >= 18.0:
        flags.append(f"ONE_GOAL_WIN_RISK: HHAD -1让平概率={hhad_probs[1]}%，主队一球胜会结算让平，不得单推让负。")
        derivative_risks.append(flags[-1])
    quality = float((core_out.get("quality") or {}).get("overall_pct") or 0)
    mode = core_out.get("mode")
    edge = None
    significant = None
    if mode != "market_only" and core_out.get("edge_vs_market_pp"):
        key = ("home_pp", "draw_pp", "away_pp")[top]
        edge = float(core_out["edge_vs_market_pp"][key])
        significant = abs(edge) > width
    unfitted = any(f.startswith("UNFITTED_FUSION") for f in flags)
    dependency = float(core_out.get("market_dependency_pct") or 0)
    if severe or quality < 35 or ledger["invalid_entries"] or ledger["unledgered_adjustments"]:
        status = "AVOID_DATA_RISK"
    elif unfitted and mode != "market_only" and (not significant or dependency >= 80):
        status = "UNFITTED_NO_VALUE"
    elif mode == "market_only":
        status = "MARKET_BASELINE"
    elif not significant:
        status = "EDGE_BELOW_UNCERTAINTY"
    else:
        status = "EDGE_REVIEWABLE"
    gap = round(float(probs[top]) - float(probs[second]), 1)
    if status in ("AVOID_DATA_RISK", "UNFITTED_NO_VALUE", "EDGE_BELOW_UNCERTAINTY"):
        action = "观察/回避，不形成独立单选或胆"
    elif status == "MARKET_BASELINE":
        action = f"市场主方向 {labels[top]}，仅作基线"
    elif gap < 8 and width > 12:
        action = f"双选 {labels[top]} {labels[second]}"
    else:
        action = f"单选候选 {labels[top]}"
    if derivative_risks or derivative_width >= 12:
        action += "；比分/大小球/BTTS/让球需单独降级"
    result_uncertainty = "高" if width > 15 else ("中" if width > 8 else "低")
    derivative_uncertainty = "高" if derivative_width >= 15 else ("中" if (derivative_width >= 8 or derivative_risks) else "低")
    uncertainty = (
        "高" if (severe or result_uncertainty == "高" or derivative_uncertainty == "高")
        else ("中" if (result_uncertainty == "中" or derivative_uncertainty == "中") else "低")
    )
    return {
        "status": status,
        "probability_rank": [{"outcome": labels[i], "prob_pct": probs[i]} for i in order],
        "primary_outcome": labels[top],
        "top_gap_pp": gap,
        "result_sensitivity_widths_pp": {labels[i]: result_widths[i] for i in range(3)},
        "sensitivity_width_pp": width,
        "derivative_market_widths_pp": derivative_widths,
        "derivative_market_max_width_pp": derivative_width,
        "result_uncertainty_level": result_uncertainty,
        "derivative_uncertainty_level": derivative_uncertainty,
        "uncertainty_level": uncertainty,
        "edge_pp_for_primary": edge,
        "edge_significant_vs_sensitivity": significant,
        "market_dependency_pct": dependency,
        "unfitted_fusion": unfitted,
        "action": action,
        "severe_flags": severe,
        "derivative_market_risks": derivative_risks,
        "note": "数据质量、结果概率、模型不确定性与决策价值彼此独立；衍生市场不继承1X2置信度。",
    }


def clean_process_tags(tags):
    """处理流程标签：EXPLICIT_XG 重映射、去重、保留顺序。"""
    tags = list(tags or [])
    out = []
    for t in tags:
        if t == "EXPLICIT_XG":
            out.append("POST_FIT_LAMBDA_REENTRY")
        else:
            out.append(t)
    if any(x in out for x in ("PROXY_XG", "MULTI_MARKET_XG", "POST_FIT_LAMBDA_REENTRY")):
        out = [x for x in out if x != "EXPLICIT_XG"]
    return list(dict.fromkeys(out))


def build_goal_rate(out):
    """构造 goal_rate（含 kind/source_tags/real_event_xg）。"""
    tags = clean_process_tags(out.get("xg_tags"))
    xg = out.get("xg")
    # POST_FIT_LAMBDA_REENTRY = 显式 λ 在拟合后重入（原 EXPLICIT_XG 的流程标签），属模型 λ 而非市场代理
    is_model = any(str(t) in ("EXPLICIT_XG", "EXPLICIT_XG_PRIOR", "POST_FIT_LAMBDA_REENTRY") for t in tags)
    if not is_model and any(str(t).startswith(("PROXY_XG", "MULTI_MARKET_XG")) for t in tags):
        kind = "proxy_lambda"
    elif is_model or xg is not None:
        kind = "model_goal_rate"
    else:
        kind = "unknown"
    return {
        "home": xg[0] if xg else None,
        "away": xg[1] if xg else None,
        "kind": kind,
        "source_tags": tags,
        "real_event_xg": None,
        "note": "主字段是goal_rate。xg仅为兼容别名，不等于StatsBomb/Opta事件xG。",
    }


def build_injury_view(data):
    """汇总双方伤停视图（含启发式映射字段）。"""
    meta = data.get("field_meta") or {}
    out = {}
    for side in ("home", "away"):
        m = meta.get(f"injury_{side}") or {}
        mapped = {}
        for fld in ("attack_absence", "defense_absence", "gk_absence"):
            key = f"{fld}_{side}"
            if key in data:
                mapped[fld] = data.get(key)
        if not m and not mapped:
            continue
        out[side] = {
            "status": m.get("status", "VALID" if mapped else "UNAVAILABLE"),
            "confirmed_no_absence": bool(m.get("confirmed_no_absence", False)),
            "count": m.get("count"),
            "players": m.get("players") or [],
            "mapped": mapped,
            "source": m.get("source"),
            "note": m.get("note") or "mapped为启发式映射值，不是直接观测缺阵百分比。",
        }
    return out or None


def apply_multi_market_adjustments(core, data, out):
    """多市场拟合路径的标签整理：核心层已应用事实修正时打标记。"""
    if out.get("lambda_solver") != "multi_market_fit" or data.get("mode") == "market_only":
        out["xg_tags"] = clean_process_tags(out.get("xg_tags"))
        return out
    tags = list(out.get("xg_tags") or [])
    if any(t in tags for t in ("INJURY_ADJUSTED", "MOTIVE_ADJUSTED", "HOME_ADV_ADJUSTED")):
        tags.append("CORE_FACT_ADJUSTMENTS_APPLIED")
        out.setdefault("reliability_flags", []).append(
            "CORE_FACT_ADJUSTMENTS_APPLIED: multi_market_fit 基准λ后已在核心层应用伤停/战意/主场修正，融合层不再二次重算。"
        )
    out["xg_tags"] = clean_process_tags(tags)
    return out


def predict_one(core, version, data):
    """单场融合预测入口：市场权重注入 → 核心预测 → 审计 → 门控。"""
    build = build_identity()
    data, weights_loaded = ensure_market_weights(dict(data))
    evidence_audit = build_evidence_audit(data)
    try:
        out = core.predict(data)
    except Exception as exc:
        try:
            from market_fit import market_freshness as _mf
            pool_states = _mf(data)
        except Exception:
            pool_states = None
        core_output = {
            "status": "core_engine_crashed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "market_pool_freshness": pool_states,
            "likely_cause": (
                "All supplied market pools were judged stale/unknown by market_freshness() "
                "(see market_pool_freshness above) and no elo_home/elo_away or "
                "lambda_home/lambda_away pair was supplied as a fallback anchor, OR "
                "field_meta.<pool>.observed_at is missing/unparseable. Refresh "
                "field_meta.<pool>.observed_at (same timezone as kickoff) with a current "
                "snapshot, or supply a second independent anchor (elo or explicit lambda)."
            ),
        }
        return stamp_identity({
            "fusion_schema_version": build["fusion_schema_version"],
            "fusion_status": "blocked",
            "core_engine_version": version,
            "build_identity": build,
            "evidence_audit": evidence_audit,
            "core_output": core_output,
        }, data)
    if out.get("status") == "ok":
        tags = out.get("xg_tags") or []
        dep = float(out.get("market_dependency_pct") or 0)
        if "NO_ANCHOR_FALLBACK" in tags and dep < 80:
            out = {
                "status": "no_independent_anchor",
                "mode": out.get("mode"),
                "requested_mode": data.get("mode"),
                "xg_tags": tags,
                "errors": [
                    "NO_ANCHOR_FALLBACK cannot be used as production 1X2; "
                    "need paired Elo/lambda or a usable HAD"
                ],
            }
    if out.get("status") == "ok":
        out = apply_multi_market_adjustments(core, data, out)
        out.setdefault("reliability_flags", []).append(
            "UNFITTED_FUSION: 融合1.2新组合路径尚未完成独立大样本回测，不得声称优于市场或旧Skill。"
        )
        if weights_loaded:
            out.setdefault("reliability_flags", []).append(
                "AUTO_MARKET_WEIGHTS: 已自动加载 config/market_weights.json（UNFITTED，仅用于可复现，不代表最优权重）。"
            )
    if out.get("status") != "ok":
        return stamp_identity({
            "fusion_schema_version": build["fusion_schema_version"],
            "fusion_status": "blocked",
            "core_engine_version": version,
            "build_identity": build,
            "evidence_audit": evidence_audit,
            "core_output": out,
        }, data)
    ledger = ledger_audit(data)
    if ledger["unledgered_adjustments"]:
        out.setdefault("reliability_flags", []).append(
            "UNLEDGERED_ADJUSTMENT: "
            + ", ".join(ledger["unledgered_adjustments"])
            + " supplied without complete adjustment_ledger evidence."
        )
    out["xg_tags"] = clean_process_tags(out.get("xg_tags"))
    goal_rate = build_goal_rate(out)
    crs_audit = crs_overlap_audit(data, out, top_n=3)
    if crs_audit and crs_audit.get("flag"):
        out.setdefault("reliability_flags", []).append(
            f"{crs_audit['flag']}: CRS与模型Top{crs_audit['top_n']}"
            f"重合度={crs_audit['overlap_ratio']}，比分排序需降级解读。"
        )
    xg_alias = out.get("xg")
    asian = out.get("asian_handicap_home")
    if asian is not None:
        asian = dict(asian)
        if data.get("ah_line") is None and data.get("hhad") is not None:
            asian["line_source"] = "core_default_or_unspecified"
            asian["note"] = "未显式提供ah_line；勿把体彩HHAD线直接当作亚洲盘线。"
        else:
            asian["line_source"] = "explicit_ah_line" if data.get("ah_line") is not None else "unspecified"
    hhad = out.get("sporttery_hhad_3way")
    if hhad is not None:
        hhad = dict(hhad)
        hhad["market_type"] = "sporttery_hhad_3way"
        hhad["note"] = "体彩让球胜平负三项，不是亚洲盘。"
        if hhad.get("error_pp") is not None:
            hhad["error_pp_definition"] = "model_minus_market"
    quality = out.get("quality") or {}
    input_coverage = {
        "completeness_pct": quality.get("completeness_pct"),
        "source_reliability_pct": quality.get("source_reliability_pct"),
        "freshness_pct": quality.get("freshness_pct"),
        "overall_pct": quality.get("overall_pct"),
        "note": "输入覆盖/来源/新鲜度评分，不是预测置信度。",
    }
    freshness_audit = (out.get("multi_market_fit") or {}).get("freshness") or market_freshness_meta or {}
    pool_inputs = {
        "had": bool(data.get("odds")),
        "hhad": bool(data.get("hhad")),
        "ou": bool(data.get("ou")),
        "ttg": bool(data.get("ttg")),
        "hafu": bool(data.get("hafu")),
        "crs": bool(data.get("crs")),
    }
    used_pools, downweighted_pools, excluded_pools = [], [], []
    for pool, present in pool_inputs.items():
        if not present:
            excluded_pools.append(pool)
            continue
        state = (freshness_audit.get(pool) or {}).get("status") or "UNKNOWN"
        factor = float((freshness_audit.get(pool) or {}).get("factor") or 0.0)
        if state in ("FRESH", "AGING") and factor > 0:
            used_pools.append(pool)
            if state == "AGING" or factor < 1:
                downweighted_pools.append(pool)
        else:
            excluded_pools.append(pool)
    adjustment_fields = [
        k for k in (
            "lambda_prior", "attack_absence_home", "attack_absence_away",
            "defense_absence_home", "defense_absence_away",
            "gk_absence_home", "gk_absence_away",
            "rotation_home", "rotation_away",
            "attack_motive_home", "attack_motive_away",
            "defense_risk_home", "defense_risk_away", "home_adv",
        )
        if data.get(k) not in (None, 0, 0.0, 1, 1.0, False)
    ]
    data_usage_audit = {
        "used_pools": used_pools,
        "downweighted_pools": downweighted_pools,
        "excluded_pools": excluded_pools,
        "freshness": freshness_audit,
        "used_adjustments": adjustment_fields,
        "double_count_risk": bool(data.get("lambda_prior") and len(used_pools) > 0),
        "market_anchor": "HAD" if out.get("market_prob_pct") is not None else "NONE_OR_STALE",
        "note": "market_anchor为NONE_OR_STALE时，不把陈旧/未知HAD当作新鲜市场锚。",
    }
    api = data.get("api_football") or {}
    api_features = data.get("api_features") or {}
    api_usage = {
        "provider": api.get("provider", "apifootball.com") if api else None,
        "match_id": api.get("match_id") if api else None,
        "statistics_status": api.get("statistics_status") if api else "NOT_ATTACHED",
        "lineups_status": api.get("lineups_status") if api else "NOT_ATTACHED",
        "standings_status": api.get("standings_status") if api else "NOT_ATTACHED",
        "predictions_status": api.get("predictions_status") if api else "NOT_ATTACHED",
        "external_market_status": api.get("external_market_status") if api else "NOT_ATTACHED",
        "pre_kickoff_usable": (api.get("as_of") or {}).get("usable") if api else False,
        "odds_policy": "separate_market_layer_only",
        "model_feature_policy": "raw_attached; no unbacktested coefficient injection",
        "note": "赛后statistics只能在历史快照聚合后用于后续比赛；get_predictions保留为p_apifootball外部对照，不是xG。",
    }
    data_usage_audit["apifootball"] = api_usage
    data_usage_audit["api_features"] = {
        "status": (data.get("field_meta") or {}).get("api_features", {}).get("status", "NOT_ATTACHED"),
        "history_matches": api_features.get("history_matches"),
        "no_future_leakage": api_features.get("no_future_leakage"),
        "lambda_prior_source": ((api_features.get("team_strength") or {}).get("source")
                                 or (data.get("lambda_prior") or {}).get("source")),
        "note": "只有显式注入lambda_prior且通过当前引擎校验时，球队动态强度才影响模型；原始统计/阵容/积分榜仅作分层审计。",
    }
    evidence_audit = build_evidence_audit(data)

    policy_path = HERE.parent / "config" / "recommendation_policy.json"
    policy_mod = HERE / "recommendation_policy.py"
    try:
        spec = importlib.util.spec_from_file_location("fusion_recommendation_policy", policy_mod)
        policy_module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(policy_module)
        recommendation_gate = policy_module.evaluate({
            "core_output": out,
            "fusion_decision": decision(out, ledger, data),
            "reliability_flags": out.get("reliability_flags"),
            "market_freshness": (out.get("multi_market_fit") or {}).get("freshness"),
            "evidence_audit": evidence_audit,
        })
    except Exception as exc:
        recommendation_gate = {
            "banker_allowed": False,
            "confidence_pct": None,
            "confidence_status": "POLICY_ERROR",
            "reasons": ["POLICY_EVALUATION_ERROR"],
            "error": str(exc),
        }

    version_manifest = None
    if VERSION_FILE.exists():
        try:
            version_manifest = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            version_manifest = None

    result = {
        "fusion_schema_version": build["fusion_schema_version"],
        "version_manifest": version_manifest,
        "build_identity": build,
        "fusion_status": "ok",
        "core_engine_version": version,
        "match": out.get("match"),
        "mode": out.get("mode"),
        "research_only": bool(data.get("research_only")),
        "research_candidate": data.get("research_candidate"),
        "input_coverage": input_coverage,
        "data_quality": quality,
        "source_evidence": data.get("source_evidence"),
        "field_meta": data.get("field_meta"),
        "api_football": {
            "provider": api.get("provider"),
            "match_id": api.get("match_id"),
            "field_status": api_usage,
            "prediction": api.get("prediction"),
            "external_market": api.get("external_market_raw"),
        } if api else None,
        "api_features": api_features or None,
        "market_freshness": (out.get("multi_market_fit") or {}).get("freshness") or market_freshness_meta,
        "data_usage_audit": data_usage_audit,
        "evidence_audit": evidence_audit,
        "recommendation_gate": recommendation_gate,
        "injury": build_injury_view(data),
        "market_weights": data.get("market_weights"),
        "market_weights_meta": data.get("market_weights_meta"),
        "forecast": {
            "market_prob_pct": out.get("market_prob_pct"),
            "model_1x2_pct": out.get("model_1x2_pct"),
            "final_1x2_pct": out.get("final_1x2_pct"),
            "final_1x2_display": out.get("final_1x2_display"),
            "goal_rate": goal_rate,
            "xg_compat_alias": xg_alias,
            "top_scores": out.get("top_scores"),
            "ou_2_5": out.get("ou_2_5"),
            "ou_3_5": out.get("ou_3_5"),
            "btts": out.get("btts"),
            "sporttery_hhad_3way": hhad,
            "asian_handicap_home": asian,
            "crs_overlap_audit": crs_audit,
            "advancement": out.get("advancement"),
        },
        "core_calibration": {
            "one_x2_calibration": out.get("calibration"),
            "confidence": out.get("confidence"),
            "derived_market_status": out.get("derived_market_status"),
            "note": (
                "这是底层核心引擎(zu-yu-dashi-3)对1X2/O-U2.5/O-U3.5等单项盘口的时间序列切分校准结果，"
                "已在测试集验证，见 derived_market_status 逐盘口状态。它不等同于融合层(fusion)推荐置信度——"
                "fusion的组合/edge路径仍是 UNFITTED_FUSION，recommendation_gate.banker_allowed 不因此自动放行。"
                "两者是不同层级的校准状态，禁止混用其中一个描述另一个。"
            ),
        },
        "market_dependency_pct": out.get("market_dependency_pct"),
        "external_models": {
            "p_apifootball": api.get("prediction") if api else None,
            "note": "apifootball get_predictions仅作为外部模型对照，不进入独立球队强度训练。",
        },
        "sensitivity": out.get("sensitivity"),
        "reliability_flags": out.get("reliability_flags"),
        "assumptions": out.get("assumptions") or data.get("assumptions"),
        "adjustment_ledger_audit": ledger,
        "fusion_decision": decision(out, ledger, data),
        "core_output": out,
        "disclaimer": "概率模型输出，非投注建议。",
    }
    return stamp_identity(result, data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="input JSON path")
    parser.add_argument("--output", help="optional output JSON path")
    parser.add_argument("--production-route", action="store_true",
                        help="按联赛生成Understat/APIfootball影子候选；不改变生产概率")
    parser.add_argument("--research-route", action="store_true",
                        help="显式研究模式：允许实验lambda先验进入hybrid；输出research_only=true")
    parser.add_argument("--understat-store",
                        default=str(data_root() / "datasets" / "understat_store.jsonl"))
    parser.add_argument("--apifootball-events",
                        help="APIfootball get_events历史JSON或JSONL；未提供时该轨道自动回退市场基线")
    parser.add_argument("--router-min-history", type=int, default=5)
    args = parser.parse_args()
    core, version = load_core()
    with open(args.input, "r", encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    if args.production_route and args.research_route:
        parser.error("--production-route and --research-route are mutually exclusive")
    if args.production_route or args.research_route:
        raw = route_matches(
            raw,
            load_event_rows(args.understat_store),
            load_event_rows(args.apifootball_events),
            min_history=args.router_min_history,
            enable_experimental=args.research_route,
        )
    if isinstance(raw, dict) and isinstance(raw.get("matches"), list):
        result = {
            "fusion_schema_version": build_identity()["fusion_schema_version"],
            "fusion_status": "batch",
            "core_engine_version": version,
            "count": len(raw["matches"]),
            "research_only": bool(args.research_route),
            "results": [predict_one(core, version, item) for item in raw["matches"]],
        }
    else:
        result = predict_one(core, version, raw)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

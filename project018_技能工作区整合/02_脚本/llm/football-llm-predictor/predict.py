#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 轨道预测: 搜索证据驱动定性判断
=================================
读取 evidence_<date>/ 目录下的六类证据文件, 拼接官方赔率,
调用多个免费LLM做定性判断(H/D/A方向+比分偏好, 不伪概率),
聚合投票输出综合方向。

用法:
  python predict.py --input data/raw_2026-08-05.json --evidence-dir data/evidence_2026-08-05
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import football_predictor as fp
import llm_prompt_rules as lpr
import model_weights as mw
import ev_calculator as evc
import fusion_probability_source as fps
import llm_track_contract as ltc
import evidence_orchestrator as eo

def load_evidence(evidence_dir):
    """读取证据目录下所有 md 文件, 返回 {文件名: 内容}。"""
    result = {}
    for path in sorted(glob.glob(os.path.join(evidence_dir, "*.md"))):
        with open(path, encoding="utf-8") as f:
            result[os.path.basename(path)] = f.read()
    return result


def match_evidence_file(match_idx, evidence_files):
    """按序号前缀匹配证据文件, 跳过 *_mcp.md (MCP 数据块, 由 match_mcp_file 单独取)。"""
    pattern = re.compile(rf"^evidence_{match_idx:03d}(?:_|\.)", re.I)
    matches = [name for name in evidence_files
               if pattern.match(name) and not name.lower().endswith("_mcp.md")]
    return matches[0] if len(matches) == 1 else None


def _selected_match_identity(match):
    meta = (match or {}).get("sporttery_meta") or {}
    value = (match or {}).get("match_id") or meta.get("match_id")
    sporttery_id = "" if value in (None, "") else str(value).replace("sporttery-", "")
    return sporttery_id, str((match or {}).get("home") or ""), str((match or {}).get("away") or "")


def match_mcp_file(match_idx, evidence_files, match=None):
    """按序号前缀匹配 *_mcp.md (apifootball MCP 数据证据块, mcp_evidence.py 生成)。"""
    pattern = re.compile(rf"^evidence_{match_idx:03d}(?:_|\.)", re.I)
    matches = [name for name in evidence_files
               if pattern.match(name) and name.lower().endswith("_mcp.md")]
    if len(matches) > 1 and match is not None:
        expected = _selected_match_identity(match)
        identity_pattern = re.compile(
            r"match_identity\(\s*sporttery_match_id=([^;)]*);home=([^;)]*);away=([^;)]*);api_match_id=([^;)]*)\s*\)",
            re.I,
        )
        matches = [name for name in matches
                   if (found := identity_pattern.search(evidence_files[name] or ""))
                   and tuple(part.strip() for part in found.groups()[:3]) == expected]
    return matches[0] if len(matches) == 1 else None


REQUIRED_EVIDENCE_SECTIONS = {
    1: r"伤停|阵容",
    2: r"战意|动机",
    3: r"近况|状态",
    4: r"主客|旅行|天气",
    5: r"赔率",
    6: r"身份|核验",
}
EVIDENCE_GAP_MARKERS = (
    "证据缺口", "未检索到", "未拿到", "未做", "不足", "缺失",
    "UNAVAILABLE", "EMPTY_UNCONFIRMED", "FORM_UNAVAILABLE", "LINEUP_UNAVAILABLE",
)
AGGREGATION_RULE_VERSION = "evidence-direction-v1"
AGGREGATION_RULE_SPEC = {
    "alt_direction_weight": 0.5,
    "collapse_score_weight": 0.5,
    "evidence_gap_weight": 0.85,
    "reasoning_invalid_weight": 0.5,
    "weak_strength_threshold": 0.6,
}
MIN_VALID_EVIDENCE_MODELS = 2
EVIDENCE_AUDITOR_MODEL = "deepseek/deepseek-v4-flash"
# 主胜比例熔断：批内主胜方向占比过高 = 赛季初/主队系统性高估（08-05 回测 4/5 主胜全错，
# 08-13 官方赔率方向仅 30% 命中）。触发后把"强度最低"的主胜场次改判为次高方向。
HOME_BIAS_THRESHOLD = 0.65   # 主胜方向占比 >= 65% 触发熔断
HOME_BIAS_MIN_SAMPLE = 5     # 至少 5 场才统计（避免小样本误熔断）


def _parse_evidence_datetime(value):
    """Parse the documented collected_at/kickoff forms without guessing a timezone."""
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _evidence_time_rejection(detail):
    return {"ok": False, "reason": f"evidence_after_kickoff:{detail}"}


def _require_aware_datetime(value):
    parsed = _parse_evidence_datetime(value)
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def assess_evidence(evidence_text, kickoff=None, now=None, *, allow_odds_only=False):
    """Validate the minimum evidence contract before any LLM client is used."""
    if not evidence_text or not evidence_text.strip():
        return {"ok": False, "reason": "missing_evidence_file"}
    missing_sections = [str(n) for n, title_pattern in REQUIRED_EVIDENCE_SECTIONS.items()
                        if not re.search(rf"(?m)^##\s*{n}\.\s*.*(?:{title_pattern})", evidence_text)]
    if missing_sections:
        return {"ok": False, "reason": "missing_required_sections:" + ",".join(missing_sections)}
    if not re.search(r"source\(\s*https?://[^)\s]+", evidence_text, re.I):
        return {"ok": False, "reason": "missing_source_url"}
    if not re.search(r"collected_at\(\s*[^)\s][^)]*\)", evidence_text, re.I):
        return _evidence_time_rejection("missing_collected_at")
    fact_lines = [line.strip() for line in evidence_text.splitlines() if line.strip().startswith(("-", "*"))]
    content_fact_lines = []
    for line in fact_lines:
        content = re.sub(r"source\(\s*[^)]*\)", "", line, flags=re.I)
        content = re.sub(r"collected_at\(\s*[^)]*\)", "", content, flags=re.I)
        content = re.sub(r"^[-*]\s*", "", content).strip(" |：:—-")
        if not content:
            continue  # 单独的来源元数据不是事实行
        content_fact_lines.append(line)
        if "source(" not in line.lower() or "collected_at(" not in line.lower():
            return {"ok": False, "reason": "fact_missing_source_or_collected_at"}
    non_market_fact_lines = [line for line in content_fact_lines
                             if not re.search(r"体彩|赔率|CRS|TTG|HAFU|让球", line, re.I)]
    only_gaps = (not non_market_fact_lines or
                 all(any(marker in line for marker in EVIDENCE_GAP_MARKERS)
                     for line in non_market_fact_lines))
    if only_gaps and not allow_odds_only:
        return {"ok": False, "reason": "only_evidence_gaps"}
    collected_raw = re.findall(r"collected_at\(\s*([^)]*?)\s*\)", evidence_text, re.I)
    collected_times = [_parse_evidence_datetime(value) for value in collected_raw]
    if any(value is None for value in collected_times):
        return _evidence_time_rejection("invalid_collected_at")
    try:
        earliest, latest = min(collected_times), max(collected_times)
    except TypeError:
        return _evidence_time_rejection("incomparable_collected_at")
    if kickoff is not None:
        kickoff_time = _require_aware_datetime(kickoff)
        if kickoff_time is None:
            return _evidence_time_rejection("invalid_kickoff")
        now_time = _require_aware_datetime(now) if now is not None else None
        if now is not None and now_time is None:
            return _evidence_time_rejection("invalid_runtime_time")
        if now_time is not None and now_time >= kickoff_time:
            return {"ok": False, "reason": "prediction_at_or_after_kickoff"}
        try:
            if any(value.tzinfo is None or value.utcoffset() is None for value in collected_times):
                return _evidence_time_rejection("collected_at_missing_timezone")
            if any(value >= kickoff_time for value in collected_times):
                return _evidence_time_rejection("collected_at_at_or_after_kickoff")
        except TypeError:
            return _evidence_time_rejection("incomparable_collected_at_and_kickoff")
    return {
        "ok": True,
        "evidence_gap": only_gaps or any(marker in evidence_text for marker in EVIDENCE_GAP_MARKERS),
        "collection_status": "ONLY_ODDS" if only_gaps and allow_odds_only else None,
        "evidence_file_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
        "evidence_collected_at_min": collected_raw[collected_times.index(earliest)],
        "evidence_collected_at_max": collected_raw[collected_times.index(latest)],
    }


def assess_mcp_evidence(mcp_text, kickoff, match=None):
    """Validate a supplementary MCP block independently of primary evidence."""
    if not mcp_text or not mcp_text.strip():
        return {"ok": False, "reason": "missing_mcp_evidence"}
    if not re.search(r"source\(\s*https?://[^)\s]+", mcp_text, re.I):
        return {"ok": False, "reason": "missing_mcp_source_url"}
    collected = re.findall(r"collected_at\(\s*([^)]*?)\s*\)", mcp_text, re.I)
    if not collected:
        return {"ok": False, "reason": "missing_mcp_collected_at"}
    kickoff_time = _require_aware_datetime(kickoff)
    if kickoff_time is None:
        return _evidence_time_rejection("invalid_kickoff")
    collected_times = [_require_aware_datetime(value) for value in collected]
    if any(value is None for value in collected_times):
        return {"ok": False, "reason": "invalid_mcp_collected_at"}
    if any(value >= kickoff_time for value in collected_times):
        return {"ok": False, "reason": "mcp_collected_at_at_or_after_kickoff"}
    if match is not None:
        identity = re.search(
            r"match_identity\(\s*sporttery_match_id=([^;)]*);home=([^;)]*);away=([^;)]*);api_match_id=([^;)]*)\s*\)",
            mcp_text,
            re.I,
        )
        if not identity:
            return {"ok": False, "reason": "missing_mcp_match_identity"}
        sporttery_id, home, away, _api_id = (part.strip() for part in identity.groups())
        expected_sporttery_id, expected_home, expected_away = _selected_match_identity(match)
        if (sporttery_id != expected_sporttery_id or home != expected_home or away != expected_away):
            return {"ok": False, "reason": "mcp_match_identity_mismatch"}
    return {"ok": True}


def select_matches(matches, match_id=None, max_matches=0, min_match=0):
    """Select matches while retaining their 1-based raw-file indices.

    min_match 用于分批预测：跳过前 min_match-1 场（序号仍按 raw 原始编号，
    证据文件匹配不受影响）。"""
    selected = list(enumerate(matches, 1))
    if min_match:
        selected = selected[min_match - 1:]
    if max_matches:
        selected = selected[:max_matches]
    if match_id is not None:
        selected = [(idx, match) for idx, match in selected
                    if _selected_match_identity(match)[0] == str(match_id)]
    return selected


def evidence_collection_label(evidence_text):
    """Use the evidence timestamp rather than a hard-coded collection date."""
    timestamps = re.findall(r"collected_at\(\s*([^)]*?)\s*\)", evidence_text or "", re.I)
    return f"采集时间 {timestamps[0]}" if timestamps else "当前采集证据"


def build_evidence_catalog(evidence_text):
    """将已通过时间和来源门禁的 Markdown 事实转为紧凑证据目录。"""
    catalog = []
    for line in (evidence_text or "").splitlines():
        stripped = re.sub(r"^\s*>\s?", "", line).strip()
        # light_evidence.render_fusion_evidence emits the structured payload
        # on the line immediately following its status bullet.  Preserve it in
        # the LLM catalog; status-only metadata tells the model that facts
        # exist but is not enough to analyze form, injuries, or lineups.
        if stripped.lower().startswith("facts=") and catalog:
            catalog[-1]["facts"] = stripped[6:].strip()[:2400]
            continue
        if not stripped.startswith(("-", "*")):
            continue
        fact = stripped[1:].strip().split("| source(", 1)[0].strip()
        source_match = re.search(r"source\(\s*(https?://[^)\s]+)\s*\)", stripped, re.I)
        if not fact or not source_match:
            continue
        collected_match = re.search(r"collected_at\(\s*([^)]*?)\s*\)", stripped, re.I)
        source_id_match = re.search(r"source_id\(\s*([^)]*?)\s*\)", stripped, re.I)
        lowered = fact.lower()
        status_match = re.search(r"(?:status|状态)\s*[=:]\s*([A-Z_]+)", fact, re.I)
        explicit_status = status_match.group(1).upper() if status_match else ""
        if any(marker in lowered for marker in ("来源冲突", "source_conflict", "说法冲突")) or explicit_status == "SOURCE_CONFLICT":
            status = "SOURCE_CONFLICT"
        elif explicit_status == "PARTIAL" and "facts_available=true" in lowered:
            # Facts exist but a quality/scope gate remains open.  Let the
            # auditor cite the facts while the separate evidence_gap flag
            # still forces a cautious downstream decision.
            status = "SINGLE_SOURCE"
        elif explicit_status and explicit_status not in (
            "VALID", "VALID_EMPTY", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING",
            "IMAGE_EXTRACTED", "PROXY_XG", "EXPLICIT_XG",
        ):
            status = "UNAVAILABLE"
        elif any(marker in lowered for marker in (
            "无记录", "0条", "未获得", "未检索到", "未拿到", "证据缺口",
            "封锁源占槽", "不采正文", "待采", "无本场逐人", "未取到本场", "按缺口记录",
        )):
            status = "UNAVAILABLE"
        elif any(marker in lowered for marker in ("双源一致", "交叉验证", "verified_multi_source")):
            status = "VERIFIED_MULTI_SOURCE"
        else:
            status = "SINGLE_SOURCE"
        item = {
            "id": f"E{len(catalog) + 1}",
            "status": status,
            "fact": fact,
            "source": source_match.group(1),
        }
        # Preserve field-level freshness and provenance in the prompt.  The
        # global evidence timestamp is insufficient when, for example, a
        # lineup refresh is newer than the form snapshot.
        if collected_match:
            item["collected_at"] = collected_match.group(1).strip()
        if source_id_match:
            item["source_id"] = source_id_match.group(1).strip()
        catalog.append(item)
    # Mark repeated provider domains conservatively.  This does not delete
    # facts—each item remains auditable—but prevents the prompt/auditor from
    # treating several pages from one supplier as independent confirmation.
    groups = {}
    for item in catalog:
        host = (urllib.parse.urlparse(item["source"]).netloc or "").lower()
        group = host.removeprefix("www.") or item["source"]
        groups.setdefault(group, []).append(item)
    for group, items in groups.items():
        if len(items) < 2:
            continue
        for rank, item in enumerate(items, 1):
            item["source_group"] = group
            item["source_group_rank"] = rank
            item["independence"] = "PRIMARY_SOURCE_GROUP" if rank == 1 else "DUPLICATE_SOURCE_GROUP"
    return catalog


def build_evidence_prompt(match, evidence_text, match_idx):
    """证据 + 官方赔率 -> LLM prompt。
    冷门规则: 两回合制/杯赛场次在 prompt 中提示冷门风险, 引导模型不盲从赔率。"""
    lines = [f"比赛信息：{match['home']} VS {match['away']} | {match.get('league', '')} | {match.get('kickoff_local', '')}"]
    # 官方赔率：缺字段或非法值时显式降级，不构造伪市场倾向。
    def valid_odds(values, count):
        if not isinstance(values, (list, tuple)) or len(values) < count:
            return False
        try:
            return all(float(value) > 0 for value in values[:count])
        except (TypeError, ValueError):
            return False

    mo = match.get("model_odds") or []
    if valid_odds(mo, 3):
        lines.append(f"官方胜平负赔率: 主胜{mo[0]} / 平{mo[1]} / 客胜{mo[2]}")
    elif mo:
        lines.append("官方胜平负赔率: 数据缺口（字段不完整或非法，不生成市场倾向）")
    hh = match.get("model_hhad") or {}
    if valid_odds(hh.get("odds"), 3):
        try:
            line = float(hh.get("line", 0))
        except (TypeError, ValueError):
            line = None
        if line is None:
            lines.append("官方让球赔率: 数据缺口（让球线非法，不生成市场倾向）")
        else:
            sign = "+" if line > 0 else ""
            lines.append(f"官方让球({sign}{line:g})赔率: 主胜{hh['odds'][0]} / 平{hh['odds'][1]} / 客胜{hh['odds'][2]}")
    elif hh.get("odds"):
        lines.append("官方让球赔率: 数据缺口（字段不完整或非法，不生成市场倾向）")
    # 次回合战意提示: 首回合领先方轮换/保守陷阱
    fl = extract_first_leg_info(match.get("league", ""), evidence_text or "", home=match.get("home", ""), away=match.get("away", ""))
    if fl.get("is_second_leg") and fl.get("first_leg_score"):
        margin = fl.get("margin")
        if margin is not None and margin >= 2:
            margin_txt = f"首回合 {fl.get('first_leg_score')}（净胜 {margin} 球）"
        else:
            margin_txt = f"首回合 {fl.get('first_leg_score')}（分差不明显）"
        lines.append(
            f"\n⚠️ 次回合战意提示: {margin_txt}。"
            f"两回合杯赛次回合的首回合领先方极易轮换主力或保守求平，'实力差'常被高估——"
            f"即使某队明显更强，若它已手握晋级优势，也警惕其战意下降；反之落后方会全力进攻。"
            f"判断时把'次回合战意'权重置于'静态实力差'之上。")
    catalog = build_evidence_catalog(evidence_text)
    lines.append(f"\n=== 结构化证据（{evidence_collection_label(evidence_text)}） ===")
    lines.append(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")))
    lines.append(
        "字段级时间规则：优先使用每条证据自身的 collected_at；若同一维度冲突，较新的开球前事实优先，"
        "但仍须保留 SOURCE_CONFLICT。全局采集时间不能覆盖字段级时间。"
    )
    if any(item.get("independence") == "DUPLICATE_SOURCE_GROUP" for item in catalog):
        lines.append(
            "\n来源独立性提示：标记为 DUPLICATE_SOURCE_GROUP 的证据来自同一来源组，"
            "只能作为同源补充，不能与 PRIMARY_SOURCE_GROUP 叠加成多个独立确认。"
        )
    predicted_xi = any(item.get("status") == "SINGLE_SOURCE" and
                       ("starting_xi" in str(item.get("fact", "")).lower() or
                        "预计首发" in str(item.get("fact", "")) or
                        "predicted" in str(item.get("fact", "")).lower())
                       for item in catalog)
    if predicted_xi:
        lines.append(
            "\n首发证据分级规则：目录中的预计首发/PREDICTED 只能作为赛前先验，权重低于官方已确认首发；"
            "不得写成‘官方首发’或据此给出高置信结论。若预计首发与伤停、近期出场或其他来源冲突，"
            "必须保留冲突并下调置信度；开球前未出现官方首发时，仍标记为预计首发。"
        )
    lines.append(
        "\n只使用上述 E 编号。decision=opinion 时必须给出 probs_1x2、比分Top3、大小球、半全场，不得留空。"
        "近5场、首发和伤停只用目录中已通过来源/时间门禁的真实快照；未采集到就写缺口，不得用投票、占位文本或常识补齐。"
        "仅赔率时仍给观察性 opinion，但不得把赔率外推成基本面，且下游强制 observe。"
    )
    return "\n".join(lines)


def parse_evidence_audit(content, evidence_catalog):
    """校验无方向证据审计结果。"""
    text = (content or "").strip()
    text = re.sub(r"^```(json)?\s*|\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"error": "audit_missing_json"}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"error": f"audit_invalid_json:{exc}"}
    forbidden = {"direction", "alt_direction", "score_pref", "ou25", "hafu"}
    if forbidden & set(data):
        return {"error": "audit_contains_prediction_fields"}
    catalog = {str(item.get("id")): item for item in (evidence_catalog or [])}
    usable = ([str(value) for value in (data.get("usable_evidence_ids") or [])]
              if "usable_evidence_ids" in data else
              [eid for eid, item in catalog.items()
               if item.get("status") in ("SINGLE_SOURCE", "VERIFIED_MULTI_SOURCE")])
    unusable = ([str(value) for value in (data.get("unusable_evidence_ids") or [])]
                if "unusable_evidence_ids" in data else
                [eid for eid, item in catalog.items() if item.get("status") == "UNAVAILABLE"])
    conflicts = ([str(value) for value in (data.get("conflict_evidence_ids") or [])]
                 if "conflict_evidence_ids" in data else
                 [eid for eid, item in catalog.items() if item.get("status") == "SOURCE_CONFLICT"])
    all_ids = usable + unusable + conflicts
    if any(value not in catalog for value in all_ids):
        return {"error": "audit_unknown_evidence_id"}
    if any(catalog[value].get("status") not in ("SINGLE_SOURCE", "VERIFIED_MULTI_SOURCE") for value in usable):
        return {"error": "audit_marks_unusable_evidence_as_usable"}
    if any(catalog[value].get("status") != "UNAVAILABLE" for value in unusable):
        return {"error": "audit_unavailable_status_mismatch"}
    if any(catalog[value].get("status") != "SOURCE_CONFLICT" for value in conflicts):
        return {"error": "audit_conflict_status_mismatch"}
    readiness = data.get("market_readiness") or {}
    required_markets = ("one_x_two", "score", "ou25", "hafu")
    if any(not isinstance(readiness.get(name), bool) for name in required_markets):
        return {"error": "audit_invalid_market_readiness"}
    return {
        "status": "ok",
        "usable_evidence_ids": usable,
        "unusable_evidence_ids": unusable,
        "conflict_evidence_ids": conflicts,
        "gaps": [str(value) for value in (data.get("gaps") or [])],
        "market_readiness": {name: readiness[name] for name in required_markets},
        "summary": str(data.get("summary") or "").strip()[:220],
    }


def build_voter_prompt(base_prompt, evidence_audit):
    audit = {key: value for key, value in evidence_audit.items() if key != "status"}
    return (f"{base_prompt}\n\n=== 证据审计（无预测方向） ===\n"
            f"{json.dumps(audit, ensure_ascii=False, separators=(',', ':'))}\n"
            "请独立判断；审计结果只说明证据可用性，不是另一个模型的比赛结论。")


def two_voter_consensus(predictions, voter_models):
    voter_models = list(voter_models)
    if len(voter_models) == 1:
        record = predictions.get(voter_models[0])
        if not isinstance(record, dict) or "error" in record or record.get("decision") != "opinion":
            return {"status": "skip", "action": "skip", "reason": "single_voter_abstained_or_failed",
                    "voter_models": voter_models}
        return {
            "status": "single_model_research",
            "action": "observe",
            "reason": "single_model_no_consensus",
            "direction": record.get("direction"),
            "voter_models": voter_models,
        }
    if len(voter_models) != 2:
        return {"status": "skip", "action": "skip", "reason": "requires_exactly_two_voters",
                "voter_models": voter_models}
    records = [predictions.get(model) for model in voter_models]
    if any(not isinstance(item, dict) or "error" in item or item.get("decision") != "opinion" for item in records):
        return {"status": "skip", "action": "skip", "reason": "voter_abstained_or_failed",
                "voter_models": voter_models}
    directions = [item.get("direction") for item in records]
    if directions[0] != directions[1]:
        return {"status": "skip", "action": "skip", "reason": "voter_disagreement",
                "voter_models": voter_models, "directions": directions}
    return {"status": "consensus", "action": "research_opinion", "direction": directions[0],
            "voter_models": voter_models}


def parse_evidence_prediction(content, evidence_catalog=None):
    """解析模型输出 JSON（ou25/hafu/evidence_gap/reasoning 质检）。"""
    text = content.strip()
    text = re.sub(r"^```(json)?\s*|\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"error": f"无JSON: {content[:80]}"}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"JSON解析失败: {e}"}
    is_new_contract = "decision" in data
    decision = str(data.get("decision") or "opinion").strip().lower()
    if decision not in ("opinion", "abstain"):
        return {"error": f"非法decision: {decision}"}
    raw_direction = data.get("direction")
    direction = str(raw_direction).strip() if raw_direction is not None else None
    if decision == "opinion" and direction not in ("主胜", "平局", "客胜"):
        return {"error": f"非法direction: {direction}"}
    if decision == "abstain":
        direction = None
    alt = str(data.get("alt_direction") or "").strip() or None
    if alt not in (None, "主胜", "平局", "客胜"):
        alt = None
    top_scores = lpr.normalize_top_scores(data.get("top_scores") or data.get("score_pref"))
    sp = (top_scores[0] if top_scores else None) or normalize_score_pref(data.get("score_pref"))
    probs = lpr.normalize_probs_1x2(data.get("probs_1x2") or data.get("probs"))
    reasoning = str(data.get("summary") or data.get("reasoning") or "").strip()[:220]
    ou25 = lpr.normalize_ou25(data.get("ou25"))
    hafu = lpr.normalize_hafu(data.get("hafu"))
    # Preserve the model's normalized self-report for research auditing even
    # when evidence gates later force the decision to abstain.  These fields
    # are deliberately prefixed raw_llm_ and never feed production gates.
    raw_llm_probs = list(probs) if probs else None
    raw_llm_top_scores = list(top_scores) if top_scores else None
    raw_llm_ou25 = ou25
    raw_llm_hafu = hafu
    egap = bool(data.get("evidence_gap", False))
    evidence_ids = [str(value).strip() for value in (data.get("evidence_ids") or []) if str(value).strip()]
    reason_codes = [str(value).strip() for value in (data.get("reason_codes") or []) if str(value).strip()]
    unsupported = [str(value).strip() for value in (data.get("unsupported_assumptions") or []) if str(value).strip()]
    catalog_by_id = {str(item.get("id")): item for item in (evidence_catalog or [])}
    invalid_ids = [value for value in evidence_ids if evidence_catalog is not None and value not in catalog_by_id]
    usable_ids = [value for value in evidence_ids if catalog_by_id.get(value, {}).get("status") in (
        "SINGLE_SOURCE", "VERIFIED_MULTI_SOURCE",
    )]
    direction_index = {"主胜": 0, "平局": 1, "客胜": 2}
    probability_conflict = (
        decision == "opinion" and direction in direction_index and probs
        and max(range(3), key=lambda index: probs[index]) != direction_index[direction]
    )
    if probability_conflict:
        decision = "abstain"
        direction = alt = sp = ou25 = hafu = None
        top_scores = probs = None
        egap = True
        reason_codes.append("PROBABILITY_DIRECTION_CONFLICT")
    if decision == "opinion" and evidence_catalog is not None and (invalid_ids or not usable_ids):
        decision = "abstain"
        direction = alt = sp = ou25 = hafu = None
        top_scores = probs = None
        egap = True
        reason_codes.append("INVALID_OR_UNUSABLE_EVIDENCE")
    elif decision == "opinion" and unsupported:
        egap = True
    if decision == "opinion" and (not probs or not top_scores or not ou25 or not hafu):
        return {"error": "missing_required_markets"}
    rq = lpr.reasoning_quality(reasoning)
    # The evidence contract carries auditable E-IDs.  A non-empty summary is
    # not evidence by itself: require the summary to cite at least one of the
    # IDs that the model returned.  This closes the gap where a model could
    # emit a plausible paragraph plus valid-looking markets without tying its
    # explanation to the supplied facts.
    # ``\b`` treats adjacent Chinese characters as word characters on
    # Python's Unicode regex engine, so it misses strings such as ``E1记录``.
    cited_ids = {str(value) for value in re.findall(
        r"(?<![A-Za-z0-9_])E\d+(?![A-Za-z0-9_])", reasoning
    )}
    declared_ids = set(evidence_ids)
    missing_evidence_reference = bool(is_new_contract and (
        not declared_ids or not (cited_ids & declared_ids)
    ))
    if is_new_contract:
        reasoning_ok = bool(reasoning) and not missing_evidence_reference
    else:
        reasoning_ok = bool(rq.get("ok"))
    rq = {**rq, "cited_evidence_ids": sorted(cited_ids),
          "missing_evidence_reference": missing_evidence_reference}
    if not reasoning_ok:
        egap = True
    # 动态坍缩标记：模型输出"低比分默认模板"(LOW_SCORE_SET)且 reasoning 差 = 坍缩。
    # 不再硬编码 2-1/1-2；当前坍缩焦点 1-0 恰在 LOW_SCORE_SET 内。
    collapse_score = bool(sp in lpr.LOW_SCORE_SET and not reasoning_ok)
    return {
        "decision": decision,
        "direction": direction,
        "alt_direction": alt,
        "score_pref": sp,
        "top_scores": top_scores,
        "probs_1x2": probs,
        "ou25": ou25,
        "hafu": hafu,
        "raw_llm_probs_1x2": raw_llm_probs,
        "raw_llm_top_scores": raw_llm_top_scores,
        "raw_llm_ou25": raw_llm_ou25,
        "raw_llm_hafu": raw_llm_hafu,
        "evidence_gap": egap,
        "evidence_ids": evidence_ids,
        "invalid_evidence_ids": invalid_ids,
        "unsupported_assumptions": unsupported,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "reasoning": reasoning,
        "reasoning_ok": reasoning_ok,
        "reasoning_flags": rq,
        "collapse_score": collapse_score,
    }

def map_score_to_crs(home: int, away: int) -> str:
    """竞彩比分兑奖映射（委托 llm_prompt_rules）。"""
    return lpr.map_score_to_crs(int(home), int(away))


def normalize_score_pref(raw):
    return lpr.normalize_score_pref(raw)


def sanitize_for_zhipu(text):
    """委托共享模块。"""
    return lpr.sanitize_for_zhipu(text)



# 角色 / JSON / 系统提示 —— 统一自 llm_prompt_rules（2026-08-08 全面优化）
ROLE_PROMPTS = lpr.ROLE_PROMPTS
JSON_RULES_SUFFIX = lpr.JSON_RULES_EVIDENCE
EVIDENCE_SYSTEM_PROMPT = lpr.EVIDENCE_SYSTEM_PROMPT


def output_token_budget(model):
    """Reserve enough room for reasoning models to emit their final JSON."""
    # DeepSeek V4 Flash exposes a reasoning channel; with a 1024-token cap it
    # can spend the whole completion on reasoning and return no final JSON.
    return 4096 if fp.strip_provider(model) in {"kimi-k3", "deepseek-v4-flash"} else 1024


def model_request_options(model):
    """Return provider-specific options without leaking them into model contracts."""
    if fp.strip_provider(model) == "deepseek-v4-flash":
        # V4 Flash otherwise spends the whole completion in reasoning_content;
        # the LLM track needs a bounded final JSON decision instead.
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def _empty_response_diagnostic(response):
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    usage = getattr(response, "usage", None)
    completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
    reasoning = getattr(choice.message, "reasoning_content", None)
    reasoning_chars = len(str(reasoning)) if reasoning else 0
    return ("empty_content"
            f"; finish_reason={finish_reason}"
            f"; completion_tokens={completion_tokens}"
            f"; reasoning_chars={reasoning_chars}")



def call_evidence_model(client, model, prompt, models_used=None, evidence_catalog=None):
    """调用单个模型做定性判断, 重试逻辑与 call_model 一致。"""
    err = "未知错误"
    real_model = fp.strip_provider(model)
    temperature = fp.MODEL_TEMPERATURE_OVERRIDES.get(real_model, 0.3)
    request_prompt = prompt
    for i in range(3):
        try:
            if model.startswith("zhipu/"):
                request_prompt = sanitize_for_zhipu(request_prompt)
            sys_prompt = lpr.system_prompt_evidence(model, models_used)
            request_options = model_request_options(model)
            resp = client.chat.completions.create(
                model=real_model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": request_prompt},
                ],
                temperature=temperature,
                max_tokens=output_token_budget(model),
                **request_options,
            )
            content = resp.choices[0].message.content
            if content is None or not str(content).strip():
                err = _empty_response_diagnostic(resp)
            else:
                parsed = parse_evidence_prediction(content, evidence_catalog)
                if not parsed.get("error"):
                    return model, parsed
                err = str(parsed["error"])[:160]
                # DeepSeek occasionally emits a nearly-correct answer with a
                # malformed/partial JSON object. Give it one explicit repair
                # instruction instead of treating the first parse failure as
                # a permanent model failure. A valid abstain is returned
                # normally and is never retried here.
                if i < 2:
                    request_prompt = (
                        f"{prompt}\n\n上一次输出未通过结构化校验（{err}）。"
                        "请重新检查证据编号、字段完整性和 JSON 语法；只输出一个完整 JSON 对象，"
                        "不要 Markdown、解释文字或代码围栏。"
                    )
        except Exception as e:
            err = str(e)[:120]
            if "429" in err or "Rate limit" in err:
                time.sleep(10 + i * 15)
            else:
                time.sleep(3)
                break
    return model, {"error": err}


def call_evidence_auditor(client, prompt, evidence_catalog):
    try:
        if EVIDENCE_AUDITOR_MODEL.startswith("zhipu/"):
            prompt = sanitize_for_zhipu(prompt)
        auditor_model = fp.strip_provider(EVIDENCE_AUDITOR_MODEL)
        temperature = fp.MODEL_TEMPERATURE_OVERRIDES.get(auditor_model, 0.0)
        audit_max_tokens = output_token_budget(EVIDENCE_AUDITOR_MODEL)
        messages = [
            {"role": "system", "content": lpr.system_prompt_evidence_audit()},
            {"role": "user", "content": prompt},
        ]
        request_options = model_request_options(EVIDENCE_AUDITOR_MODEL)
        response = client.chat.completions.create(
            model=auditor_model,
            messages=messages,
            temperature=temperature,
            max_tokens=audit_max_tokens,
            **request_options,
        )
        raw = response.choices[0].message.content
        parsed = parse_evidence_audit(raw, evidence_catalog)
        retryable_errors = {
            "audit_missing_json", "audit_unknown_evidence_id",
            "audit_marks_unusable_evidence_as_usable", "audit_unavailable_status_mismatch",
            "audit_conflict_status_mismatch", "audit_invalid_market_readiness",
        }
        error = str(parsed.get("error") or "")
        if error.split(":", 1)[0] not in retryable_errors:
            return parsed
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": (
                f"审计未通过：{error}。程序会按目录状态自动推导证据可用性；"
                "不得输出 usable_evidence_ids、unusable_evidence_ids 或 conflict_evidence_ids，也不得枚举 E 编号。"
                "四个 market_readiness 字段必须为布尔值。只输出包含 gaps、market_readiness、summary 的完整 JSON 对象。"
            ),
        })
        response = client.chat.completions.create(
            model=auditor_model,
            messages=messages,
            temperature=temperature,
            max_tokens=audit_max_tokens,
            **request_options,
        )
        return parse_evidence_audit(response.choices[0].message.content, evidence_catalog)
    except Exception as exc:
        return {"error": str(exc)[:160]}


def is_two_legged(league, evidence_text):
    """检测两回合制赛事(资格赛/杯赛): 这些场次冷门概率显著更高。
    策略: 联赛名命中优先; 证据正文仅匹配"本场/本回合/本场比赛"上下文中的
    首回合/次回合/资格赛等强信号, 排除"天皇杯/日联杯/两回合交锋记录"(H2H/荣誉)等干扰。"""
    league = league or ""
    # 1) 联赛名直接命中: 最可靠
    if any(kw in league for kw in ["资格赛", "欧冠", "欧罗巴", "欧协联", "巴西杯",
                                   "英联杯", "英联赛杯", "日联杯", "足协杯", "国王杯"]):
        return True
    # 2) 证据正文: 只看"本场/首回合/次回合"赛事阶段信号, 且排除 H2H/荣誉上下文
    if evidence_text:
        # 强信号: 明确提到"本场是...首回合/次回合/资格赛第N轮"
        import re
        strong_patterns = [
            r"本场.{0,15}(首回合|次回合)",
            r"本场比赛.{0,15}(首回合|次回合)",
            r"第[一二三三四五六七八九十\d]+轮资格赛",
            r"资格赛.{0,10}(首回合|次回合)",
            r"欧罗巴.{0,10}(第[一二三\d]+轮|资格赛)",
            r"欧冠.{0,10}(第[一二三\d]+轮|资格赛)",
        ]
        for pat in strong_patterns:
            if re.search(pat, evidence_text):
                return True
        # 弱信号: "首回合"出现在行首附近(比赛信息区), 且不是"交锋记录/历史"
        for m in re.finditer(r"首回合|次回合", evidence_text):
            ctx = evidence_text[max(0, m.start()-60):m.end()+30]
            if any(neg in ctx for neg in ["交锋", "H2H", "历史", "记录", "首回合0-", "首回合0-2", "战绩"]):
                continue
            if "本场" in ctx or "第" in ctx or "轮" in ctx or "资格" in ctx:
                return True
    return False


def extract_first_leg_info(league, evidence_text, home=None, away=None):
    """从证据文本提取两回合制赛事的关键信息, 用于次回合战意判断。

    返回 dict:
      is_second_leg: bool —— 本场是否次回合
      first_leg_score: "1-1" 或 None —— 首回合比分(原始视角)
      margin: int 或 None —— 首回合净胜球数(绝对值)。分差≥2 是"领先方轮换/保守"高发场景
      agg_text: "总比分 X-Y" 原文片段或 None

    home/away: 保留参数(未来可扩展队名级判断), 当前 leader 判断不可靠已移除,
    改用"分差"作为战意修正的稳健信号——无论谁领先, 大分差次回合都倾向保守。
    """
    result = {"is_second_leg": False, "first_leg_score": None,
              "margin": None, "agg_text": None}
    text = evidence_text or ""
    if not text:
        return result
    # 次回合检测: 证据明确写"次回合"且非历史交锋上下文
    for m in re.finditer(r"次回合|第二回合|second leg|Second leg|2nd leg", text):
        ctx = text[max(0, m.start()-80):m.end()+40]
        if any(neg in ctx for neg in ["交锋", "H2H", "历史", "记录", "此前"]):
            continue
        result["is_second_leg"] = True
        break
    if not result["is_second_leg"]:
        # 有些证据只写"首回合比分"但本场是次回合, 用"总比分/agg"兜底
        if re.search(r"总比分|aggregate|Agg", text):
            result["is_second_leg"] = True
    # 首回合比分: 找"首回合"上下文里的比分。先剔除日期(2026-08-06)避免误匹配,
    # 比分 = 1-2 位数字 - 1-2 位数字, 前后不能是数字或连字符(排除日期残留)
    text_nodate = re.sub(r"\d{4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,2}", " ", text)
    fl_m = re.search(r"首回合[^0-9]{0,60}?(?<![\d-])(\d{1,2})\s*[-:：]\s*(\d{1,2})(?![\d-])", text_nodate)
    if fl_m:
        result["first_leg_score"] = f"{fl_m.group(1)}-{fl_m.group(2)}"
        try:
            result["margin"] = abs(int(fl_m.group(1)) - int(fl_m.group(2)))
        except (ValueError, IndexError):
            result["margin"] = None
    # 总比分 / aggregate 片段(同样排除日期), 兜底 margin
    agg_m = re.search(r"(?:总比分|aggregate|Agg)[^0-9]{0,15}(?<![\d-])(\d{1,2})\s*[-:：]\s*(\d{1,2})(?![\d-])", text_nodate, re.I)
    if agg_m:
        result["agg_text"] = f"{agg_m.group(1)}-{agg_m.group(2)}"
        if result["margin"] is None:
            try:
                result["margin"] = abs(int(agg_m.group(1)) - int(agg_m.group(2)))
            except (ValueError, IndexError):
                pass
    return result


def decide_single_pick(agg, ev_results, first_leg, match=None):
    """双选 → 单选主推方向(决策层)；平局概率高时保留双选建议。

    场景: 强度<60% 或证据缺口时, 系统强制双选, 但"能赚钱的是单选"。
    本函数默认在双选的两个方向里挑一个主推, 依据:
      1. EV 差: 若一个方向正 EV 且另一个负 EV, 选正 EV 方向
      2. 投票差: 若票数明显偏向一方, 选票多的一方
      3. 次回合战意: 首回合大分差(≥2球)时, 平局概率上升——给平局小幅加权

    例外(平局概率高): 平局是 1X2 里最难单选、最该双选的方向。
    当平局是 top 方向, 或平局投票占比 ≥30% 且与主选方向差距 <10pp 时,
    不强制单选, 输出"平局/另一方"双选建议。

    返回 {"pick": 方向或"平局/X"双选, "confidence": 0-1, "reason": str, "skip": bool}
    """
    direction = agg.get("direction")
    alt = agg.get("alt_direction")
    votes = agg.get("all_votes") or {}
    strength = agg.get("strength", 0)

    # 无双选时, 主推即方向
    if not alt or alt == direction:
        return {"pick": direction, "confidence": strength, "reason": "模型共识明确(无备选)", "skip": False}

    # ---- 平局概率高 → 双选建议(不强制单选) ----
    total_votes = sum(votes.values())
    draw_prob = votes.get("平局", 0) / total_votes if total_votes else 0
    top_prob = votes.get(direction, 0) / total_votes if total_votes else 0
    draw_high = (direction == "平局") or (draw_prob >= 0.30 and abs(draw_prob - top_prob) < 0.10)
    if draw_high:
        # 双选的另一方: 主胜/客胜里票数更高者
        other = "主胜" if votes.get("主胜", 0) >= votes.get("客胜", 0) else "客胜"
        return {
            "pick": f"平局/{other}",
            "confidence": 0.5,
            "reason": f"平局概率高({draw_prob:.0%})，双选建议",
            "skip": False,
        }

    candidates = [direction, alt]
    # 1) EV 打分
    ev_score = {d: 0.0 for d in candidates}
    if ev_results:
        for d in candidates:
            data = ev_results.get(d, {})
            ev = data.get("ev", -999)
            ev_score[d] = ev
    # 2) 投票打分(归一化票差)
    vd, va = votes.get(direction, 0), votes.get(alt, 0)
    total = vd + va
    vote_score = {direction: (vd / total if total else 0.5),
                  alt: (va / total if total else 0.5)}

    # 3) 次回合战意修正: 首回合大分差(≥2球) → 平局概率上升
    tactical_bias = {d: 0.0 for d in candidates}
    if first_leg and first_leg.get("is_second_leg") and first_leg.get("margin", 0) >= 2:
        # 领先方次回合易轮换/保守, 落后方虽猛攻但难净胜, 平局概率上升
        tactical_bias["平局"] = tactical_bias.get("平局", 0) + 0.10

    # 综合: EV 权重最高, 但 EV 全负时靠投票
    score = {}
    for d in candidates:
        s = vote_score[d]  # 基础 = 投票占比(0-1)
        ev = ev_score.get(d, -999)
        if ev != -999:
            # EV 映射到 [0,1] 分数: 正 EV 加分, 负 EV 减分
            s += max(-0.5, min(0.5, ev * 1.5))  # ev 0.3 -> +0.45, ev -0.3 -> -0.45
        s += tactical_bias.get(d, 0)
        score[d] = s

    pick = max(candidates, key=lambda d: score[d])
    gap = abs(score[direction] - score[alt])
    confidence = min(0.85, 0.5 + gap)  # 差距越大信心越高, 上限 0.85

    # 理由
    reasons = []
    ev_d, ev_a = ev_score.get(direction, -999), ev_score.get(alt, -999)
    if ev_d != -999 and ev_a != -999:
        reasons.append(f"EV {direction}{ev_d:+.1%} vs {alt}{ev_a:+.1%}")
    reasons.append(f"票数 {direction}{vd:.1f} vs {alt}{va:.1f}")
    if first_leg and first_leg.get("is_second_leg"):
        margin_txt = f"首回合{first_leg.get('first_leg_score') or '?'}(分差{first_leg.get('margin', '?')})"
        reasons.append(f"次回合{margin_txt}")

    return {
        "pick": pick,
        "confidence": confidence,
        "reason": "; ".join(reasons),
        "skip": False,
    }


def annotate_single_pick_action(single_pick, ev_recommendation):
    """Separate a research direction from an actionable betting decision.

    ``decide_single_pick`` may still identify the strongest direction when the
    EV/evidence gate is closed.  Keep that opinion for audit, but make the
    non-bet state explicit so downstream reports cannot mistake it for a
    purchase recommendation.
    """
    result = dict(single_pick or {})
    action = str((ev_recommendation or {}).get("action") or "skip").lower()
    bettable = action == "bet"
    result["action"] = "bet" if bettable else "observe"
    result["bettable"] = bettable
    if not bettable and result.get("pick"):
        reason = str(result.get("reason") or "").strip()
        suffix = "非下注：EV/证据门禁未通过"
        if suffix not in reason:
            result["reason"] = f"{reason}；{suffix}" if reason else suffix
    return result


def aggregate_directions(predictions, *, allow_single_model_research=False):
    """单选1票/双选0.5; reasoning差与2-1坍缩降权; 强度<60%强制双选。"""
    valid = {md: p for md, p in predictions.items()
             if isinstance(p, dict) and "error" not in p and p.get("decision", "opinion") == "opinion"}
    if not valid:
        return {"error": "所有模型均调用失败",
                "errors": [p for p in predictions.values() if isinstance(p, dict) and "error" in p]}
    if len(valid) < 2 and not allow_single_model_research:
        return {
            "error": "insufficient_model_responses",
            "valid_model_count": len(valid),
            "minimum_valid_models": MIN_VALID_EVIDENCE_MODELS,
            "errors": [p for p in predictions.values() if isinstance(p, dict) and "error" in p],
        }
    # 独立性修正: 同一推理路径的模型权重打折, 防止虚假共识
    model_pool = list(valid.keys())
    model_w = mw.get_all_weights(model_pool)
    votes = Counter()
    score_prefs = Counter()
    ou_prefs = Counter()
    hafu_prefs = Counter()
    prob_acc = [0.0, 0.0, 0.0]
    prob_w = 0.0
    for md, p in valid.items():
        w = model_w.get(md, 0.8)
        if p.get("reasoning_ok") is False:
            w *= 0.5
        if p.get("evidence_gap"):
            w *= 0.85
        if p.get("collapse_score"):
            w *= 0.5
        votes[p["direction"]] += w
        if p.get("alt_direction"):
            votes[p["alt_direction"]] += 0.5 * w
        ranked = p.get("top_scores") or ([p["score_pref"]] if p.get("score_pref") else [])
        for i, score in enumerate(ranked[:3]):
            score_prefs[score] += w * (3 - i) * (0.5 if p.get("collapse_score") else 1.0)
        if p.get("ou25"):
            ou_prefs[p["ou25"]] += w
        if p.get("hafu"):
            hafu_prefs[p["hafu"]] += w
        pr = p.get("probs_1x2")
        if pr:
            for i in range(3):
                prob_acc[i] += pr[i] * w
            prob_w += w
    top_dir, top_votes = votes.most_common(1)[0]
    total_votes = sum(votes.values())
    strength = top_votes / total_votes if total_votes else 0
    top3 = [s for s, _ in score_prefs.most_common(3)]
    top_score = top3[0] if top3 else None
    top_ou = ou_prefs.most_common(1)[0][0] if ou_prefs else None
    top_hafu = hafu_prefs.most_common(1)[0][0] if hafu_prefs else None
    avg_probs = lpr.normalize_probs_1x2(
        [x / prob_w for x in prob_acc]
    ) if prob_w else None
    alt_dir, caution = lpr.force_dual_if_weak(strength, votes, 0.6)
    if len(valid) == 1:
        only_prediction = next(iter(valid.values()))
        alt_dir = only_prediction.get("alt_direction") or next(
            direction for direction in ("平局", "主胜", "客胜") if direction != top_dir
        )
        collapse = lpr.summarize_collapse(valid)
        return {
            "direction": top_dir, "votes": top_votes, "total_votes": total_votes,
            "strength": None, "all_votes": dict(votes),
            "probs_1x2": None,
            "top_score_pref": top_score, "top_scores": top3, "score_prefs": dict(score_prefs),
            "top_ou25": top_ou, "all_ou25": dict(ou_prefs),
            "top_hafu": top_hafu, "all_hafu": dict(hafu_prefs),
            "alt_direction": alt_dir, "caution": True,
            "single_model": True, "research_only": True, "action": "observe",
            "reason": "single_model_no_consensus",
            "valid_model_count": 1,
            "minimum_valid_models": MIN_VALID_EVIDENCE_MODELS,
            "collapse_flags": collapse.get("flags") or [],
            "individual": fp.standardize_individual_predictions(predictions, list(predictions)),
        }
    if len(valid) < MIN_VALID_EVIDENCE_MODELS:
        caution = True
        ranked_alternatives = [(direction, count) for direction, count in votes.most_common()
                               if direction != top_dir]
        alt_dir = ranked_alternatives[0][0] if ranked_alternatives else next(
            direction for direction in ("平局", "主胜", "客胜") if direction != top_dir
        )
    collapse = lpr.summarize_collapse(valid)
    return {
        "direction": top_dir, "votes": top_votes, "total_votes": total_votes,
        "strength": strength, "all_votes": dict(votes),
        "probs_1x2": avg_probs,
        "top_score_pref": top_score, "top_scores": top3, "score_prefs": dict(score_prefs),
        "top_ou25": top_ou, "all_ou25": dict(ou_prefs),
        "top_hafu": top_hafu, "all_hafu": dict(hafu_prefs),
        "alt_direction": alt_dir, "caution": caution,
        "valid_model_count": len(valid),
        "minimum_valid_models": MIN_VALID_EVIDENCE_MODELS,
        "collapse_flags": collapse.get("flags") or [],
        "individual": fp.standardize_individual_predictions(predictions, list(predictions)),
    }



def enforce_evidence_gap(aggregation):
    """A documented evidence gap always makes the final direction a cautious dual."""
    aggregation = dict(aggregation)
    direction = aggregation.get("direction")
    alt = aggregation.get("alt_direction")
    if not alt or alt == direction:
        votes = aggregation.get("all_votes") or {}
        ranked_alternatives = sorted(
            ((candidate, count) for candidate, count in votes.items() if candidate != direction),
            key=lambda item: (-item[1], item[0]),
        )
        alt = ranked_alternatives[0][0] if ranked_alternatives else next(
            candidate for candidate in ("平局", "主胜", "客胜") if candidate != direction
        )
    aggregation.update({"alt_direction": alt, "caution": True, "evidence_gap": True})
    return aggregation


def enforce_home_bias_breaker(results):
    """主胜比例熔断：批内主胜方向占比过高时，把强度最低的主胜场次改判为次高方向。

    results: list of (match_idx, match, agg)，agg 为 aggregate_directions 输出。
    返回 (corrections, report)：
      corrections = {match_idx: 新方向}（被熔断改判的场次）
      report = 描述行列表（供打印）
    """
    total = len(results)
    if total < HOME_BIAS_MIN_SAMPLE:
        return {}, []
    home = [(idx, m, agg) for idx, m, agg in results if agg.get("direction") == "主胜"]
    n_home = len(home)
    if n_home / total < HOME_BIAS_THRESHOLD:
        return {}, []
    allowed = int(total * HOME_BIAS_THRESHOLD)
    excess = n_home - allowed
    if excess <= 0:
        return {}, []
    # 强度最低的主胜场次优先改判（最没把握的先改）
    home_sorted = sorted(home, key=lambda r: r[2].get("strength", 0.0))
    corrections = {}
    report = [
        f"主胜比例熔断触发: 本批 {total} 场中主胜 {n_home} 场 ({n_home/total:.0%}) ≥ {HOME_BIAS_THRESHOLD:.0%}",
        f"熔断 {excess} 场（强度最低的主胜场次）改判为次高方向:",
    ]
    for idx, m, agg in home_sorted[:excess]:
        new_dir = agg.get("alt_direction")
        if not new_dir or new_dir == "主胜":
            votes = agg.get("all_votes", {})
            others = sorted(((d, v) for d, v in votes.items() if d != "主胜"), key=lambda x: -x[1])
            new_dir = others[0][0] if others else "平局"
        corrections[idx] = new_dir
        report.append(
            f"  {m.get('match_num','?')} {m.get('home','')}vs{m.get('away','')}: "
            f"主胜(强度{agg.get('strength',0)*100:.0f}%) → {new_dir}"
        )
    return corrections, report


def _stable_sha256(value):
    """Hash JSON data with a deterministic, Unicode-preserving encoding."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_match_id(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower().startswith("sporttery-"):
        rest = text.split("-", 1)[1].strip()
        return f"sporttery-{rest}" if rest else None
    if text.isdigit():
        return f"sporttery-{text}"
    return None


def build_audit_record(aggregation, models_used, prompt, evidence_status, ev_recommendation=None,
                       single_pick=None, evidence_audit=None, consensus_gate=None, match=None):
    """Build the successful per-match JSON audit payload without calling an LLM."""
    if aggregation.get("error"):
        raise ValueError("cannot audit a failed aggregation")
    record = dict(aggregation)
    record["models_used"] = list(models_used)
    record["prediction_as_of"] = datetime.now(timezone.utc).isoformat()
    if match:
        record["match_id"] = _normalize_match_id(
            match.get("match_id") or (match.get("sporttery_meta") or {}).get("match_id")
        )
        record["match_num"] = match.get("match_num")
        record["home"] = match.get("home")
        record["away"] = match.get("away")
        record["kickoff"] = match.get("kickoff_iso") or match.get("kickoff")
        record["league"] = match.get("league")
        record["llm_track_contract"] = ltc.validate_prediction_record(record)
        record["evidence_manifest"] = _build_llm_evidence_manifest(
            match, evidence_status, evidence_status.get("evidence_text", "")
        )
    record.update({
        "individual": fp.standardize_individual_predictions(
            aggregation.get("individual", {}), models_used
        ),
        "llm_model_pool_sha256": hashlib.sha256(
            json.dumps(models_used, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "aggregation_rule_version": AGGREGATION_RULE_VERSION,
        "aggregation_rule_sha256": _stable_sha256(AGGREGATION_RULE_SPEC),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "evidence_file_sha256": evidence_status["evidence_file_sha256"],
        "evidence_source": evidence_status.get("evidence_source", "web_primary"),
        "mcp_evidence_file_sha256": evidence_status.get("mcp_evidence_file_sha256"),
        "evidence_collected_at_min": evidence_status["evidence_collected_at_min"],
        "evidence_collected_at_max": evidence_status["evidence_collected_at_max"],
        "ev_recommendation": ev_recommendation,
        "single_pick": single_pick,
        "evidence_audit": evidence_audit,
        "consensus_gate": consensus_gate,
    })
    return record


def _build_llm_evidence_manifest(match, evidence_status, evidence_text):
    """Convert existing evidence-boundary output into the machine manifest."""
    text = evidence_text or ""
    def has(*terms):
        lowered = text.lower()
        return any(term.lower() in lowered for term in terms)

    def has_usable(*terms):
        for line in text.splitlines():
            lowered = line.lower()
            if not line.lstrip().startswith(("-", "*")) or "source(" not in lowered:
                continue
            if any(term.lower() in lowered for term in terms) and not any(
                marker in line for marker in EVIDENCE_GAP_MARKERS
            ):
                return True
        return False

    evidence = {
        "recent_form": {"home": [1] if has_usable("近5场", "最近5场", "近况") else [],
                        "away": [1] if has_usable("近5场", "最近5场", "近况") else []},
        "crs": match.get("crs") or ([1] if has("CRS", "比分赔率") else []),
        "ttg": match.get("ttg") or ([1] if has("TTG", "总进球赔率") else []),
        "hafu": match.get("hafu") or ([1] if has("HAFU", "半全场赔率") else []),
        "injuries_status": (
            "EMPTY_UNCONFIRMED" if has("伤停状态=EMPTY_UNCONFIRMED", "伤停=EMPTY_UNCONFIRMED")
            else ("UNAVAILABLE" if has("伤停状态=UNAVAILABLE", "伤停=UNAVAILABLE")
                  else ("AVAILABLE" if has_usable("伤停", "缺阵") else "UNAVAILABLE"))
        ),
        "lineups_status": (
            "EMPTY_UNCONFIRMED" if has("首发状态=EMPTY_UNCONFIRMED", "首发=EMPTY_UNCONFIRMED")
            else ("UNAVAILABLE" if has("首发状态=UNAVAILABLE", "首发=UNAVAILABLE")
            else ("PREDICTED" if has("首发状态=PREDICTED", "首发状态 | PREDICTED", "预计首发")
                  else ("AVAILABLE" if has_usable("首发", "阵容") else "UNAVAILABLE")))
        ),
        "collected_at": evidence_status.get("evidence_collected_at_max"),
    }
    # Prefer the structured, identity- and time-gated chain attached by the
    # collector over Markdown keyword heuristics.  The latter can say
    # FORM_UNAVAILABLE even when the snapshot contains two complete recent
    # five-match lists (the labels may be English or rendered as JSON).
    chain = match.get("evidence_chain") or {}
    recent = chain.get("recent_form") if isinstance(chain, dict) else None
    if isinstance(recent, dict):
        status = str(recent.get("status") or "").upper()
        value = recent.get("value") or {}
        home = value.get("home") if isinstance(value, dict) else None
        away = value.get("away") if isinstance(value, dict) else None
        if status in {"VALID", "OK", "AVAILABLE", "FRESH", "AGING"}:
            evidence["recent_form"] = {
                "home": list(home or [])[:5], "away": list(away or [])[:5]
            }
    for field, key in (("injury", "injuries_status"), ("suspensions", "suspensions_status"),
                       ("starting_xi", "lineups_status")):
        entry = chain.get(field) if isinstance(chain, dict) else None
        if not isinstance(entry, dict):
            continue
        state = str(entry.get("status") or "").upper()
        if field == "starting_xi":
            evidence[key] = state if state in {"VALID", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING"} else "UNAVAILABLE"
        elif field == "injury":
            evidence[key] = "AVAILABLE" if state in {"VALID", "OK", "AVAILABLE", "FRESH", "AGING"} else state or "UNAVAILABLE"
        else:
            evidence[key] = state or "UNAVAILABLE"
    manifest = ltc.build_evidence_manifest(match, evidence)
    if evidence_status.get("collection_status") == "ONLY_ODDS":
        manifest["collection_status"] = "ONLY_ODDS"
    return manifest


def build_skip_audit_record(predictions, models_used, prompt, evidence_status,
                            evidence_audit, consensus_gate, aggregation_error, match=None):
    """Preserve a complete audit trail when the two-voter gate skips a match."""
    record = {
        "status": "skip",
        "action": "skip",
        "reason": consensus_gate.get("reason") or aggregation_error,
        "aggregation_error": aggregation_error,
        "individual": fp.standardize_individual_predictions(predictions, models_used),
        "llm_model_pool_sha256": hashlib.sha256(
            json.dumps(models_used, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "evidence_file_sha256": evidence_status["evidence_file_sha256"],
        "evidence_source": evidence_status.get("evidence_source", "web_primary"),
        "mcp_evidence_file_sha256": evidence_status.get("mcp_evidence_file_sha256"),
        "evidence_collected_at_min": evidence_status["evidence_collected_at_min"],
        "evidence_collected_at_max": evidence_status["evidence_collected_at_max"],
        "evidence_audit": evidence_audit,
        "consensus_gate": consensus_gate,
        "models_used": list(models_used),
        "prediction_as_of": datetime.now(timezone.utc).isoformat(),
    }
    if match:
        record["match_id"] = ltc.normalize_match_id(
            match.get("match_id") or (match.get("sporttery_meta") or {}).get("match_id")
        )
        record["home"] = match.get("home")
        record["away"] = match.get("away")
        record["kickoff"] = match.get("kickoff_iso") or match.get("kickoff")
        record["llm_track_contract"] = ltc.validate_prediction_record({
            **record, "single_model": len(models_used) == 1,
            "research_only": True if len(models_used) == 1 else False,
            "action": "observe" if len(models_used) == 1 else "skip",
            "reason": "single_model_no_consensus" if len(models_used) == 1 else record["reason"],
        })
        record["evidence_manifest"] = _build_llm_evidence_manifest(match, evidence_status, "")
    return record


def main():
    ap = argparse.ArgumentParser(description="LLM轨道: 证据驱动定性预测")
    ap.add_argument("--input", required=True, help="采集器输出的JSON文件")
    ap.add_argument("--evidence-dir", required=True, help="证据文件目录")
    ap.add_argument("--models", nargs="+", default=fp.DEFAULT_MODELS)
    ap.add_argument("--match-id", type=int, default=None)
    ap.add_argument("--max-matches", type=int, default=0)
    ap.add_argument("--min-match", type=int, default=0, help="分批预测：从第 N 场开始（序号按 raw 原始编号）")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    selected_matches = select_matches(data["matches"], args.match_id, args.max_matches, args.min_match)
    if not selected_matches:
        print("没有符合条件的比赛")
        return

    evidence_files = load_evidence(args.evidence_dir)
    print(f"📁 证据文件: {len(evidence_files)} 个")
    for n in sorted(evidence_files):
        print(f"   - {n}")

    voter_models = list(dict.fromkeys(args.models))
    print(f"🎯 共 {len(selected_matches)} 场比赛待预测, {EVIDENCE_AUDITOR_MODEL} 证据审计 + {len(voter_models)} 个投票模型\n")

    # 全局比分坍缩统计：收集每场 top 比分，循环结束后做跨场次分布检测。
    score_prefs_collected = []
    # 主胜比例熔断：收集每场 (match_idx, match, agg)，循环结束后做方向坍缩检测。
    breaker_results = []

    for i, (match_idx, m) in enumerate(selected_matches, 1):
        if i > 1:
            print("\n⏳ 场次冷却 5 秒...")
            time.sleep(5)
        idx = m.get("match_num", "")
        # 使用 raw 文件中的原始场次序号，避免 --match-id 过滤后重新编号而错配证据。
        # kickoff_iso 带明确时区（体彩原始数据为 Asia/Shanghai），用于与
        # collected_at 的 ISO 时间戳比较；kickoff_local 仅是展示用回退字段。
        kickoff = m.get("kickoff_iso") or m.get("kickoff") or m.get("kickoff_local")
        now = datetime.now(timezone.utc)
        ev_name = match_evidence_file(match_idx, evidence_files)
        mcp_name = match_mcp_file(match_idx, evidence_files, match=m)
        odds_available = bool(m.get("model_odds") or m.get("crs") or m.get("ttg") or m.get("hafu"))
        if ev_name:
            primary_evidence = evidence_files[ev_name]
            evidence_status = assess_evidence(
                primary_evidence, kickoff=kickoff, now=now, allow_odds_only=odds_available
            )
            if not evidence_status["ok"]:
                print(json.dumps({"match_index": i, "status": "evidence_insufficient", "reason": evidence_status["reason"]}, ensure_ascii=False))
                continue
            evidence_status["evidence_source"] = "web_primary"
            ev_text = primary_evidence
            if mcp_name:
                mcp_status = assess_mcp_evidence(evidence_files[mcp_name], kickoff, match=m)
                if mcp_status["ok"]:
                    ev_text += "\n\n" + evidence_files[mcp_name]
                    evidence_status["evidence_source"] = "web_primary_with_mcp"
                    evidence_status["mcp_evidence_file_sha256"] = hashlib.sha256(
                        evidence_files[mcp_name].encode("utf-8")
                    ).hexdigest()
                    print(f"   数据块: {mcp_name} (MCP 已拼入)")
                else:
                    print(f"   ⚠️ MCP 数据块已拒绝: {mcp_status['reason']}")
        else:
            if not mcp_name:
                print(json.dumps({"match_index": i, "status": "evidence_insufficient", "reason": "missing_evidence_file"}, ensure_ascii=False))
                continue
            mcp_status = assess_mcp_evidence(evidence_files[mcp_name], kickoff, match=m)
            if not mcp_status["ok"]:
                print(json.dumps({"match_index": i, "status": "evidence_insufficient", "reason": mcp_status["reason"]}, ensure_ascii=False))
                continue
            ev_text = evidence_files[mcp_name]
            evidence_status = assess_evidence(
                ev_text, kickoff=kickoff, now=now, allow_odds_only=odds_available
            )
            if not evidence_status["ok"]:
                print(json.dumps({"match_index": i, "status": "evidence_insufficient", "reason": evidence_status["reason"]}, ensure_ascii=False))
                continue
            ev_name = mcp_name
            evidence_status["evidence_source"] = "mcp_primary"
            evidence_status["mcp_evidence_file_sha256"] = evidence_status["evidence_file_sha256"]

        # 仅在内存中交给契约清单生成器，正式记录仍保存哈希和时间戳，
        # 不把整篇原始证据重复嵌入预测 JSON。
        evidence_status["evidence_text"] = ev_text
        evidence_manifest = _build_llm_evidence_manifest(m, evidence_status, ev_text)
        evidence_status["collection_status"] = evidence_manifest.get("collection_status")
        evidence_status["gap_sections"] = evidence_manifest.get("gap_sections", [])

        print("=" * 64)
        print(f"⚽ 第{i}/{len(selected_matches)}场 [{idx}] {m['home']} VS {m['away']} | {m.get('league', '')} | {m.get('kickoff_local', '')}")
        source_label = " (MCP 主证据)" if evidence_status["evidence_source"] == "mcp_primary" else ""
        print(f"   证据: {ev_name}{source_label}")
        print("=" * 64)

        evidence_catalog = build_evidence_catalog(ev_text)
        prompt = build_evidence_prompt(m, ev_text, match_idx)
        evidence_audit = call_evidence_auditor(
            fp.get_client(fp.provider_for(EVIDENCE_AUDITOR_MODEL)), prompt, evidence_catalog)
        if "error" in evidence_audit:
            print(json.dumps({"match_index": i, "status": "evidence_audit_failed",
                              "reason": evidence_audit["error"]}, ensure_ascii=False))
            continue
        voter_prompt = build_voter_prompt(prompt, evidence_audit)
        predictions = {}
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(call_evidence_model,
                              fp.get_client(fp.provider_for(md)), md, voter_prompt, voter_models,
                              evidence_catalog): md
                    for md in voter_models}
            for fut in as_completed(futs):
                md, p = fut.result()
                with lock:
                    predictions[md] = p
                if "error" in p:
                    print(f"     ✗ [{md}] 失败: {p['error'][:55]}")
                else:
                    if p.get("decision") == "abstain":
                        reason_codes = ",".join(p.get("reason_codes") or []) or "unspecified"
                        print(f"     ⊘ [{md.split('/')[-1].split(':')[0][:18]:<18}] -> 弃权 ({reason_codes})")
                        continue
                    alt = f" / {p['alt_direction']}" if p.get("alt_direction") else ""
                    sp = f" 比分偏好:{p['score_pref']}" if p.get("score_pref") else ""
                    print(f"     ✓ [{md.split('/')[-1].split(':')[0][:18]:<18}] "
                          f"-> {p['direction']}{alt}{sp}")

        single_model_mode = len(voter_models) == 1
        agg = aggregate_directions(predictions, allow_single_model_research=single_model_mode)
        consensus_gate = two_voter_consensus(predictions, voter_models)
        if consensus_gate["status"] == "skip":
            print(f"  🚫 最终门控: skip ({consensus_gate['reason']})")
            print(json.dumps(build_skip_audit_record(
                predictions, voter_models, voter_prompt, evidence_status,
                evidence_audit, consensus_gate, agg.get("error", consensus_gate["reason"]), match=m,
            ), ensure_ascii=False))
            continue
        if evidence_status["evidence_gap"] and "error" not in agg:
            agg = enforce_evidence_gap(agg)
        if "error" in agg:
            print(f"  [失败] {agg['error']}")
            print(json.dumps(build_skip_audit_record(
                predictions, voter_models, voter_prompt, evidence_status,
                evidence_audit, consensus_gate, agg["error"], match=m,
            ), ensure_ascii=False))
            continue

        if agg.get("single_model"):
            agg = eo.apply_collection_degradation(agg, evidence_status.get("collection_status", "PARTIAL"))
            print(f"\n  🔎 DeepSeek V4 Flash 单模型研究意见: {agg['direction']}（非共识，不显示强度/概率）")
            print(f"  🚫 下注建议: 跳过（{agg['reason']}）")
            top3 = agg.get("top_scores") or ([agg["top_score_pref"]] if agg.get("top_score_pref") else [])
            print(f"  🎯 比分研究偏好: {', '.join(top3) if top3 else '分散'}")
            print(f"  📦 大小球研究偏好: {agg.get('top_ou25') or '-'}")
            print(f"  ⏱️ 半全场研究偏好: {agg.get('top_hafu') or '-'}")
            print(json.dumps(build_audit_record(
                agg, voter_models, voter_prompt, evidence_status,
                ev_recommendation={"action": "skip", "reason": "single_model_no_consensus"},
                single_pick={"pick": None, "confidence": None, "reason": "single_model_no_consensus",
                             "skip": True, "action": "observe", "bettable": False},
                evidence_audit=evidence_audit, consensus_gate=consensus_gate,
                match=m,
            ), ensure_ascii=False))
            continue

        agg = eo.apply_collection_degradation(agg, evidence_status.get("collection_status", "PARTIAL"))
        breaker_results.append((match_idx, m, dict(agg)))

        print(f"\n  📊 综合方向: {agg['direction']}  "
              f"({agg['votes']:.1f}/{agg['total_votes']:.1f}票, "
              f"强度{agg['strength']*100:.0f}%)")
        # 冷门/谨慎标记
        if is_two_legged(m.get("league", ""), ev_text or ""):
            print("  ⚠️ 两回合制/杯赛场次(冷门风险高)")
        if agg.get("caution"):
            alt_dir = agg.get("alt_direction") or "?"
            caution_reasons = []
            if agg["strength"] < AGGREGATION_RULE_SPEC["weak_strength_threshold"]:
                caution_reasons.append(f"强度<{AGGREGATION_RULE_SPEC['weak_strength_threshold'] * 100:.0f}%")
            if agg.get("evidence_gap"):
                caution_reasons.append("证据存在缺口")
            reason_text = "、".join(caution_reasons) or "聚合风控"
            print(f"  🚨 谨慎({reason_text}): 建议双选 {agg['direction']}/{alt_dir}")
        if agg.get("probs_1x2"):
            ph, pd, pa = agg["probs_1x2"]
            print(f"  📈 1X2概率: 主{ph:.1f} / 平{pd:.1f} / 客{pa:.1f}（LLM加权换算，非量化校准）")
        top3 = agg.get("top_scores") or ([agg["top_score_pref"]] if agg.get("top_score_pref") else [])
        print(f"  🎯 比分Top3: {', '.join(top3) if top3 else '分散'}")
        if agg.get("top_score_pref"):
            score_prefs_collected.append(agg["top_score_pref"])
        print(f"  📦 大小球2.5: {agg.get('top_ou25') or '-'}")
        print(f"  ⏱️ 半全场: {agg.get('top_hafu') or '-'}")
        if agg.get("collapse_flags"):
            print(f"  ⚠️ 坍缩标记: {', '.join(agg['collapse_flags'])}")
        # ---------- EV 下注推荐 ----------
        mo = m.get("model_odds") or []
        ev_rec = None
        if evidence_status.get("collection_status") == "ONLY_ODDS":
            ev_rec = {"action": "skip", "reason": "odds_only_evidence"}
            print("\n  💰 下注推荐: 跳过(仅有官方赔率，无独立证据；不计算EV/Kelly)")
        elif all(isinstance(x, (int, float)) and x > 0 for x in mo[:3]) if len(mo) >= 3 else False:
            # 概率来源取轨道A融合引擎的 final_1x2_pct（核心引擎按联赛校准过的真概率）。
            # 取不到就传 None，ev_calculator 会 fail closed——**不得回退到投票比例**。
            fusion_probs = fps.load_fusion_probabilities(m.get("match_id"))
            ev_rec = evc.generate_betting_recommendation(
                votes=agg["all_votes"],
                model_odds=list(mo[:3]),
                strength=agg["strength"],
                evidence_gap=bool(agg.get("evidence_gap")) or bool(evidence_status.get("evidence_gap")),
                calibrated_probs=(fusion_probs or {}).get("probabilities"),
                prob_source=(fusion_probs or {}).get("source"),
                prob_calibration_status=(fusion_probs or {}).get("calibration_status", "UNFITTED"),
                market_derived=bool((fusion_probs or {}).get("market_derived")),
            )
            if fusion_probs:
                ev_rec["fusion_reference"] = {
                    k: fusion_probs.get(k) for k in
                    ("prediction_id", "model_version", "snapshot_type", "mode",
                     "market_dependency_pct", "calibration_basis")
                }
            print("\n  💰 下注推荐:")
            for line in evc.format_betting_advice(ev_rec).split("\n"):
                print(f"     {line}")
            if not fusion_probs:
                print("     （量化轨尚未登记该场，无概率来源）")
        else:
            print("\n  💰 下注推荐: 跳过(官方赔率缺失或非法)")
        # ---------- 单选主推(双选→单选决策层) ----------
        fl = extract_first_leg_info(m.get("league", ""), ev_text or "", home=m.get("home", ""), away=m.get("away", ""))
        # 2026-08-15：只有 action=bet 的 EV 才允许进入决策层。此前无论 skip 与否都把
        # ev_analysis 传下去，等于绕开 ev_calculator 自己的风控闸门——这正是 8-15 报告
        # 把 skip 场次塞进推荐表的同一条通路，只不过那次发生在人工摘录环节。
        ev_results = (ev_rec.get("ev_analysis", {}) or {}) if (
            isinstance(ev_rec, dict) and ev_rec.get("action") == "bet") else {}
        if evidence_status.get("collection_status") == "ONLY_ODDS":
            sp = {"pick": None, "confidence": None, "reason": "odds_only_evidence", "skip": True}
        else:
            sp = decide_single_pick(agg, ev_results, fl, match=m)
        sp = annotate_single_pick_action(sp, ev_rec)
        confidence_text = "—" if sp.get("confidence") is None else f"{sp['confidence']*100:.0f}%"
        print(f"  🎯 下注建议: {sp['pick'] or '观察'} (信心{confidence_text}) | {sp['reason']}")
        if fl.get("is_second_leg"):
            if fl.get("margin") is not None and fl["margin"] >= 2:
                print(f"  ⚠️ 次回合战意提示: 首回合{fl.get('first_leg_score') or '?'}(净胜{fl['margin']}球) → 领先方可能轮换/保守, 平局概率上升")
            else:
                print(f"  ⚠️ 次回合战意提示: 首回合{fl.get('first_leg_score') or '?'}(分差小) → 领先方优势有限, 战意仍强")
        print("  🗳️ 投票分布: " + " | ".join(
            f"{k}:{v:.1f}" for k, v in
            sorted(agg['all_votes'].items(), key=lambda x: -x[1])))
        print("  🤖 各模型判断:")
        for md, p in agg["individual"].items():
            if p["status"] == "failed":
                print(f"     [{md.split('/')[-1].split(':')[0][:20]:<20}] 失败 — {p['error'][:60]}")
                continue
            alt = f" (备选:{p['alt_direction']})" if p.get("alt_direction") else ""
            score_txt = f" 比分:{p['score_pref']}" if p.get("score_pref") else ""
            print(f"     [{md.split('/')[-1].split(':')[0][:20]:<20}] "
                  f"{p['direction']}{alt}{score_txt} — {p['reasoning'][:60]}")
        print(json.dumps(build_audit_record(
            agg, voter_models, voter_prompt, evidence_status,
            ev_recommendation=ev_rec, single_pick=sp,
            evidence_audit=evidence_audit, consensus_gate=consensus_gate,
            match=m,
        ), ensure_ascii=False))
        print()

    # ---------- 主胜比例熔断（方向坍缩修正） ----------
    corrections, breaker_report = enforce_home_bias_breaker(breaker_results)
    if corrections:
        print("=" * 64)
        for line in breaker_report:
            print("  " + line)
        print("=" * 64)
        # 熔断后最终方向总表（权威结论，改判已写回）
        print("🔒 熔断后最终方向总表:")
        for idx, m, agg in breaker_results:
            final_dir = corrections.get(idx, agg["direction"])
            mark = "  ⚠️熔断改判" if idx in corrections else ""
            print(f"    {m.get('match_num','?'):<8} {m.get('home','')}vs{m.get('away','')}: {final_dir}{mark}")
        print("  注: 登记/回测方向以本表熔断后方向为准（纠正赛季初主胜系统性高估）。")
        print("=" * 64)
        print()

    # ---------- 全局比分坍缩统计（跨场次分布检测） ----------
    if len(score_prefs_collected) >= 3:
        sc = Counter(score_prefs_collected)
        total = len(score_prefs_collected)
        top, n = sc.most_common(1)[0]
        ratio = n / total
        print("=" * 64)
        if ratio >= lpr.SCORE_COLLAPSE_RATIO:
            print(f"⚠️ 全局比分坍缩警报: 本批 {total} 场中, 比分 {top} 出现 {n} 场 ({ratio*100:.0f}%)")
            print("   分布: " + " | ".join(f"{k}:{v}场" for k, v in sc.most_common()))
            print(f"   判定: 单一比分占比 ≥ {lpr.SCORE_COLLAPSE_RATIO*100:.0f}% = 模型在套默认模板, 非独立判断。")
            print("   建议: 该比分 Top1 不可作下注依据, 应视为坍缩噪声。")
        else:
            print(f"✅ 比分分布健康: {total} 场 top 比分分布 " + " | ".join(f"{k}:{v}场" for k, v in sc.most_common()))
        print("=" * 64)


if __name__ == "__main__":
    main()

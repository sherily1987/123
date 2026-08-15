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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import football_predictor as fp
import llm_prompt_rules as lpr

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


def match_mcp_file(match_idx, evidence_files):
    """按序号前缀匹配 *_mcp.md (apifootball MCP 数据证据块, mcp_evidence.py 生成)。"""
    pattern = re.compile(rf"^evidence_{match_idx:03d}(?:_|\.)", re.I)
    matches = [name for name in evidence_files
               if pattern.match(name) and name.lower().endswith("_mcp.md")]
    return matches[0] if len(matches) == 1 else None


REQUIRED_EVIDENCE_SECTIONS = {
    1: r"伤停|阵容",
    2: r"战意|动机",
    3: r"近况|状态",
    4: r"主客|旅行|天气",
    5: r"赔率",
    6: r"身份|核验",
}
EVIDENCE_GAP_MARKERS = ("证据缺口", "未检索到", "未拿到", "未做", "不足", "缺失")
AGGREGATION_RULE_VERSION = "evidence-direction-v1"
AGGREGATION_RULE_SPEC = {
    "alt_direction_weight": 0.5,
    "collapse_score_weight": 0.5,
    "evidence_gap_weight": 0.85,
    "reasoning_invalid_weight": 0.5,
    "weak_strength_threshold": 0.6,
}
MIN_VALID_EVIDENCE_MODELS = 2
EVIDENCE_AUDITOR_MODEL = "deepseek/deepseek-chat"


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


def assess_evidence(evidence_text, kickoff=None, now=None):
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
    if not content_fact_lines or all(any(marker in line for marker in EVIDENCE_GAP_MARKERS) for line in content_fact_lines):
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
        "evidence_gap": any(marker in evidence_text for marker in EVIDENCE_GAP_MARKERS),
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
        if (sporttery_id != str(match.get("match_id", "")) or
                home != str(match.get("home", "")) or
                away != str(match.get("away", ""))):
            return {"ok": False, "reason": "mcp_match_identity_mismatch"}
    return {"ok": True}


def select_matches(matches, match_id=None, max_matches=0):
    """Select matches while retaining their 1-based raw-file indices."""
    selected = list(enumerate(matches, 1))
    if max_matches:
        selected = selected[:max_matches]
    if match_id is not None:
        selected = [(idx, match) for idx, match in selected
                    if str(match.get("match_id")) == str(match_id)]
    return selected


def evidence_collection_label(evidence_text):
    """Use the evidence timestamp rather than a hard-coded collection date."""
    timestamps = re.findall(r"collected_at\(\s*([^)]*?)\s*\)", evidence_text or "", re.I)
    return f"采集时间 {timestamps[0]}" if timestamps else "当前采集证据"


def build_evidence_catalog(evidence_text):
    """将已通过时间和来源门禁的 Markdown 事实转为紧凑证据目录。"""
    catalog = []
    for line in (evidence_text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            continue
        fact = stripped[1:].strip().split("| source(", 1)[0].strip()
        source_match = re.search(r"source\(\s*(https?://[^)\s]+)\s*\)", stripped, re.I)
        if not fact or not source_match:
            continue
        lowered = fact.lower()
        if any(marker in lowered for marker in ("来源冲突", "source_conflict", "说法冲突")):
            status = "SOURCE_CONFLICT"
        elif any(marker in lowered for marker in ("无记录", "0条", "未获得", "未检索到", "未拿到", "证据缺口")):
            status = "UNAVAILABLE"
        elif any(marker in lowered for marker in ("双源一致", "交叉验证", "verified_multi_source")):
            status = "VERIFIED_MULTI_SOURCE"
        else:
            status = "SINGLE_SOURCE"
        catalog.append({"id": f"E{len(catalog) + 1}", "status": status,
                        "fact": fact, "source": source_match.group(1)})
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
    catalog = build_evidence_catalog(evidence_text)
    lines.append(f"\n=== 结构化证据（{evidence_collection_label(evidence_text)}） ===")
    lines.append(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")))
    lines.append("\n只使用上述 E 编号。每个市场证据不足时单独填 null；整体不足时 decision=abstain。")
    return "\n".join(lines)


def parse_evidence_audit(content, evidence_catalog):
    """校验 DeepSeek 的无方向证据审计结果。"""
    text = (content or "").strip()
    text = re.sub(r"^```(json)?\s*|\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"error": "audit_missing_json"}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"error": f"audit_invalid_json:{exc}"}
    if {"direction", "alt_direction", "score_pref", "ou25", "hafu"} & set(data):
        return {"error": "audit_contains_prediction_fields"}
    catalog = {str(item.get("id")): item for item in (evidence_catalog or [])}
    usable = [str(value) for value in (data.get("usable_evidence_ids") or [])]
    unusable = [str(value) for value in (data.get("unusable_evidence_ids") or [])]
    conflicts = [str(value) for value in (data.get("conflict_evidence_ids") or [])]
    if any(value not in catalog for value in usable + unusable + conflicts):
        return {"error": "audit_unknown_evidence_id"}
    if any(catalog[value].get("status") not in ("SINGLE_SOURCE", "VERIFIED_MULTI_SOURCE") for value in usable):
        return {"error": "audit_marks_unusable_evidence_as_usable"}
    if any(catalog[value].get("status") != "UNAVAILABLE" for value in unusable):
        return {"error": "audit_unavailable_status_mismatch"}
    if any(catalog[value].get("status") != "SOURCE_CONFLICT" for value in conflicts):
        return {"error": "audit_conflict_status_mismatch"}
    readiness = data.get("market_readiness") or {}
    required = ("one_x_two", "score", "ou25", "hafu")
    if any(not isinstance(readiness.get(name), bool) for name in required):
        return {"error": "audit_invalid_market_readiness"}
    return {"status":"ok","usable_evidence_ids":usable,"unusable_evidence_ids":unusable,
            "conflict_evidence_ids":conflicts,"gaps":[str(v) for v in (data.get("gaps") or [])],
            "market_readiness":{name:readiness[name] for name in required},
            "summary":str(data.get("summary") or "").strip()[:220]}


def build_voter_prompt(base_prompt, evidence_audit):
    audit = {key:value for key,value in evidence_audit.items() if key != "status"}
    return (f"{base_prompt}\n\n=== DeepSeek 证据审计（无预测方向） ===\n"
            f"{json.dumps(audit, ensure_ascii=False, separators=(',', ':'))}\n"
            "请独立判断；审计结果只说明证据可用性，不是另一个模型的比赛结论。")


def two_voter_consensus(predictions, voter_models):
    voter_models = list(voter_models)
    if len(voter_models) != 2:
        return {"status":"skip","action":"skip","reason":"requires_exactly_two_voters","voter_models":voter_models}
    records = [predictions.get(model) for model in voter_models]
    if any(not isinstance(item,dict) or "error" in item or item.get("decision") != "opinion" for item in records):
        return {"status":"skip","action":"skip","reason":"voter_abstained_or_failed","voter_models":voter_models}
    directions = [item.get("direction") for item in records]
    if directions[0] != directions[1]:
        return {"status":"skip","action":"skip","reason":"voter_disagreement","voter_models":voter_models,"directions":directions}
    return {"status":"consensus","action":"research_opinion","direction":directions[0],"voter_models":voter_models}


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
    sp = normalize_score_pref(data.get("score_pref"))
    reasoning = str(data.get("summary") or data.get("reasoning") or "").strip()[:220]
    ou25 = lpr.normalize_ou25(data.get("ou25"))
    hafu = lpr.normalize_hafu(data.get("hafu"))
    egap = bool(data.get("evidence_gap", False))
    evidence_ids = [str(value).strip() for value in (data.get("evidence_ids") or []) if str(value).strip()]
    reason_codes = [str(value).strip() for value in (data.get("reason_codes") or []) if str(value).strip()]
    unsupported = [str(value).strip() for value in (data.get("unsupported_assumptions") or []) if str(value).strip()]
    catalog_by_id = {str(item.get("id")): item for item in (evidence_catalog or [])}
    invalid_ids = [value for value in evidence_ids if evidence_catalog is not None and value not in catalog_by_id]
    usable_ids = [value for value in evidence_ids if catalog_by_id.get(value, {}).get("status") in ("SINGLE_SOURCE", "VERIFIED_MULTI_SOURCE")]
    if decision == "opinion" and evidence_catalog is not None and (invalid_ids or not usable_ids or unsupported):
        decision = "abstain"
        direction = alt = sp = ou25 = hafu = None
        egap = True
        reason_codes.append("INVALID_OR_UNUSABLE_EVIDENCE")
    rq = lpr.reasoning_quality(reasoning)
    reasoning_ok = bool(reasoning) if is_new_contract else bool(rq.get("ok"))
    if not reasoning_ok:
        egap = True
    collapse_score = bool(sp in lpr.LOW_SCORE_SET and not reasoning_ok)
    return {
        "decision": decision,
        "direction": direction,
        "alt_direction": alt,
        "score_pref": sp,
        "ou25": ou25,
        "hafu": hafu,
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

    raw = str(raw).strip()
    if raw in CRS_VALID:
        return raw
    m = re.match(r"^(\d+)-(\d+)$", raw)
    if m:
        return map_score_to_crs(int(m.group(1)), int(m.group(2)))
    return None


def sanitize_for_zhipu(text):
    """委托共享模块。"""
    return lpr.sanitize_for_zhipu(text)



# 角色 / JSON / 系统提示 —— 统一自 llm_prompt_rules（2026-08-08 全面优化）
ROLE_PROMPTS = lpr.ROLE_PROMPTS
JSON_RULES_SUFFIX = lpr.JSON_RULES_EVIDENCE
EVIDENCE_SYSTEM_PROMPT = lpr.EVIDENCE_SYSTEM_PROMPT


def output_token_budget(model):
    """Reserve enough room for reasoning models to emit their final JSON."""
    return 4096 if fp.strip_provider(model) == "kimi-k2.6" else 1024


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
    for i in range(3):
        try:
            if model.startswith("zhipu/"):
                prompt = sanitize_for_zhipu(prompt)
            sys_prompt = lpr.system_prompt_evidence(model, models_used)
            resp = client.chat.completions.create(
                model=real_model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=output_token_budget(model),
            )
            content = resp.choices[0].message.content
            if content is None or not str(content).strip():
                err = _empty_response_diagnostic(resp)
            else:
                return model, parse_evidence_prediction(content, evidence_catalog)
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
        response = client.chat.completions.create(
            model=fp.strip_provider(EVIDENCE_AUDITOR_MODEL),
            messages=[{"role":"system","content":lpr.system_prompt_evidence_audit()},
                      {"role":"user","content":prompt}],
            temperature=0.0, max_tokens=768)
        return parse_evidence_audit(response.choices[0].message.content, evidence_catalog)
    except Exception as exc:
        return {"error":str(exc)[:160]}


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


def aggregate_directions(predictions):
    """单选1票/双选0.5; reasoning差与2-1坍缩降权; 强度<60%强制双选。"""
    valid = {md: p for md, p in predictions.items()
             if isinstance(p, dict) and "error" not in p and p.get("decision", "opinion") == "opinion"}
    if not valid:
        return {"error": "所有模型均调用失败",
                "errors": [p for p in predictions.values() if isinstance(p, dict) and "error" in p]}
    if len(valid) < 2:
        return {
            "error": "insufficient_model_responses",
            "valid_model_count": len(valid),
            "minimum_valid_models": MIN_VALID_EVIDENCE_MODELS,
            "errors": [p for p in predictions.values() if isinstance(p, dict) and "error" in p],
        }
    votes = Counter()
    score_prefs = Counter()
    ou_prefs = Counter()
    hafu_prefs = Counter()
    for md, p in valid.items():
        w = 1.0
        if p.get("reasoning_ok") is False:
            w *= 0.5
        if p.get("evidence_gap"):
            w *= 0.85
        if p.get("collapse_score"):
            w *= 0.5
        votes[p["direction"]] += w
        if p.get("alt_direction"):
            votes[p["alt_direction"]] += 0.5 * w
        if p.get("score_pref"):
            score_prefs[p["score_pref"]] += w * (0.5 if p.get("collapse_score") else 1.0)
        if p.get("ou25"):
            ou_prefs[p["ou25"]] += w
        if p.get("hafu"):
            hafu_prefs[p["hafu"]] += w
    top_dir, top_votes = votes.most_common(1)[0]
    total_votes = sum(votes.values())
    strength = top_votes / total_votes if total_votes else 0
    top_score = score_prefs.most_common(1)[0][0] if score_prefs else None
    top_ou = ou_prefs.most_common(1)[0][0] if ou_prefs else None
    top_hafu = hafu_prefs.most_common(1)[0][0] if hafu_prefs else None
    alt_dir, caution = lpr.force_dual_if_weak(strength, votes, 0.6)
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
        "top_score_pref": top_score, "score_prefs": dict(score_prefs),
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


def _stable_sha256(value):
    """Hash JSON data with a deterministic, Unicode-preserving encoding."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_audit_record(aggregation, models_used, prompt, evidence_status,
                       evidence_audit=None, consensus_gate=None):
    """Build the successful per-match JSON audit payload without calling an LLM."""
    if aggregation.get("error"):
        raise ValueError("cannot audit a failed aggregation")
    record = dict(aggregation)
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
        "evidence_collected_at_min": evidence_status["evidence_collected_at_min"],
        "evidence_collected_at_max": evidence_status["evidence_collected_at_max"],
        "evidence_audit": evidence_audit,
        "consensus_gate": consensus_gate,
    })
    return record


def build_skip_audit_record(predictions, models_used, prompt, evidence_status,
                            evidence_audit, consensus_gate, aggregation_error):
    """Preserve a complete audit trail when the two-voter gate skips a match."""
    return {
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
        "evidence_collected_at_min": evidence_status["evidence_collected_at_min"],
        "evidence_collected_at_max": evidence_status["evidence_collected_at_max"],
        "evidence_audit": evidence_audit,
        "consensus_gate": consensus_gate,
    }


def main():
    ap = argparse.ArgumentParser(description="LLM轨道: 证据驱动定性预测")
    ap.add_argument("--input", required=True, help="采集器输出的JSON文件")
    ap.add_argument("--evidence-dir", required=True, help="证据文件目录")
    ap.add_argument("--models", nargs="+", default=fp.DEFAULT_MODELS)
    ap.add_argument("--match-id", type=int, default=None)
    ap.add_argument("--max-matches", type=int, default=0)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    selected_matches = select_matches(data["matches"], args.match_id, args.max_matches)
    if not selected_matches:
        print("没有符合条件的比赛")
        return

    evidence_files = load_evidence(args.evidence_dir)
    print(f"📁 证据文件: {len(evidence_files)} 个")
    for n in sorted(evidence_files):
        print(f"   - {n}")

    voter_models = [model for model in args.models if model != EVIDENCE_AUDITOR_MODEL]
    print(f"🎯 共 {len(selected_matches)} 场比赛待预测, DeepSeek证据审计 + {len(voter_models)} 个独立投票模型\n")

    for i, (match_idx, m) in enumerate(selected_matches, 1):
        if i > 1:
            print("\n⏳ 场次冷却 5 秒...")
            time.sleep(5)
        idx = m.get("match_num", "")
        # 使用 raw 文件中的原始场次序号，避免 --match-id 过滤后重新编号而错配证据。
        ev_name = match_evidence_file(match_idx, evidence_files)
        if not ev_name:
            print(json.dumps({"match_index": i, "status": "evidence_insufficient", "reason": "missing_evidence_file"}, ensure_ascii=False))
            continue
        primary_evidence = evidence_files[ev_name]
        # kickoff_iso 带明确时区（体彩原始数据为 Asia/Shanghai），用于与
        # collected_at 的 ISO 时间戳比较；kickoff_local 仅是展示用回退字段。
        kickoff = m.get("kickoff_iso") or m.get("kickoff") or m.get("kickoff_local")
        evidence_status = assess_evidence(
            primary_evidence, kickoff=kickoff, now=datetime.now(timezone.utc)
        )
        if not evidence_status["ok"]:
            print(json.dumps({"match_index": i, "status": "evidence_insufficient", "reason": evidence_status["reason"]}, ensure_ascii=False))
            continue
        ev_text = primary_evidence
        mcp_name = match_mcp_file(match_idx, evidence_files)
        if mcp_name:
            mcp_status = assess_mcp_evidence(evidence_files[mcp_name], kickoff, match=m)
            if mcp_status["ok"]:
                ev_text += "\n\n" + evidence_files[mcp_name]
                print(f"   数据块: {mcp_name} (MCP 已拼入)")
            else:
                print(f"   ⚠️ MCP 数据块已拒绝: {mcp_status['reason']}")

        print("=" * 64)
        print(f"⚽ 第{i}/{len(selected_matches)}场 [{idx}] {m['home']} VS {m['away']} | {m.get('league', '')} | {m.get('kickoff_local', '')}")
        print(f"   证据: {ev_name}")
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

        agg = aggregate_directions(predictions)
        consensus_gate = two_voter_consensus(predictions, voter_models)
        if consensus_gate["status"] != "consensus":
            print(f"  🚫 最终门控: skip ({consensus_gate['reason']})")
        if evidence_status["evidence_gap"] and "error" not in agg:
            agg = enforce_evidence_gap(agg)
        if "error" in agg:
            print(f"  [失败] {agg['error']}")
            print(json.dumps(build_skip_audit_record(
                predictions, voter_models, voter_prompt, evidence_status,
                evidence_audit, consensus_gate, agg["error"],
            ), ensure_ascii=False))
            continue

        print(f"\n  📊 综合方向: {agg['direction']}  "
              f"({agg['votes']:.1f}/{agg['total_votes']:.1f}票, "
              f"强度{agg['strength']*100:.0f}%)")
        # 冷门/谨慎标记
        if is_two_legged(m.get("league", ""), ev_text or ""):
            print(f"  ⚠️ 两回合制/杯赛场次(冷门风险高)")
        if agg.get("caution"):
            alt_dir = agg.get("alt_direction") or "?"
            caution_reasons = []
            if agg["strength"] < AGGREGATION_RULE_SPEC["weak_strength_threshold"]:
                caution_reasons.append(f"强度<{AGGREGATION_RULE_SPEC['weak_strength_threshold'] * 100:.0f}%")
            if agg.get("evidence_gap"):
                caution_reasons.append("证据存在缺口")
            reason_text = "、".join(caution_reasons) or "聚合风控"
            print(f"  🚨 谨慎({reason_text}): 建议双选 {agg['direction']}/{alt_dir}")
        print(f"  🎯 比分偏好: {agg['top_score_pref'] or '分散'}")
        if agg.get("top_ou25"):
            print(f"  📦 大小球2.5: {agg['top_ou25']}")
        if agg.get("top_hafu"):
            print(f"  ⏱️ 半全场: {agg['top_hafu']}")
        if agg.get("collapse_flags"):
            print(f"  ⚠️ 坍缩标记: {', '.join(agg['collapse_flags'])}")
        print(f"  🗳️ 投票分布: " + " | ".join(
            f"{k}:{v:.1f}" for k, v in
            sorted(agg['all_votes'].items(), key=lambda x: -x[1])))
        print(f"  🤖 各模型判断:")
        for md, p in agg["individual"].items():
            if p["status"] == "failed":
                print(f"     [{md.split('/')[-1].split(':')[0][:20]:<20}] 失败 — {p['error'][:60]}")
                continue
            alt = f" (备选:{p['alt_direction']})" if p.get("alt_direction") else ""
            sp = f" 比分:{p['score_pref']}" if p.get("score_pref") else ""
            print(f"     [{md.split('/')[-1].split(':')[0][:20]:<20}] "
                  f"{p['direction']}{alt}{sp} — {p['reasoning'][:60]}")
        print(json.dumps(build_audit_record(
            agg, voter_models, voter_prompt, evidence_status,
            evidence_audit=evidence_audit, consensus_gate=consensus_gate,
        ), ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()

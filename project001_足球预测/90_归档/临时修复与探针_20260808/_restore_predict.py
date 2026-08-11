# -*- coding: utf-8 -*-
"""Restore predict.py from backup and apply LLM prompt optimizations cleanly."""
from __future__ import annotations

import ast
import re
from pathlib import Path

src = Path(__file__).resolve().parent / "_tmp_predict.py.txt"
dst = Path(r"C:/Users/Administrator/football-llm-predictor/predict.py")
text = src.read_text(encoding="utf-8")
ast.parse(text)

if "import llm_prompt_rules as lpr" not in text:
    text = text.replace(
        "import football_predictor as fp\n",
        "import football_predictor as fp\nimport llm_prompt_rules as lpr\n",
    )

# drop first long EVIDENCE_SYSTEM_PROMPT before load_evidence
text = re.sub(
    r"EVIDENCE_SYSTEM_PROMPT = \"\"\"[\s\S]*?\"\"\"\n\n\ndef load_evidence",
    "def load_evidence",
    text,
    count=1,
)

# ROLE / JSON / EVIDENCE block
text = re.sub(
    r"# 角色差异化:[\s\S]*?EVIDENCE_SYSTEM_PROMPT = \"\"\"[\s\S]*?\"\"\" \+ JSON_RULES_SUFFIX\n",
    (
        "# 角色 / JSON / 系统提示 —— 统一自 llm_prompt_rules（2026-08-08 全面优化）\n"
        "ROLE_PROMPTS = lpr.ROLE_PROMPTS\n"
        "JSON_RULES_SUFFIX = lpr.JSON_RULES_EVIDENCE\n"
        "EVIDENCE_SYSTEM_PROMPT = lpr.EVIDENCE_SYSTEM_PROMPT\n\n"
    ),
    text,
    count=1,
)

text = re.sub(
    r"def sanitize_for_zhipu\(text\):[\s\S]*?return t\n",
    (
        "def sanitize_for_zhipu(text):\n"
        '    """委托共享模块。"""\n'
        "    return lpr.sanitize_for_zhipu(text)\n\n"
    ),
    text,
    count=1,
)

text = re.sub(
    r"def normalize_score_pref\(raw\):[\s\S]*?return None\n",
    "def normalize_score_pref(raw):\n    return lpr.normalize_score_pref(raw)\n\n",
    text,
    count=1,
)

ps = text.find("def parse_evidence_prediction")
pe = text.find("\ndef map_score_to_crs")
if ps < 0 or pe < 0:
    raise SystemExit(f"parse markers {ps} {pe}")

new_parse = '''def parse_evidence_prediction(content):
    """解析模型输出 JSON（ou25/hafu/evidence_gap/reasoning 质检）。"""
    text = content.strip()
    text = re.sub(r"^```(json)?\\s*|\\s*```$", "", text)
    m = re.search(r"\\{.*\\}", text, re.S)
    if not m:
        return {"error": f"无JSON: {content[:80]}"}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"JSON解析失败: {e}"}
    direction = str(data.get("direction", "")).strip()
    if direction not in ("主胜", "平局", "客胜"):
        return {"error": f"非法direction: {direction}"}
    alt = str(data.get("alt_direction") or "").strip() or None
    if alt not in (None, "主胜", "平局", "客胜"):
        alt = None
    sp = normalize_score_pref(data.get("score_pref"))
    reasoning = str(data.get("reasoning", "")).strip()[:220]
    ou25 = lpr.normalize_ou25(data.get("ou25"))
    hafu = lpr.normalize_hafu(data.get("hafu"))
    egap = bool(data.get("evidence_gap", False))
    rq = lpr.reasoning_quality(reasoning)
    if not rq.get("ok"):
        egap = True
    collapse_score = bool(sp in lpr.COLLAPSE_SCORES and not rq.get("ok"))
    return {
        "direction": direction,
        "alt_direction": alt,
        "score_pref": sp,
        "ou25": ou25,
        "hafu": hafu,
        "evidence_gap": egap,
        "reasoning": reasoning,
        "reasoning_ok": bool(rq.get("ok")),
        "reasoning_flags": rq,
        "collapse_score": collapse_score,
    }

'''
text = text[:ps] + new_parse + text[pe + 1 :]

# build prompt single-line append (avoid multiline escape hell)
old_tail = 'lines.append("\\n请基于上述证据做定性判断(方向 + 比分偏好), 输出 JSON。")'
new_tail = (
    'lines.append("\\n请基于上述证据输出 JSON。硬性要求: 禁止无依据写2-1/1-2; '
    'ou25/hafu独立; reasoning必须含【伤停|近况|战意|主客|身份|交锋:事实】; '
    '缺口时evidence_gap=true并填alt_direction。")\n'
    '    if evidence_text and ("未检索到" in evidence_text or "证据缺口" in evidence_text or "未拿到" in evidence_text):\n'
    '        lines.append("⚠️ 证据文件含缺口标记: 不得编造伤停/首发, 须 evidence_gap=true。")'
)
if old_tail not in text:
    raise SystemExit("build tail not found")
text = text.replace(old_tail, new_tail)

text = text.replace(
    "def call_evidence_model(client, model, prompt):",
    "def call_evidence_model(client, model, prompt, models_used=None):",
)

# sys prompt block
pat = re.compile(
    r"            # 角色差异化:.*\n"
    r"            role_part = ROLE_PROMPTS\.get\(model\)\n"
    r"            if role_part:\n"
    r"                sys_prompt = role_part \+ .*?\n"
    r"            else:\n"
    r"                sys_prompt = EVIDENCE_SYSTEM_PROMPT\n",
    re.S,
)
text2, n = pat.subn(
    "            sys_prompt = lpr.system_prompt_evidence(model, models_used)\n",
    text,
    count=1,
)
if n != 1:
    # fallback exact
    if "role_part = ROLE_PROMPTS.get(model)" not in text2:
        raise SystemExit("role_part block missing")
text = text2

ps = text.find("def aggregate_directions")
pe = text.find("\ndef main")
if ps < 0 or pe < 0:
    raise SystemExit(f"agg markers {ps} {pe}")

new_agg = '''def aggregate_directions(predictions):
    """单选1票/双选0.5; reasoning差与2-1坍缩降权; 强度<60%强制双选。"""
    valid = {md: p for md, p in predictions.items()
             if isinstance(p, dict) and "error" not in p}
    if not valid:
        return {"error": "所有模型均调用失败",
                "errors": [p for p in predictions.values() if isinstance(p, dict) and "error" in p]}
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
    collapse = lpr.summarize_collapse(valid)
    return {
        "direction": top_dir, "votes": top_votes, "total_votes": total_votes,
        "strength": strength, "all_votes": dict(votes),
        "top_score_pref": top_score, "score_prefs": dict(score_prefs),
        "top_ou25": top_ou, "all_ou25": dict(ou_prefs),
        "top_hafu": top_hafu, "all_hafu": dict(hafu_prefs),
        "alt_direction": alt_dir, "caution": caution,
        "collapse_flags": collapse.get("flags") or [],
        "individual": valid,
    }


'''
text = text[:ps] + new_agg + text[pe + 1 :]

text = text.replace(
    "fp.get_client(fp.provider_for(md)), md, prompt): md",
    "fp.get_client(fp.provider_for(md)), md, prompt, args.models): md",
)

if "坍缩标记" not in text:
    needle = 'print(f"  🎯 比分偏好: {agg[\'top_score_pref\'] or \'分散\'}")'
    if needle not in text:
        # alternate quote style from file
        for line in text.splitlines():
            if "比分偏好" in line and "top_score_pref" in line and "print" in line:
                needle = line
                break
    text = text.replace(
        needle,
        needle
        + "\n        if agg.get(\"top_ou25\"):\n"
        + "            print(f\"  📦 大小球2.5: {agg['top_ou25']}\")\n"
        + "        if agg.get(\"top_hafu\"):\n"
        + "            print(f\"  ⏱️ 半全场: {agg['top_hafu']}\")\n"
        + "        if agg.get(\"collapse_flags\"):\n"
        + "            print(f\"  ⚠️ 坍缩标记: {', '.join(agg['collapse_flags'])}\")",
        1,
    )

dst.write_text(text, encoding="utf-8")
ast.parse(text)
print("OK", len(text))
for c in [
    "ROLE_PROMPTS = lpr.ROLE_PROMPTS",
    "system_prompt_evidence",
    "collapse_score",
    "force_dual_if_weak",
    "args.models): md",
    "evidence_gap=true",
    "坍缩标记",
]:
    print(c, c in text)
print("old persona", "敢于反市场" in text)
print("2-1 example", 'score_pref": "2-1"' in text)

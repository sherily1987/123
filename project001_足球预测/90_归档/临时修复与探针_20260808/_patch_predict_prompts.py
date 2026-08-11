# -*- coding: utf-8 -*-
"""Patch predict.py for LLM prompt optimization."""
from pathlib import Path
import re
import ast

p = Path(r"C:/Users/Administrator/football-llm-predictor/predict.py")
t = p.read_text(encoding="utf-8")

# --- ROLE/JSON/EVIDENCE block ---
m = re.search(
    r"ROLE_PROMPTS = \{[\s\S]*?\n\}\n\n# 公共 JSON[\s\S]*?EVIDENCE_SYSTEM_PROMPT = \"\"\"[\s\S]*?\"\"\" \+ JSON_RULES_SUFFIX",
    t,
)
if not m:
    m = re.search(
        r"# 角色差异化:[\s\S]*?EVIDENCE_SYSTEM_PROMPT = \"\"\"[\s\S]*?\"\"\" \+ JSON_RULES_SUFFIX",
        t,
    )
replacement = """# 角色 / JSON 规则 / 系统提示 —— 统一自 llm_prompt_rules（2026-08-08 全面优化）
import llm_prompt_rules as lpr

ROLE_PROMPTS = lpr.ROLE_PROMPTS
JSON_RULES_SUFFIX = lpr.JSON_RULES_EVIDENCE
EVIDENCE_SYSTEM_PROMPT = lpr.EVIDENCE_SYSTEM_PROMPT
"""
if m:
    t = t[: m.start()] + replacement + t[m.end() :]
    print("replaced role/json block")
else:
    print("WARN: role block not found")

# early duplicate prompt
m2 = re.search(
    r'EVIDENCE_SYSTEM_PROMPT = """你是一名专业的足球数据分析师。以下是基于真实来源搜索整理的本场比赛证据[\s\S]*?"""\n',
    t,
)
if m2 and "lpr.EVIDENCE" not in m2.group(0):
    t = t[: m2.start()] + "# 旧版顶置提示词已移除，统一用 lpr.EVIDENCE_SYSTEM_PROMPT\n" + t[m2.end() :]
    print("removed early duplicate prompt")

t = t.replace('score_pref": "2-1"', 'score_pref": "1-0"')
t = t.replace("score_pref\": \"2-1\"", "score_pref\": \"1-0\"")

# sanitize
old_san = re.search(r"def sanitize_for_zhipu\(text\):[\s\S]*?return t\n", t)
if old_san:
    t = (
        t[: old_san.start()]
        + "def sanitize_for_zhipu(text):\n"
        + '    """委托共享模块（智谱内容过滤）。"""\n'
        + "    return lpr.sanitize_for_zhipu(text)\n\n"
        + t[old_san.end() :]
    )
    print("sanitize delegated")

# normalize_score_pref
t2, n = re.subn(
    r"def normalize_score_pref\(raw\):[\s\S]*?return None\n",
    "def normalize_score_pref(raw):\n    return lpr.normalize_score_pref(raw)\n\n",
    t,
    count=1,
)
t = t2
print("normalize_score_pref", n)

# parse_evidence_prediction
new_parse = '''def parse_evidence_prediction(content):
    """解析模型输出的 JSON 定性判断（含 ou25/hafu/evidence_gap/reasoning 质检）。"""
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
    collapse_score = sp in getattr(lpr, "COLLAPSE_SCORES", {"2-1", "1-2"}) and not rq.get("ok")
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
t2, n = re.subn(
    r"def parse_evidence_prediction\(content\):[\s\S]*?return \{\"direction\": direction, \"alt_direction\": alt,\n            \"score_pref\": sp, \"reasoning\": reasoning\}\n",
    new_parse,
    t,
    count=1,
)
if n == 0:
    t2, n = re.subn(
        r"def parse_evidence_prediction\(content\):[\s\S]*?\"reasoning\": reasoning\}\n",
        new_parse,
        t,
        count=1,
    )
t = t2
print("parse_evidence", n)

# call_evidence_model
t = t.replace(
    "def call_evidence_model(client, model, prompt):",
    "def call_evidence_model(client, model, prompt, models_used=None):",
)
old_call_bit = """            role_part = ROLE_PROMPTS.get(model)
            if role_part:
                sys_prompt = role_part + \"\\n\\n\" + JSON_RULES_SUFFIX
            else:
                sys_prompt = EVIDENCE_SYSTEM_PROMPT"""
# try actual file content
if "role_part = ROLE_PROMPTS.get(model)" in t:
    t = re.sub(
        r"            role_part = ROLE_PROMPTS\.get\(model\)\n"
        r"            if role_part:\n"
        r"                sys_prompt = role_part \+ \"\\n\\n\" \+ JSON_RULES_SUFFIX\n"
        r"            else:\n"
        r"                sys_prompt = EVIDENCE_SYSTEM_PROMPT\n",
        "            sys_prompt = lpr.system_prompt_evidence(model, models_used)\n",
        t,
        count=1,
    )
    print("call_evidence sys_prompt ok")
else:
    print("WARN call_evidence role_part missing")

# build_evidence_prompt tail
old_tail = 'lines.append("\\n请基于上述证据做定性判断(方向 + 比分偏好), 输出 JSON。")'
new_tail = """lines.append(
        "\\n请基于上述证据输出 JSON。"
        "硬性要求: ①禁止无依据写2-1/1-2; ②ou25/hafu独立; "
        "③reasoning必须含【伤停|近况|战意|主客|身份|交锋:事实】;"
        "④关键证据缺失时 evidence_gap=true 并填 alt_direction。"
    )
    if evidence_text and ("未检索到" in evidence_text or "证据缺口" in evidence_text or "未拿到" in evidence_text):
        lines.append("⚠️ 证据文件含缺口标记: 不得编造伤停/首发, 须 evidence_gap=true。")"""
if old_tail in t:
    t = t.replace(old_tail, new_tail)
    print("build_evidence_prompt updated")
else:
    print("WARN build tail missing")

# aggregate_directions
new_agg = '''def aggregate_directions(predictions):
    """聚合方向投票: 单选计1票, 双选各计0.5票; reasoning差/坍缩降权; 强度<60%强制双选。"""
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
            sw = w * (0.5 if p.get("collapse_score") else 1.0)
            score_prefs[p["score_pref"]] += sw
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

    return {"direction": top_dir, "votes": top_votes, "total_votes": total_votes,
            "strength": strength, "all_votes": dict(votes),
            "top_score_pref": top_score, "score_prefs": dict(score_prefs),
            "top_ou25": top_ou, "all_ou25": dict(ou_prefs),
            "top_hafu": top_hafu, "all_hafu": dict(hafu_prefs),
            "alt_direction": alt_dir, "caution": caution,
            "collapse_flags": collapse.get("flags") or [],
            "individual": valid}

'''
t2, n = re.subn(
    r"def aggregate_directions\(predictions\):[\s\S]*?\"individual\": valid\}\n",
    new_agg,
    t,
    count=1,
)
t = t2
print("aggregate_directions", n)

# submit models_used
t = t.replace(
    "fp.get_client(fp.provider_for(md)), md, prompt): md",
    "fp.get_client(fp.provider_for(md)), md, prompt, args.models): md",
)

old_print = '        print(f"  🎯 比分偏好: {agg[\'top_score_pref\'] or \'分散\'}")'
# actual quotes
for line in t.splitlines():
    if "比分偏好" in line and "top_score_pref" in line:
        print("print line:", line)
        new_line = line + "\n" + (
            "        if agg.get(\"top_ou25\"):\n"
            "            print(f\"  📦 大小球2.5: {agg['top_ou25']}\")\n"
            "        if agg.get(\"top_hafu\"):\n"
            "            print(f\"  ⏱️ 半全场: {agg['top_hafu']}\")\n"
            "        if agg.get(\"collapse_flags\"):\n"
            "            print(f\"  ⚠️ 坍缩标记: {', '.join(agg['collapse_flags'])}\")"
        )
        t = t.replace(line, new_line, 1)
        break

if "import llm_prompt_rules as lpr" not in t:
    t = t.replace(
        "import football_predictor as fp\n",
        "import football_predictor as fp\nimport llm_prompt_rules as lpr\n",
    )
    print("added top import")

p.write_text(t, encoding="utf-8")
ast.parse(t)
print("predict.py OK", len(t))
for f in [
    r"C:/Users/Administrator/football-llm-predictor/football_predictor.py",
    r"C:/Users/Administrator/football-llm-predictor/llm_prompt_rules.py",
]:
    ast.parse(Path(f).read_text(encoding="utf-8"))
    print("OK", f)

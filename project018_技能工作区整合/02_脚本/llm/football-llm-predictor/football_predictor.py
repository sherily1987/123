#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多LLM足球比分预测系统 (多服务商免费模型聚合版)
================================================
每个模型独立预测 -> 投票聚合 -> 综合报告 + 分歧度分析

使用前提:
  1. 注册对应服务商获取 API key (智谱/千问/Groq/Kimi/Gemini/豆包)
  2. 设置环境变量:  export ZHIPU_API_KEY=xxx  (对应服务商的 env 名)
     (Windows PowerShell: $env:ZHIPU_API_KEY="xxx")

用法示例:
  python football_predictor.py "曼城" "利物浦" --league "英超"
  python football_predictor.py "皇马" "巴萨" --league "西甲" --round "第30轮"
  python football_predictor.py --dry-run "曼城" "利物浦"   # 演示聚合逻辑(不调API)
"""

import argparse
import json
import os
import re
import statistics
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============ 配置区 ============

# 多 provider 支持: 模型ID前缀 -> 服务商。无前缀默认 zhipu
PROVIDERS = {
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4",
              "env": "ZHIPU_API_KEY"},           # 智谱 GLM-4-Flash 完全免费
    "groq": {"base_url": "https://api.groq.com/openai/v1",
             "env": "GROQ_API_KEY"},             # 需代理(大陆IP 403)
    "moonshot": {"base_url": "https://api.moonshot.cn/v1",
              "env": "MOONSHOT_API_KEY"},     # Kimi K3 推理模型
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "env": "GOOGLE_API_KEY"},         # Google Gemini 3 (需代理)
    "ark": {"base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "env": "ARK_API_KEY"},               # 豆包/火山方舟 (需控制台开通模型)
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "env": "DASHSCOPE_API_KEY"},        # 千问 qwen-flash 完全免费 (阿里云百炼)
    "deepseek": {"base_url": "https://api.deepseek.com",
                 "env": "DEEPSEEK_API_KEY"},     # DeepSeek (国内直连, 极低价, 强推理)
}

# 模型级温度覆盖(推理模型只允许 temperature=1)
MODEL_TEMPERATURE_OVERRIDES = {
    "kimi-k3": 1.0,
    "doubao-seed-evolving": 1.0,
}

# 正式证据LLM模型池：国内直连三模型（2026-08-12 移除千问 qwen3.8-max：
# 用户裁定删除，DASHSCOPE key 401 失效且不再续用）。
# 海外/其他模型只能显式传参用于独立实验，不得因默认值混入生产投票或同一回测池。
DEFAULT_MODELS = [
    "zhipu/glm-4-flash",                    # 智谱 (完全免费, 无限量)
    "deepseek/deepseek-chat",               # DeepSeek V3 (国内直连, 强推理, 极低价)
    "moonshot/kimi-k3",                     # Kimi K3 (推理模型, temperature=1)
]

TIMEOUT = 90          # 单模型调用超时(秒)
TEMPERATURE = 0.8     # 温度: 让各模型略有差异, 避免全部雷同

# 共享提示词/反坍缩规则（2026-08-08 全面优化）
try:
    import llm_prompt_rules as lpr
except ImportError:  # pragma: no cover
    lpr = None

# 兼容旧引用: 默认四玩法规则（示例比分已改为 1-0，禁 2-1 锚定）
SYSTEM_PROMPT = (
    lpr.JSON_RULES_FOUR_MARKET if lpr is not None else
    """你是专业足球分析师。只输出 JSON:
{"home_score":1,"away_score":0,"result":"主胜","total_goals":"1","half_result":"平局","ou25":"小","hafu":"平胜","alt_direction":null,"evidence_gap":false,"confidence":0.55,"reasoning":"【近况:…】"}
禁止无依据写2-1; ou25/hafu须独立判断; reasoning必须含【类别:事实】。"""
)


def hhad_result(home_score, away_score, goal_line):
    """竞彩让球胜平负结果判定。

    goal_line 带符号: 负数=主队让球, 正数=主队受让。
    让球后主队得分 = 实际主队得分 + goal_line, 再与客队比较。
    返回: 让胜/让平/让负 或 受让胜/受让平/受让负 或 胜/平/负(线为0)。
    """
    adj_home = home_score + goal_line
    if goal_line < 0:
        return ("让胜" if adj_home > away_score
                else "让平" if adj_home == away_score else "让负")
    if goal_line > 0:
        return ("受让胜" if adj_home > away_score
                else "受让平" if adj_home == away_score else "受让负")
    return ("主胜" if adj_home > away_score
            else "平局" if adj_home == away_score else "客胜")


def hhad_analysis(match, score):
    """让球玩法分析: 模型综合比分 -> 让球结果, 并与官方让球赔率对照。

    match: 采集数据中的比赛dict(含 model_hhad)。
    score: (home_score, away_score) 综合预测比分。
    返回 dict 或 None(无让球数据)。
    """
    hh = match.get("model_hhad") or {}
    line = hh.get("line", 0)
    odds = hh.get("odds")
    if not odds or len(odds) < 3:
        return None
    result = hhad_result(score[0], score[1], line)
    dirs = ["主胜", "平局", "客胜"]
    official_dir = dirs[odds.index(min(odds))]  # 官方最低赔方向
    result_dir = {"让胜": "主胜", "让平": "平局", "让负": "客胜",
                  "受让胜": "主胜", "受让平": "平局", "受让负": "客胜",
                  "主胜": "主胜", "平局": "平局", "客胜": "客胜"}[result]
    return {"line": line, "result": result, "official_odds": odds,
            "official_dir": official_dir, "agree": result_dir == official_dir}


def provider_for(model):
    """模型ID前缀 -> provider名(无前缀默认 zhipu)。"""
    for prefix in ("zhipu/", "groq/", "moonshot/", "gemini/", "ark/", "qwen/", "deepseek/", "openrouter/"):
        if model.startswith(prefix):
            return prefix.rstrip("/")
    return "zhipu"


def strip_provider(model):
    """去掉 provider 前缀, 返回服务商真正识别的模型ID。"""
    for prefix in ("zhipu/", "groq/", "moonshot/", "gemini/", "ark/", "qwen/", "deepseek/", "openrouter/"):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def standardize_individual_predictions(predictions, models_used):
    """Return serializable per-model records; failed calls are never votes."""
    individual = {}
    for model in models_used:
        prediction = predictions.get(model)
        base = {"model_id": model, "provider": provider_for(model)}
        if not isinstance(prediction, dict) or "error" in prediction:
            error = prediction.get("error", "missing_prediction") if isinstance(prediction, dict) else "missing_prediction"
            base.update({"status": "failed", "error": str(error)})
        else:
            base.update(prediction)
            base["status"] = "success"
        individual[model] = base
    return individual


_clients = {}


def load_windows_user_env(name):
    """Return a persistent Windows user environment variable without exposing it.

    A long-running Hermes terminal backend may predate a Windows environment
    variable update.  This fallback hydrates only the current Python process;
    it never writes the registry, a .env file, or stdout.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value).strip()
    except (FileNotFoundError, OSError):
        return ""


def get_client(provider="zhipu"):
    """按 provider 获取(缓存的) OpenAI client。"""
    if provider in _clients:
        return _clients[provider]
    cfg = PROVIDERS.get(provider)
    if not cfg:
        print(f"[!] 未知 provider: {provider}")
        sys.exit(1)
    from openai import OpenAI
    env_name = cfg["env"]
    key = os.environ.get(env_name, "").strip()
    if not key:
        key = load_windows_user_env(env_name)
        if key:
            os.environ[env_name] = key
    if not key:
        print(f"[!] 未检测到 {env_name} 环境变量")
        print("    请先注册对应服务并设置环境变量, 例如:")
        print(f"    setx {env_name} \"你的key\"   (Windows持久化)")
        sys.exit(1)
    _clients[provider] = OpenAI(base_url=cfg["base_url"], api_key=key,
                                timeout=TIMEOUT)
    return _clients[provider]


def build_user_prompt(home, away, league, extra):
    lines = [f"比赛信息：{home} VS {away}"]
    if league:
        lines.append(f"联赛/赛事：{league}")
    if extra:
        lines.append(extra)
    lines.append(
        "请输出四玩法 JSON。"
        "注意: ①禁止无依据默认2-1; ②ou25/hafu独立判断; "
        "③reasoning必须含【伤停|近况|战意|主客|身份|交锋:事实】;"
        "④证据不足时 evidence_gap=true 并考虑 alt_direction。"
    )
    return "\n".join(lines)


def ttg_from_score(hs, as_):
    """比分 -> 总进球档位(0-6, 7+)。"""
    total = hs + as_
    return "7+" if total >= 7 else str(total)


def hafu_result(half_result, full_result):
    """半全场九宫格推导: 半场结果 x 全场结果 -> 组合名。"""
    combos = {
        ("主胜", "主胜"): "胜胜", ("主胜", "平局"): "胜平", ("主胜", "客胜"): "胜负",
        ("平局", "主胜"): "平胜", ("平局", "平局"): "平平", ("平局", "客胜"): "平负",
        ("客胜", "主胜"): "负胜", ("客胜", "平局"): "负平", ("客胜", "客胜"): "负负",
    }
    return combos.get((half_result, full_result))


def hafu_analysis(match, half_result, full_result):
    """半全场分析: 模型(半场结果,全场结果) -> 九宫格, 对照官方HAFU最低赔。
    match: 采集比赛dict(含 hafu dict: hh/hd/ha/dh/dd/da/ah/ad/aa)。
    返回 dict 或 None。"""
    hafu = match.get("hafu") or {}
    if not hafu or not isinstance(hafu, dict):
        return None
    combo = hafu_result(half_result, full_result)
    if not combo:
        return None
    # 官方字段名映射
    field_map = {"胜胜": "hh", "胜平": "hd", "胜负": "ha", "平胜": "dh",
                 "平平": "dd", "平负": "da", "负胜": "ah", "负平": "ad",
                 "负负": "aa"}
    field = field_map[combo]
    official_odds = hafu.get(field)
    if official_odds is None:
        return None
    # 官方最低赔组合(市场最看好) -> 反查组合名
    try:
        best_field = min((k for k in hafu if hafu[k] not in (None, "")),
                         key=lambda k: float(hafu[k]))
    except (ValueError, TypeError):
        return {"combo": combo, "official_odds": official_odds,
                "official_best": None, "agree": None}
    rev_map = {v: k for k, v in field_map.items()}
    best_combo = rev_map.get(best_field, best_field)
    return {"combo": combo, "official_odds": official_odds,
            "official_best": best_combo, "agree": best_field == field}


def parse_prediction(text: str):
    """容错解析模型输出中的 JSON（含 ou25/hafu/alt/evidence_gap）。"""
    text = text.strip()
    # 去掉可能的 markdown 代码块围栏
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"未找到JSON: {text[:200]}")
    data = json.loads(m.group(0))
    hs = int(data.get("home_score", -1))
    as_ = int(data.get("away_score", -1))
    conf = float(data.get("confidence", 0.5))
    result = str(data.get("result", "")).strip()
    reasoning = str(data.get("reasoning", "")).strip()
    if not (0 <= hs <= 7 and 0 <= as_ <= 7):
        raise ValueError(f"比分越界: {hs}-{as_}")
    # 校验 result 与比分一致性, 不一致时以比分为准
    if hs > as_:
        result = "主胜"
    elif hs < as_:
        result = "客胜"
    else:
        result = "平局"
    conf = max(0.0, min(1.0, conf))
    # 总进球: 优先用模型值, 但必须与比分之和一致(不一致以比分为准)
    tg = str(data.get("total_goals", "")).strip()
    tg_calc = ttg_from_score(hs, as_)
    if tg not in ("0", "1", "2", "3", "4", "5", "6", "7+") or tg != tg_calc:
        tg = tg_calc
    # 半场结果: 模型值, 非法则留空(该模型半全场作废)
    hr = str(data.get("half_result", "")).strip()
    if hr not in ("主胜", "平局", "客胜"):
        hr = ""

    # 独立 OU / HAFU
    ou25 = None
    hafu = None
    if lpr is not None:
        ou25 = lpr.normalize_ou25(data.get("ou25"))
        hafu = lpr.normalize_hafu(data.get("hafu"))
        rq = lpr.reasoning_quality(reasoning)
    else:
        rq = {"ok": "【" in reasoning, "invalid_reason": None}

    # 若未给 hafu 但有 half_result，可推导（降级）
    if not hafu and hr:
        hafu = hafu_result(hr, result)

    # 若未给 ou25，不从比分强制大球——仅作弱默认且标记
    ou_from_score = False
    if not ou25:
        n = hs + as_
        ou25 = "大2.5" if n >= 3 else "小2.5"
        ou_from_score = True

    alt = str(data.get("alt_direction") or "").strip() or None
    if alt not in (None, "主胜", "平局", "客胜"):
        alt = None
    egap = bool(data.get("evidence_gap", False))
    if not rq.get("ok"):
        conf = min(conf, 0.45)
        egap = True

    # 2-1 无优质 reasoning → 降置信
    score_s = f"{hs}-{as_}"
    if score_s in ("2-1", "1-2") and not rq.get("ok"):
        conf = min(conf, 0.4)

    return {
        "home_score": hs, "away_score": as_, "result": result,
        "total_goals": tg, "half_result": hr,
        "ou25": ou25, "hafu": hafu,
        "ou_from_score": ou_from_score,
        "alt_direction": alt, "evidence_gap": egap,
        "confidence": conf, "reasoning": reasoning,
        "reasoning_ok": bool(rq.get("ok")),
        "reasoning_flags": rq,
    }


def call_model(client, model, prompt, models_used=None):
    """调用单个模型, 返回 (model, prediction)。失败返回 (model, {"error": ...})。
    空响应/格式错误重试1次(等3s); 429限流重试2次(等10s/25s退避)。
    使用角色化 system prompt（若 llm_prompt_rules 可用）。"""
    err = "未知错误"
    attempts = [1, 2, 3]
    real_model = strip_provider(model)
    temperature = MODEL_TEMPERATURE_OVERRIDES.get(real_model, TEMPERATURE)
    if lpr is not None:
        sys_prompt = lpr.system_prompt_four_market(model, models_used)
    else:
        sys_prompt = SYSTEM_PROMPT
    # 智谱过滤
    use_prompt = prompt
    if model.startswith("zhipu/") or real_model.startswith("glm"):
        if lpr is not None:
            use_prompt = lpr.sanitize_for_zhipu(prompt)
        else:
            use_prompt = re.sub(r"盘口|水位|博彩", "数据", prompt)
    for i, attempt in enumerate(attempts):
        try:
            resp = client.chat.completions.create(
                model=real_model,  # 去掉 provider 前缀
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": use_prompt},
                ],
                temperature=temperature,
            )
            content = resp.choices[0].message.content
            if content is None or not str(content).strip():
                err = "模型返回空内容(None)"
            else:
                return model, parse_prediction(content)
        except Exception as e:
            err = str(e)[:120]
            if "429" in err or "Rate limit" in err or "rate limit" in err:
                time.sleep(10 + i * 15)  # 429: 10s, 25s 退避
            else:
                time.sleep(3)  # 其他错误: 短等
                break  # 非限流错误不重复尝试
    return model, {"error": err}


def aggregate(predictions, models_used):
    """聚合投票: 比分/赛果/总进球/半全场/OU众数 + 反坍缩 + 分歧双选。"""
    scores = [p for p in predictions.values() if isinstance(p, dict) and "error" not in p]
    errors = [p for p in predictions.values() if isinstance(p, dict) and "error" in p]

    if not scores:
        return {"error": "所有模型均调用失败", "errors": errors,
                "models_used": models_used}

    # 无效 reasoning 降权: 复制一份带权重的计数
    score_counter = Counter()
    result_counter = Counter()
    tg_counter = Counter()
    hr_counter = Counter()
    hafu_counter = Counter()
    ou_counter = Counter()
    confs = []
    individuals = {m: p for m, p in predictions.items()
                   if isinstance(p, dict) and "error" not in p}

    for p in scores:
        w = 1.0
        if p.get("reasoning_ok") is False:
            w = 0.5
        if p.get("evidence_gap"):
            w *= 0.85
        sc = (p["home_score"], p["away_score"])
        score_counter[sc] += w
        result_counter[p["result"]] += w
        if p.get("total_goals"):
            tg_counter[p["total_goals"]] += w
        if p.get("half_result"):
            hr_counter[p["half_result"]] += w
        # HAFU: 优先显式字段
        hf = p.get("hafu") or (hafu_result(p["half_result"], p["result"]) if p.get("half_result") else None)
        if hf:
            hafu_counter[hf] += w
        ou = p.get("ou25")
        if ou:
            # 从比分反推的 OU 降权
            ou_counter[ou] += (0.4 * w) if p.get("ou_from_score") else w
        confs.append(p["confidence"])

    # 2-1 坍缩再罚
    if lpr is not None:
        # convert to str keys helper via apply on tuple keys
        tmp = Counter()
        for k, v in score_counter.items():
            tmp[k] = v
        # if collapse and weak reasoning majority
        collapse_n = score_counter.get((2, 1), 0) + score_counter.get((1, 2), 0)
        if collapse_n >= 0.5 * sum(score_counter.values()):
            bad = sum(1 for p in scores if f"{p['home_score']}-{p['away_score']}" in ("2-1", "1-2") and not p.get("reasoning_ok", True))
            if bad >= max(1, len(scores) // 2):
                score_counter[(2, 1)] = score_counter.get((2, 1), 0) * 0.5
                score_counter[(1, 2)] = score_counter.get((1, 2), 0) * 0.5

    top_score, top_score_votes = score_counter.most_common(1)[0]
    top_result, top_result_votes = result_counter.most_common(1)[0]
    avg_conf = statistics.mean(confs)
    # 分歧度: 不同比分数量 / 有效模型数
    disagreement = len([k for k, v in score_counter.items() if v > 0]) / max(1, len(scores))

    top_tg = tg_counter.most_common(1)[0][0] if tg_counter else ""
    top_hafu = hafu_counter.most_common(1)[0][0] if hafu_counter else ""
    top_ou = ou_counter.most_common(1)[0][0] if ou_counter else ""

    total_rv = sum(result_counter.values()) or 1
    strength = top_result_votes / total_rv
    alt_dir, caution = (None, False)
    if lpr is not None:
        alt_dir, caution = lpr.force_dual_if_weak(strength, result_counter, 0.6)
    elif strength < 0.6 and len(result_counter) > 1:
        alt_dir = result_counter.most_common(2)[1][0]
        caution = True

    collapse = lpr.summarize_collapse(individuals) if lpr is not None else {"flags": []}

    # 序列化友好的 score keys
    all_scores = {f"{a}-{b}": v for (a, b), v in score_counter.items()}

    return {
        "top_score": top_score,
        "top_score_votes": top_score_votes,
        "top_result": top_result,
        "top_result_votes": top_result_votes,
        "top_total_goals": top_tg,
        "top_hafu": top_hafu,
        "top_ou25": top_ou,
        "alt_direction": alt_dir,
        "caution": caution,
        "strength": strength,
        "avg_confidence": avg_conf,
        "disagreement": disagreement,
        "all_scores": all_scores,
        "all_results": dict(result_counter),
        "all_total_goals": dict(tg_counter),
        "all_hafu": dict(hafu_counter),
        "all_ou25": dict(ou_counter),
        "collapse_flags": collapse.get("flags") or [],
        "individual": standardize_individual_predictions(predictions, models_used),
        "errors": errors,
        "models_used": models_used,
        "valid_count": len(scores),
    }


def print_report(home, away, agg):
    print("\n" + "=" * 62)
    print(f"  ⚽ 多LLM足球预测报告: {home} VS {away}")
    print("=" * 62)
    if "error" in agg:
        print(f"[失败] {agg['error']}")
        for e in agg.get("errors", []):
            print(f"  - {e}")
        return

    print(f"\n  📊 综合预测比分:  {home} {agg['top_score'][0]} - {agg['top_score'][1]} {away}"
          f"   (得票 {agg['top_score_votes']}/{agg['valid_count']})")
    print(f"  🏆 综合赛果:      {agg['top_result']}   (得票 {agg['top_result_votes']}/{agg['valid_count']})")
    if agg.get("alt_direction") or agg.get("caution"):
        print(f"  🚨 双选/谨慎:     {agg['top_result']}"
              f"{('/' + str(agg['alt_direction'])) if agg.get('alt_direction') else ''}"
              f"  强度{float(agg.get('strength') or 0)*100:.0f}%")
    if agg.get("top_ou25"):
        print(f"  📦 大小球2.5:     {agg['top_ou25']}")
    if agg.get("top_hafu"):
        print(f"  ⏱️ 半全场:        {agg['top_hafu']}")
    if agg.get("collapse_flags"):
        print(f"  ⚠️ 坍缩标记:      {', '.join(agg['collapse_flags'])}")
    print(f"  🎯 平均置信度:    {agg['avg_confidence']*100:.0f}%")
    dis = agg["disagreement"]
    if dis <= 0.35:
        print(f"  🤝 模型分歧度:    {dis:.0%}  (低 — 模型意见较一致)")
    elif dis <= 0.6:
        print(f"  ⚖️ 模型分歧度:    {dis:.0%}  (中 — 存在不同看法)")
    else:
        print(f"  ⚠️ 模型分歧度:    {dis:.0%}  (高 — 意见分散, 谨慎参考)")

    print("\n  📈 比分投票分布:")
    for score, cnt in sorted(agg["all_scores"].items(), key=lambda x: -x[1]):
        hs, as_ = score.split("-", 1)
        stars = "★" * max(1, round(cnt))
        print(f"     {hs}-{as_}: {stars} ({cnt:g}票)")
    print("  📊 赛果投票分布:  " +
          " | ".join(f"{k}: {v}票" for k, v in agg["all_results"].items()))

    print("\n  🤖 各模型独立预测:")
    for m, p in agg["individual"].items():
        if p["status"] == "failed":
            print(f"     [{m.split('/')[-1].split(':')[0]:<16}] 失败 — {p['error'][:60]}")
            continue
        print(f"     [{m.split('/')[-1].split(':')[0]:<16}] "
              f"{p['home_score']}-{p['away_score']} "
              f"({p['result']}, 置信 {p['confidence']*100:.0f}%) "
              f"— {p['reasoning'][:45]}")
    if agg["errors"]:
        print(f"\n  ⚠️ {len(agg['errors'])} 个模型调用失败:")
        for e in agg["errors"]:
            print(f"     - {e}")


def main():
    ap = argparse.ArgumentParser(description="多LLM足球比分预测")
    ap.add_argument("home", help="主队名称")
    ap.add_argument("away", help="客队名称")
    ap.add_argument("--league", default="", help="联赛/赛事")
    ap.add_argument("--extra", default="", help="附加信息(近期状态/积分等)")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                    help="使用的模型列表(默认: 内置免费模型)")
    ap.add_argument("--dry-run", action="store_true",
                    help="不调用API, 用模拟数据演示聚合逻辑")
    args = ap.parse_args()

    print(f"⚽ 比赛: {args.home} VS {args.away}"
          + (f" | {args.league}" if args.league else "")
          + f"\n🤖 参与模型 ({len(args.models)}):")
    for m in args.models:
        print(f"     - {m}")

    prompt = build_user_prompt(args.home, args.away, args.league, args.extra)

    if args.dry_run:
        import random
        random.seed(42)
        predictions = {}
        for m in args.models:
            hs = random.randint(0, 3)
            as_ = random.randint(0, 2)
            predictions[m] = {
                "home_score": hs, "away_score": as_,
                "result": ("主胜" if hs > as_ else "客胜" if hs < as_ else "平局"),
                "confidence": round(random.uniform(0.45, 0.7), 2),
                "reasoning": "模拟数据(dry-run模式)",
            }
        print("\n[dry-run] 使用模拟响应演示聚合逻辑...")
    else:
        predictions = {}
        lock = threading.Lock()
        print(f"\n⏳ 正在并行调用 {len(args.models)} 个模型...")
        with ThreadPoolExecutor(max_workers=min(7, len(args.models))) as ex:
            futs = {ex.submit(call_model, get_client(provider_for(m)), m, prompt, args.models): m
                    for m in args.models}
            for fut in as_completed(futs):
                m, p = fut.result()
                with lock:
                    predictions[m] = p
                if "error" in p:
                    print(f"     ✗ [{m}] 失败: {p['error'][:60]}")
                else:
                    print(f"     ✓ [{m}] -> {p['home_score']}-{p['away_score']} {p['result']}")

    agg = aggregate(predictions, args.models)
    print_report(args.home, args.away, agg)


if __name__ == "__main__":
    main()

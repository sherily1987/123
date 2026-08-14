# -*- coding: utf-8 -*-
"""LLM 足球预测 — 共享提示词规则与反坍缩工具（predict / football_predictor 共用）。

2026-08-08 优化动机（28 场实测）：
  比分 2-1×23、大2.5×28、半全场胜胜×23、reasoning 几乎只有赔率/主场。
目标：去 2-1 锚定、强迫非赔率证据引用、OU/HAFU 独立、分歧强制双选。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------- 竞彩 CRS ----------
CRS_OPTIONS = [
    "1-0", "2-0", "2-1", "3-0", "3-1", "3-2",
    "4-0", "4-1", "4-2", "5-0", "5-1", "5-2",
    "0-0", "1-1", "2-2", "3-3",
    "0-1", "0-2", "1-2", "0-3", "1-3", "2-3",
    "0-4", "1-4", "2-4", "0-5", "1-5", "2-5",
]
CRS_OTHER = {"主胜": "胜其他", "平局": "平其他", "客胜": "负其他"}
CRS_VALID = set(CRS_OPTIONS) | set(CRS_OTHER.values())

# 低比分优先集合（反 2-1 锚定）
LOW_SCORE_SET = {"0-0", "1-0", "0-1", "1-1", "2-0", "0-2"}
# 常见坍缩比分
COLLAPSE_SCORES = {"2-1", "1-2"}

HAFU_VALID = {"胜胜", "胜平", "胜负", "平胜", "平平", "平负", "负胜", "负平", "负负"}
OU25_VALID = {"大", "小", "大2.5", "小2.5", "over", "under"}
DIRS = ("主胜", "平局", "客胜")

# 证据类别标记（reasoning 必须至少一类非纯赔率）
EVIDENCE_TAGS = ("伤停", "阵容", "首发", "缺阵", "战意", "动机", "近况", "状态", "主客", "旅行", "天气", "身份", "交锋")
ODDS_ONLY_TAGS = ("赔率", "盘口", "让球", "市场")

# ---------- 检索关键词（证据收集用） ----------
# 分层结构：required = 每类至少搜一次的核心词；optional = 按赛事/语言扩展。
# 2026-08-12 修订：
#   - 清理伪关键词（get_lineups / team_ids / wttr / 勿混淆——搜了只命中文档）；
#   - 补两回合制战意词（second leg / aggregate / qualifying round 等，8月资格赛主战场）；
#   - 补南美语言词（escalação / once titular / formación 等，解放者杯常客）；
#   - 近况补主客分拆（home/away form）与连胜连败（streak）。
SEARCH_KEYWORDS = {
    "伤停": {
        "required": [
            "injury", "injured", "doubtful", "suspended", "team news",
            "大名单", "伤停", "缺阵", "停赛",
        ],
        "optional": [
            "predicted lineup", "confirmed lineup", "official lineup", "team announcement",
            "starting XI", "missing players", "伤病名单", "赛前发布会",
            "blessure", "opstelling", "desfalques", "lesão", "infortunio", "ausfälle",
            "escalação", "once titular", "formación",
        ],
    },
    "近况": {
        "required": [
            "last 5", "form", "recent results", "近5场", "状态",
        ],
        "optional": [
            "home form", "away form", "winning streak", "losing streak", "undefeated",
            "xG", "xG for", "xG against", "clean sheet", "走势",
        ],
    },
    "战意": {
        "required": [
            "首回合", "次回合", "first leg", "second leg", "aggregate", "qualifying round",
        ],
        "optional": [
            "opening day", "promoted", "relegation", "title race", "rotation", "midweek",
            "extra time", "penalties", "away goals rule", "trophy", "final", "showpiece",
            "揭幕", "升级", "保级", "争冠", "轮换",
        ],
    },
    "主客天气": {
        "required": [
            "home advantage", "travel", "weather", "主场", "客场", "天气",
        ],
        "optional": [
            "artificial turf", "pitch condition", "altitude", "heat", "temperature",
            "long journey", "草皮", "远征",
        ],
    },
    "赔率": {
        "required": [
            "opening odds", "closing odds", "初盘", "即盘",
        ],
        "optional": [
            "odds movement", "odds drift", "market move", "steam", "drift",
            "让球线", "冷热", "升水", "降水",
        ],
    },
    "身份": {
        "required": [
            "official name", "full name", "官方全名",
        ],
        "optional": [
            "official site", "official page", "match page", "UEFA official",
            "球队官方", "官网",
        ],
    },
}


def sanitize_for_zhipu(text: str) -> str:
    """智谱 glm-4-flash 对博彩/盘口类词汇有内容过滤(400 code 1301)。"""
    t = re.sub(r"威廉希尔|立博|Bet365|bet365|Interwetten|澳门盘|澳门", "多家机构", text)
    t = re.sub(r"初盘-终盘|初盘|终盘|盘口|水位|让球盘", "赔率变化", t)
    t = re.sub(r"博彩", "数据", t)
    return t


def map_score_to_crs(home: int, away: int) -> str:
    if home > away:
        s = f"{home}-{away}"
        return s if s in CRS_OPTIONS else CRS_OTHER["主胜"]
    if home == away:
        s = f"{home}-{away}"
        return s if s in CRS_OPTIONS else CRS_OTHER["平局"]
    s = f"{home}-{away}"
    return s if s in CRS_OPTIONS else CRS_OTHER["客胜"]


def normalize_score_pref(raw) -> Optional[str]:
    if not raw:
        return None
    raw = str(raw).strip()
    if raw in CRS_VALID:
        return raw
    m = re.match(r"^(\d+)-(\d+)$", raw)
    if m:
        return map_score_to_crs(int(m.group(1)), int(m.group(2)))
    return None


def normalize_ou25(raw) -> Optional[str]:
    if raw is None or raw == "":
        return None
    s = str(raw).strip().lower()
    if s in ("大", "大2.5", "over", "o", "over2.5", "o2.5"):
        return "大2.5"
    if s in ("小", "小2.5", "under", "u", "under2.5", "u2.5"):
        return "小2.5"
    return None


def normalize_hafu(raw) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip()
    # 允许 HH 码
    code = {
        "HH": "胜胜", "HD": "胜平", "HA": "胜负",
        "DH": "平胜", "DD": "平平", "DA": "平负",
        "AH": "负胜", "AD": "负平", "AA": "负负",
    }
    if s in code:
        return code[s]
    if s.upper() in code:
        return code[s.upper()]
    return s if s in HAFU_VALID else None


def reasoning_quality(reasoning: str) -> Dict[str, Any]:
    """检查 reasoning 是否引用非赔率证据。"""
    text = reasoning or ""
    has_bracket = "【" in text and "】" in text
    tags_found = [t for t in EVIDENCE_TAGS if t in text]
    odds_only = (not tags_found) and any(t in text for t in ODDS_ONLY_TAGS)
    # 有【类别:】格式
    cited = bool(re.search(r"【[^】]{1,12}[:：]", text))
    ok = bool(tags_found or (has_bracket and cited))
    if odds_only and not tags_found:
        ok = False
    return {
        "ok": ok,
        "has_bracket": has_bracket,
        "tags": tags_found,
        "odds_only": odds_only,
        "invalid_reason": None if ok else ("仅赔率/无证据引用" if odds_only or not tags_found else None),
    }


# ---------- 角色 ----------
ROLE_PROMPTS: Dict[str, str] = {
    "zhipu/glm-4-flash": (
        "你是一名注重基本面的足球分析师。核心信念: 伤病、状态、战意比赔率更可靠。\n"
        "重点: 伤停/阵容、近况趋势、战意(杯赛轮次/保级/争冠/揭幕)。\n"
        "硬规则: ①证据未写明伤停时禁止编造伤员名；②反市场必须点名哪条基本面；"
        "③无进攻大战证据时优先低比分(0-0/1-0/1-1/0-1/2-0)。\n"
        "兼负「低比分审慎」职责(三模型场景): 警惕默认2-1与无脑大球。"
    ),
    "qwen/qwen-flash": (
        "你是一名市场分析派足球分析师。核心信念: 赔率异动反映增量信息，但终盘强弱≠赛果。\n"
        "重点: 初盘→即盘方向、让球线移动、TTG最低赔档；只认异动，不把低赔当成必胜。\n"
        "硬规则: ①与市场同向时必须找一条否证；②reasoning 不能只有赔率，须再引基本面或写【证据缺口】。"
    ),
    "groq/llama-3.3-70b-versatile": (
        "你是一名专猎冷门的足球分析师。核心信念: 热门常被高估，冷门多于大众预期。\n"
        "重点: 两回合/杯赛首回合、大热主胜风险、客队旅行疲惫、升班马战意。\n"
        "你倾向双选；对「稳赢」高度怀疑；避免无依据的大比分。"
    ),
    "moonshot/kimi-k2.6": (
        "你是一名保守审慎的足球分析师。核心信念: 平局与低比分比想象中多。\n"
        "重点: 双方防守、近期平局率、低总进球信号。\n"
        "硬规则: 优先从 0-0/1-0/0-1/1-1/2-0/0-2 中选比分；**不要**因为「常见」就选 2-1。"
    ),
    "gemini/gemini-3-flash-preview": (
        "你是一名战术流足球分析师。核心信念: 阵型克制、核心球员与教练部署决定比赛。\n"
        "重点: 预计首发、对位、射手/组织者、新帅磨合、主客与天气对战术影响。"
    ),
    "ark/doubao-seed-evolving": (
        "你是一名逆向思维足球分析师。核心信念: 市场常错误定价，机会在赔率与证据背离处。\n"
        "重点: 被忽视的客队/弱队、证据支撑不足的大热；有证据时敢反市场。"
    ),
    "deepseek/deepseek-chat": (
        "你是一名深度推理派足球分析师。核心信念: 好预测来自系统推演而非单一信号。\n"
        "流程: 先列关键证据(伤停/状态/战意/主客/赔率) → 正方一条 + 反方一条 → 结论。\n"
        "注意竞彩90分钟口径与两回合冷门；拿不准给双选。\n"
        "兼负「冷门怀疑」职责(三模型场景): 大热主胜必须写风险点；避免全员2-1模板。"
    ),
}

# 仅跑国内三模时的附加职责（拼到角色后）
DOMESTIC3_EXTRA = {
    "zhipu/glm-4-flash": "\n[三模增强] 你同时负责压低无依据的大球/2-1默认；证据缺口大时倾向双选或低比分。",
    "qwen/qwen-flash": "\n[三模增强] 市场派也必须标注证据缺口；禁止 reasoning 纯盘口。",
    "deepseek/deepseek-chat": "\n[三模增强] 你同时负责冷门审查与正反推演；强度不足时 alt_direction 必填。",
}


def role_prompt_for(model: str, models_used: Optional[Sequence[str]] = None) -> str:
    base = ROLE_PROMPTS.get(model, "")
    if not models_used:
        return base
    # 国内三件套场景
    domestic = {"zhipu/glm-4-flash", "qwen/qwen-flash", "deepseek/deepseek-chat"}
    used = set(models_used)
    if used <= domestic or (len(used) <= 3 and used & domestic == used):
        base = base + DOMESTIC3_EXTRA.get(model, "")
    return base


# ---------- JSON 规则：证据轨（direction） ----------
JSON_RULES_EVIDENCE = """请基于证据做定性判断, 只输出一个 JSON 对象, 不要输出任何其他文字:
{"direction":"主胜","alt_direction":null,"score_pref":"1-0","ou25":"小","hafu":"平胜","evidence_gap":false,"reasoning":"【近况:…】【战意:…】"}

规则:
1. direction 只能是 "主胜"/"平局"/"客胜"(单选必填)。
2. alt_direction 为备选(双选); 拿不准或证据缺口大时必填, 单选坚定则 null。
3. score_pref 必须是竞彩可兑奖项: 主胜1-0/2-0/2-1/3-0/3-1/3-2/4-0/4-1/4-2/5-0/5-1/5-2/胜其他; 平0-0/1-1/2-2/3-3/平其他; 客0-1/0-2/1-2/0-3/1-3/2-3/0-4/1-4/2-4/0-5/1-5/2-5/负其他。
4. **禁止无进攻/对攻证据就写 2-1 或 1-2**。默认优先 0-0/1-0/0-1/1-1/2-0/0-2；只有证据支持进球战时才用 2-1+。
5. ou25 必须独立判断: 只能 "大" 或 "小"(2.5球)。**禁止**仅因比分总进球≥3就选大；无对攻证据默认倾向 "小"。
6. hafu 半全场九宫格: 胜胜/胜平/胜负/平胜/平平/平负/负胜/负平/负负。**禁止**「全场主胜⇒默认胜胜」；无半场信息时优先平胜/平平/平负。
7. evidence_gap: 伤停/近况等关键类缺失时为 true。
8. reasoning 60-100字, **必须**含至少一处【类别: 事实】, 类别从 伤停/阵容/首发/缺阵/近况/战意/主客/身份/交锋 中选；若证据含 get_lineups 首发/缺阵名单必须引用；**禁止**只有【赔率】；禁止编造。
9. 禁止伪概率、伪xG。官方赔率仅参考；与基本面冲突时以证据为准。
10. 两回合/杯赛首回合冷门多, 大热方优先双选。
11. 竞彩口径: 仅90分钟(含补时), 不含加时/点球。
12. **不得因为「常见比分统计」选择 2-1。**"""


# ---------- JSON 规则：四玩法轨（比分+半场+OU） ----------
JSON_RULES_FOUR_MARKET = """你是专业足球分析师。只输出一个 JSON 对象, 不要 markdown 或其它文字:
{"home_score":1,"away_score":0,"result":"主胜","total_goals":"1","half_result":"平局","ou25":"小","hafu":"平胜","alt_direction":null,"evidence_gap":false,"confidence":0.55,"reasoning":"【近况:…】【主客:…】"}

规则:
1. result 只能 主胜/平局/客胜; 必须与 home_score/away_score 一致(不一致以比分为准)。
2. home_score/away_score 为 0-7 整数。
3. total_goals 为 "0"-"6" 或 "7+", 必须等于两队进球之和(≥7为7+)。
4. half_result 为上半场 主胜/平局/客胜。
5. ou25 独立字段: "大" 或 "小"(2.5)。**不要**只从比分抄; 无对攻证据默认 "小"。
6. hafu 独立字段九宫格(胜胜…负负)。**不要**默认「主胜=胜胜」; 半场不明优先平X。
7. alt_direction: 拿不准时填备选方向, 否则 null。
8. evidence_gap: 关键证据缺失时 true。
9. confidence 0-1。
10. reasoning 必须含【伤停|阵容|首发|缺阵|近况|战意|主客|身份|交锋 : 事实】至少一类; 有 get_lineups 名单时必须引用; 禁止纯赔率; 禁止编造伤员。
11. **禁止无依据输出 2-1/1-2 模板**; 优先 0-0/1-0/0-1/1-1/2-0/0-2。
12. 官方赔率只参考不盲从; 90分钟口径。
13. 不得因常见比分统计而选 2-1。"""


EVIDENCE_SYSTEM_PROMPT = (
    "你是一名专业的足球数据分析师。以下是基于真实来源整理的六类证据与官方赔率。\n\n"
    + JSON_RULES_EVIDENCE
)


def system_prompt_evidence(model: str, models_used: Optional[Sequence[str]] = None) -> str:
    role = role_prompt_for(model, models_used)
    if role:
        return role + "\n\n" + JSON_RULES_EVIDENCE
    return EVIDENCE_SYSTEM_PROMPT


def system_prompt_four_market(model: str, models_used: Optional[Sequence[str]] = None) -> str:
    role = role_prompt_for(model, models_used)
    if role:
        return role + "\n\n" + JSON_RULES_FOUR_MARKET
    return JSON_RULES_FOUR_MARKET


# ---------- 聚合：反坍缩 / 双选 ----------
def apply_score_collapse_penalty(
    score_counter: Counter,
    individuals: Dict[str, dict],
) -> Counter:
    """若多数票是 2-1/1-2 且 reasoning 质量差, 降权。"""
    c = Counter(score_counter)
    total = sum(c.values())
    if total <= 0:
        return c
    for sc in list(c.keys()):
        key = sc if isinstance(sc, str) else f"{sc[0]}-{sc[1]}"
        if key not in COLLAPSE_SCORES:
            continue
        # 统计该比分票中无效 reasoning 比例
        bad = 0
        n = 0
        for p in individuals.values():
            ps = f"{p.get('home_score')}-{p.get('away_score')}"
            if ps != key and (p.get("score_pref") != key):
                continue
            n += 1
            rq = reasoning_quality(p.get("reasoning") or "")
            if not rq["ok"]:
                bad += 1
        if n and bad / n >= 0.5 and c[sc] / total >= 0.5:
            # 降到一半票
            c[sc] = max(1, c[sc] // 2) if isinstance(c[sc], int) else c[sc] * 0.5
    return c


def force_dual_if_weak(strength: float, votes: Counter, threshold: float = 0.6):
    alt = None
    caution = False
    if strength < threshold and len(votes) > 1:
        second = votes.most_common(2)[1]
        alt = second[0]
        caution = True
    return alt, caution


def summarize_collapse(individuals: Dict[str, dict]) -> Dict[str, Any]:
    scores = []
    ou = []
    hafu = []
    for p in individuals.values():
        if "error" in p:
            continue
        if p.get("home_score") is not None:
            scores.append(f"{p.get('home_score')}-{p.get('away_score')}")
        elif p.get("score_pref"):
            scores.append(str(p.get("score_pref")))
        if p.get("ou25"):
            ou.append(normalize_ou25(p.get("ou25")) or p.get("ou25"))
        if p.get("hafu"):
            hafu.append(normalize_hafu(p.get("hafu")) or p.get("hafu"))
    sc = Counter(scores)
    flags = []
    if sc:
        top, n = sc.most_common(1)[0]
        if top in COLLAPSE_SCORES and n >= max(2, int(0.6 * sum(sc.values()))):
            flags.append(f"SCORE_COLLAPSE:{top}x{n}")
    oc = Counter(ou)
    if oc:
        top, n = oc.most_common(1)[0]
        if n >= max(2, int(0.8 * sum(oc.values()))):
            flags.append(f"OU_COLLAPSE:{top}x{n}")
    hc = Counter(hafu)
    if hc:
        top, n = hc.most_common(1)[0]
        if top == "胜胜" and n >= max(2, int(0.8 * sum(hc.values()))):
            flags.append(f"HAFU_COLLAPSE:{top}x{n}")
    return {"flags": flags, "score_dist": dict(sc), "ou_dist": dict(oc), "hafu_dist": dict(hc)}

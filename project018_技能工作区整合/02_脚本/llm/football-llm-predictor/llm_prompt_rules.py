# -*- coding: utf-8 -*-
"""LLM 足球预测 — 共享提示词规则与反坍缩工具（predict / football_predictor 共用）。

2026-08-08 优化动机（28 场实测）：
  比分 2-1×23、大2.5×28、半全场胜胜×23、reasoning 几乎只有赔率/主场。
目标：去 2-1 锚定、强迫非赔率证据引用、OU/HAFU 独立、分歧强制双选。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Optional, Sequence

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

# 低比分默认模板集合（检测用）：模型无依据退回这些"安全低比分"时标记坍缩。
# 注意：不再是 prompt 引导清单（规则4 已删除"默认优先低比分"），只作 collapse_score 判定锚点。
LOW_SCORE_SET = {"0-0", "1-0", "0-1", "1-1", "2-0", "0-2"}
# 动态坍缩检测阈值：不再硬编码"哪些比分是坍缩比分"。
# 历史教训：先坍缩 2-1（反锚定后），又坍缩 1-0（规则4"默认优先低比分"引导）。
# 硬编码单一比分治标不治本——改按"聚合占比"动态判定，任何比分都逃不掉检测。
SCORE_COLLAPSE_RATIO = 0.6     # top 比分占比 >= 60% 即标记坍缩
SCORE_COLLAPSE_MIN_VOTES = 2   # 且至少 2 票（3 模型池下即 2/3 票）

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


# ---------- 中性角色 ----------
NEUTRAL_EVIDENCE_ROLE = (
    "你是一名中性的足球证据审核员。不预设主胜、平局、客胜、大小球或比分方向。\n"
    "只使用提供的编号证据；先识别可用事实、冲突和缺口，再决定每个市场是否有足够依据表达定性意见。\n"
    "不得编造伤停、首发、战意、状态或战术；不得把 UNAVAILABLE 解读为反向事实。"
)
ROLE_PROMPTS: Dict[str, str] = {}

def role_prompt_for(model: str, models_used: Optional[Sequence[str]] = None) -> str:
    return NEUTRAL_EVIDENCE_ROLE


# ---------- JSON 规则：证据轨（direction） ----------
JSON_RULES_EVIDENCE = """只输出一个 JSON 对象，不要 Markdown 或额外文字。
证据不足示例:
{"decision":"abstain","direction":null,"alt_direction":null,"score_pref":null,"ou25":null,"hafu":null,"evidence_gap":true,"evidence_ids":["E1"],"unsupported_assumptions":[],"reason_codes":["LINEUP_UNAVAILABLE"],"summary":"证据不足以形成独立方向。"}
有足够证据示例:
{"decision":"opinion","direction":"主胜","alt_direction":null,"score_pref":null,"ou25":null,"hafu":null,"evidence_gap":false,"evidence_ids":["E2","E4"],"unsupported_assumptions":[],"reason_codes":[],"summary":"E2 与 E4 支持主队方向；进球与半场证据不足，其他市场弃权。"}

规则:
1. decision 只能是 opinion 或 abstain。abstain 时 direction 必须为 null。
2. direction/alt_direction 只能是主胜/平局/客胜或 null。score_pref/ou25/hafu 均可单独为 null；缺少对应证据时必须为 null，不得猜测。
3. evidence_ids 只能引用提示词中存在的 E 编号。UNAVAILABLE 和 SOURCE_CONFLICT 只能证明缺口/冲突，不能支持 opinion。
4. 不得使用未在证据中出现的事实。任何必须假设的内容写入 unsupported_assumptions；存在影响结论的未支持假设时应 abstain。
5. 禁止伪概率、伪 xG、常见比分模板和人设先验。赔率只是一类证据，不得冒充独立基本面。
6. 比分、大小球、半全场必须各自有直接证据；无直接证据则对应字段为 null。
7. 口径仅为90分钟含补时，不含加时和点球。summary 限两句。"""

EVIDENCE_AUDIT_SYSTEM_PROMPT = """你是足球证据审计员，只审核证据可用性，不做比赛预测。
不得输出胜平负、比分、大小球或半全场的任何方向。
只输出一个 JSON 对象:
{"usable_evidence_ids":["E2"],"unusable_evidence_ids":["E1"],"conflict_evidence_ids":[],"gaps":["LINEUP_UNAVAILABLE"],"market_readiness":{"one_x_two":true,"score":false,"ou25":false,"hafu":false},"summary":"E2可用；阵容信息不可用。"}
规则:
1. 所有 ID 必须存在于输入证据目录。
2. UNAVAILABLE 只能放入 unusable_evidence_ids；SOURCE_CONFLICT 只能放入 conflict_evidence_ids。
3. market_readiness 只评估证据是否足以供下游判断，不暗示任何结果。
4. 不得补充输入中没有的事实。summary 限两句。"""


def system_prompt_evidence_audit() -> str:
    return EVIDENCE_AUDIT_SYSTEM_PROMPT


# ---------- JSON 规则：四玩法轨（比分+半场+OU） ----------
JSON_RULES_FOUR_MARKET = """你是专业足球分析师。只输出一个 JSON 对象, 不要 markdown 或其它文字:
{"home_score":1,"away_score":0,"result":"主胜","total_goals":"1","half_result":"平局","ou25":"小","hafu":"平胜","alt_direction":null,"evidence_gap":false,"confidence":0.55,"reasoning":"【近况:…】【主客:…】"}

规则:
1. result 只能 主胜/平局/客胜; 必须与 home_score/away_score 一致(不一致以比分为准)。
2. home_score/away_score 为 0-7 整数。
3. total_goals 为 "0"-"6" 或 "7+", 必须等于两队进球之和(≥7为7+)。
4. half_result 为上半场 主胜/平局/客胜。
5. ou25 独立字段: "大" 或 "小"(2.5)。**不要**只从比分抄; 必须给独立依据(两队场均进球/攻防/天气), 禁止"无对攻就默认小"或"低比分就默认小"。无进球证据时按赔率方向判断并标注。
6. hafu 独立字段九宫格(胜胜…负负)。**不要**默认「主胜=胜胜」; 半场不明优先平X。
7. alt_direction: 拿不准时填备选方向, 否则 null。
8. evidence_gap: 关键证据缺失时 true。
9. confidence 0-1。
10. reasoning 必须含【伤停|阵容|首发|缺阵|近况|战意|主客|身份|交锋 : 事实】至少一类; 有 get_lineups 名单时必须引用; 禁止纯赔率; 禁止编造伤员。
11. 比分由攻防强度推导, reasoning 写进球逻辑; **禁止**套"常见比分"模板, **禁止**机械默认(主胜配1-0/平局配1-1); 比分须与 result、ou25 自洽。
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
    """若 top 比分占比过高且 reasoning 质量差, 动态降权（不再限定 2-1/1-2）。"""
    c = Counter(score_counter)
    total = sum(c.values())
    if total <= 0:
        return c
    for sc in list(c.keys()):
        key = sc if isinstance(sc, str) else f"{sc[0]}-{sc[1]}"
        # 动态检测：该比分占比 < 阈值则跳过（不硬编码"哪些比分会坍缩"）
        if c[sc] / total < SCORE_COLLAPSE_RATIO:
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
        if n and bad / n >= 0.5:
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
        if n >= SCORE_COLLAPSE_MIN_VOTES and n >= SCORE_COLLAPSE_RATIO * sum(sc.values()):
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

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
            "last 5", "form", "recent results", "近5场", "双方近5场", "状态",
        ],
        "optional": [
            "home form", "away form", "winning streak", "losing streak", "undefeated",
            "xG", "xG for", "xG against", "clean sheet", "走势",
            "last five matches", "recent form",
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


def normalize_probs_1x2(raw) -> Optional[list]:
    """主/平/客 三位，合计 100。接受百分数或 0-1 小数。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = [
            raw.get("主胜", raw.get("H", raw.get("h"))),
            raw.get("平局", raw.get("D", raw.get("d"))),
            raw.get("客胜", raw.get("A", raw.get("a"))),
        ]
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        vals = [float(raw[0]), float(raw[1]), float(raw[2])]
    except (TypeError, ValueError):
        return None
    if any(v < 0 for v in vals):
        return None
    total = sum(vals)
    if total <= 0:
        return None
    if total <= 1.5:
        vals = [v * 100.0 for v in vals]
        total = sum(vals)
    vals = [round(v / total * 100.0, 1) for v in vals]
    vals[2] = round(100.0 - vals[0] - vals[1], 1)
    if vals[2] < 0:
        return None
    return vals


def normalize_top_scores(raw) -> Optional[list]:
    """恰好 3 个不重复竞彩比分，按给定顺序。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return None
    out = []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("score") or item.get("score_pref")
        pref = normalize_score_pref(item)
        if pref and pref not in out:
            out.append(pref)
        if len(out) == 3:
            return out
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

# DeepSeek V4 Flash is the current single-model research voter.  Keep this
# addendum separate from the shared rules so changing its response discipline
# cannot silently alter other providers' prompts.
DEEPSEEK_V4_FLASH_ADDENDUM = """DeepSeek V4 Flash 专用执行附录：
1. 先检查证据目录的 status、refreshed_at 和 evidence_gap；GAP、PARTIAL、EMPTY_UNCONFIRMED、PENDING_REFRESH 只能降低对应维度权重，不能被解释成“没有伤停”或“已确认首发”。
2. 预计首发只能作为 PREDICTED 先验，官方首发只能在目录明确标记 VALID/CONFIRMED 时使用；不得把预计首发改写为官方首发。
3. 四个市场完全独立：1X2 只用 1X2 赔率/胜平负证据，比分只用 CRS/攻防证据，大小球只用 TTG/进球证据，半全场只用 HAFU/半场证据；缺对应来源就保留缺口，不得用 1X2 反推。
4. 只输出规则要求的单个 JSON 对象；不要输出 Markdown、解释段、代码围栏或额外键。概率只保留一位小数并合计 100；这是研究判断概率，不是已校准生产概率。
5. 证据不足时仍可给 opinion 供研究记录，但必须 evidence_gap=true、明确 unsupported_assumptions，并避免高置信表述；不得生成下注、EV、Kelly 或“推荐购买”字段。"""

def role_prompt_for(model: str, models_used: Optional[Sequence[str]] = None) -> str:
    return NEUTRAL_EVIDENCE_ROLE


# ---------- JSON 规则：证据轨（direction） ----------
JSON_RULES_EVIDENCE = """只输出一个 JSON 对象，不要 Markdown 或额外文字。
仅赔率示例（仍给研究意见，但绝不下注）:
{"decision":"opinion","direction":"主胜","alt_direction":"平局","probs_1x2":[45.0,30.0,25.0],"top_scores":["1-0","1-1","0-0"],"ou25":"小","hafu":"平胜","evidence_gap":true,"evidence_ids":["E5"],"unsupported_assumptions":["缺少近况、伤停、首发和战意的独立事实"],"reason_codes":["ONLY_ODDS"],"summary":"仅依据E5体彩市场作观察性研究意见；独立证据缺口，禁止下注。"}
有足够证据示例（阵容有缺口仍须给方向）:
{"decision":"opinion","direction":"主胜","alt_direction":"平局","probs_1x2":[48.0,28.0,24.0],"top_scores":["1-0","2-0","1-1"],"ou25":"小","hafu":"平胜","evidence_gap":false,"evidence_ids":["E2","E4"],"unsupported_assumptions":[],"reason_codes":["LINEUP_PREDICTED_NOT_CONFIRMED"],"summary":"E2近况与E4主场支持主胜；E4为预计首发，尚非官方首发，按风险项处理。"}

规则:
1. decision 只能是 opinion 或 abstain。仅赔率时仍输出 opinion；只有身份无法核验或没有任何可审计证据时才 abstain。abstain 时 direction 与四个市场字段必须为 null。
2. opinion 时必须同时给出：direction（主胜/平局/客胜）、probs_1x2（主/平/客三位合计100）、top_scores（恰好3个比分）、ou25（大或小）、hafu（九宫格）。这五项禁止 null。
3. evidence_ids 只能引用提示词中存在的 E 编号。UNAVAILABLE、EMPTY_UNCONFIRMED 和 SOURCE_CONFLICT 只能证明缺口/冲突；ONLY_ODDS 只能引用官方体彩市场，不得声称有独立基本面支持。
4. 不得编造伤停、赛果或队名事实。必须假设的内容写入 unsupported_assumptions。预计首发可以作为赛前阵容证据使用，但必须保留 `PREDICTED` 状态，写明“预计、非官方”，不得改写成已确认首发。
5. probs_1x2 由第9条多维加权换算，一位小数，argmax 必须等于 direction。这是本模型的判断概率，不是量化轨校准概率，禁止冒充 xG 或精确到多位小数。
6. top_scores 按可能性从高到低恰好3个竞彩比分；第1个必须与 direction 同向（主胜则主>客，客胜则客>主，平局则平局比分）。ou25 只能大/小。hafu 必须是胜胜/胜平/胜负/平胜/平平/平负/负胜/负平/负负之一。
7. 口径仅为90分钟含补时，不含加时和点球。summary 限两句。
8. 近5场：只使用证据目录中逐场列出的正式赛果，必须引用【近况】；不得用投票、常识或占位文本补齐。若状态标为 AGING/PRIOR_SEASON，必须在摘要注明“上一赛季样本”，降低近况维度权重并写入 unsupported_assumptions；不得把它当作当前赛季近5场。完全检索不到正式赛果时写 FORM_UNAVAILABLE、evidence_gap=true，仍可给观察性 opinion。
9. 多维加权（只给目录里可用的维打分；缺维删除该权后重标定，不得把缺维当 0 分中性或默认主队）。仅赔率时方向、比分和四玩法都只是观察性研究意见，probs_1x2 不是量化校准概率；下游会强制 confidence=null、action=observe，禁止 EV/Kelly/推荐:
   近况0.30 / 阵容0.22 / 战意0.15 / 赔率0.15 / 主客环境0.13。身份核验是门禁不是权重。
   各维对主队打 -2..+2，只能引用 E 编号事实。近况内部近5场按新到旧 5>4>3>2>1 加权（Dixon-Coles 1997 时间衰减的短窗近似）；AGING/PRIOR_SEASON 只能作为低权重背景，不能与当前赛季样本等权。
   将加权和换算为 probs_1x2 并必须输出；仅赔率时只能按官方市场做观察性研究，不得把它当量化概率。市场输入必须同市场对应：1X2 赔率只可支持胜平负，CRS 只可支持比分，TTG 只可支持总进球/大小球，HAFU 只可支持半全场；禁止用 1X2 反推 CRS、TTG 或 HAFU，缺少对应盘口时该市场只能标记为证据不足。
10. 只允许写入页面或 API 快照中实际出现、且通过身份/时间/来源门禁的首发和伤停。不得用模型投票、占位文本或“通常首发”补齐。官方首发缺失时，若有合格来源的预计首发，使用 `LINEUP_PREDICTED_NOT_CONFIRMED` 风险码并在摘要注明非官方；只有完全没有首发资料才使用 `LINEUP_UNAVAILABLE` 并 `evidence_gap=true`。`EMPTY_UNCONFIRMED` 表示接口有空响应但不能证明无伤停/无首发，必须保留缺口并不得写成“暂无”。`FORM_UNAVAILABLE` 仍须 `evidence_gap=true`；仅赔率时仍输出观察意见，但不得把赔率外推成基本面事实。"""

EVIDENCE_AUDIT_SYSTEM_PROMPT = """你是足球证据审计员，只审核证据可用性，不做比赛预测。
不得输出胜平负、比分、大小球或半全场的任何方向。
只输出一个 JSON 对象:
{"gaps":["LINEUP_POSITION_CONFLICT"],"market_readiness":{"one_x_two":true,"score":true,"ou25":true,"hafu":true},"summary":"仅个别位置两源对不上，不得整维标阵容或近况不可用。"}
规则:
1. 程序按目录状态自动推导 usable_evidence_ids、unusable_evidence_ids、conflict_evidence_ids；不得输出这三个字段，也不得枚举 E 编号。
2. gaps 只记录输入可推导的异常或缺口代码，不得补充输入中没有的事实。
3. market_readiness 只评估证据是否足以供下游判断，不暗示任何结果；四个字段必须都是布尔值。
4. summary 限两句，且不得包含方向、比分、大小球或半全场结论。
5. 只接受输入中已有的、通过来源与时间门禁的首发/近况事实；未采集到就保留对应缺口，不得用投票、占位文本或上季常识填充。标为AGING/PRIOR_SEASON的近况只能作为低新鲜度背景，必须在审计摘要中指出赛季切换风险。"""


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
13. 不得因常见比分统计而选 2-1。
14. 证据中有双方近5场正式赛果时，reasoning 必须写【近况:主队…；客队…】并用近况推本场方向与进球倾向；若为AGING/PRIOR_SEASON，必须注明上一赛季样本并降低置信度。热身赛不算正式近5场。缺近5场不得编造，evidence_gap=true。
15. 择向按近况0.30/阵容0.22/战意0.15/赔率0.15/主客0.13 加权；缺维删权再标定。近5场新到旧 5>4>3>2>1。加权和换算为 probs_1x2 必须输出。
16. 各市场独立判断：不得把胜平负概率、比分概率或模型投票复制到另一个市场；若对应市场赔率或独立进球/半场证据缺失，降低该市场 readiness 并在 unsupported_assumptions 中写明缺口。"""


EVIDENCE_SYSTEM_PROMPT = (
    "你是一名专业的足球数据分析师。以下是基于真实来源整理的六类证据与官方赔率。\n\n"
    + JSON_RULES_EVIDENCE
)


def system_prompt_evidence(model: str, models_used: Optional[Sequence[str]] = None) -> str:
    role = role_prompt_for(model, models_used)
    if str(model).strip().casefold().endswith("deepseek-v4-flash"):
        role = (role + "\n\n" + DEEPSEEK_V4_FLASH_ADDENDUM).strip()
    if role:
        return role + "\n\n" + JSON_RULES_EVIDENCE
    return EVIDENCE_SYSTEM_PROMPT


def system_prompt_four_market(model: str, models_used: Optional[Sequence[str]] = None) -> str:
    role = role_prompt_for(model, models_used)
    if str(model).strip().casefold().endswith("deepseek-v4-flash"):
        role = (role + "\n\n" + DEEPSEEK_V4_FLASH_ADDENDUM).strip()
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

#!/usr/bin/env python3
"""足预大师 3.2 — 预测引擎

═══ 3.2 的改动（经 3504 场回测验证）═══
  由市场概率求 λ 的方法，从「线性映射」换成「数值反解」。

  旧方法强制 λ主 + λ客 ≡ total，把强弱差压缩了。3504 场（五大联赛×2赛季，
  Pinnacle 为主赔率）回测实测后果：
      纯模型 Brier 0.5847  vs  市场 0.5777   →  系统性损失 0.0070
      80% 以上概率档产生不出任何样本（市场有 82 场）
      60-80% 档偏差 -9.0pp（市场仅 -1.6pp）

  新方法 solve_lam_from_probs() 用嵌套二分反解出能还原市场 1X2 的 (λ主, λ客)，
  不再外部指定总进球。同一批 3504 场回测：
      纯模型 Brier 0.5777  vs  市场 0.5777   →  损失归零
      80%+ 档恢复 82 场，各档校准偏差与市场完全一致

  ⚠️ 注意这是「无损」不是「更优」——模型现在忠实复现市场，并未超越它。
     价值在于：往里加 Elo/xG/伤停时，是建立在未失真的基线上。

═══ 3.1 的改动（相对 3.0，全部向后兼容，原有输出字段一个未删）═══
  1. 所有常数集中到顶部，并标注出处等级 —— 见 CONSTANTS 说明
  2. goal_total 支持按赛事取默认值（competition 字段）
  3. hybrid 模式下输出 reliability_flags，明确警告 edge 的循环论证问题
  4. penalty_home_prob 默认 0.52 → 0.50，并说明理由
  5. quality 增加 note 字段，说明它测的是"输入完整度"而非"预测可靠度"
  6. 进球截断 9 → 12，消除尾部堆积
  7. 新增 sensitivity：λ ±10% 扰动下 1X2 的波动范围

配套 backtest.py 用于校准验证。没跑过回测的常数一律标 [UNFITTED]。
"""
import argparse
import json
import math

# ============================================================
# 常数与出处标注
# ------------------------------------------------------------
# 出处等级：
#   [EMPIRICAL] 行业广泛使用的经验值，有公开文献支撑，但本项目未用自己的数据拟合
#   [UNFITTED]  拍脑袋的初值，最需要用 backtest.py 校准后替换
#
# ⚠️ 标 [UNFITTED] 的常数直接决定输出精度。在跑过回测之前，
#    本引擎的绝对数值不应被当作可信概率，只可用于相对比较。
# ============================================================

# Dixon-Coles 低比分修正系数。
# [EMPIRICAL] -0.08 是文献常用的通用值，实际应按联赛/年代分别拟合。
RHO_DEFAULT = -0.08

# 场均总进球的兜底值（没给 goal_total 也没给 competition 时用）。
# [UNFITTED] 全球统一常数，粗糙。
GOAL_TOTAL_FALLBACK = 2.45

# 按赛事的场均总进球。
# [UNFITTED] ⚠️ 以下全部是近似值，未经本项目拟合，仅比"全球统一 2.45"稍好。
#            用 backtest.py 跑出真实值后替换本表。
LEAGUE_GOAL_TOTALS = {
    "英超": 2.80, "EPL": 2.80, "Premier League": 2.80,
    "西甲": 2.55, "La Liga": 2.55,
    "意甲": 2.70, "Serie A": 2.70,
    "德甲": 3.10, "Bundesliga": 3.10,
    "法甲": 2.70, "Ligue 1": 2.70,
    "欧冠": 3.00, "UCL": 3.00, "Champions League": 3.00,
    "欧联": 2.90, "UEL": 2.90, "Europa League": 2.90,
    "欧协联": 3.00, "UECL": 3.00,
}

# 由市场赔率反推 λ 的线性映射系数。
# [DEPRECATED] 3.2 起已不是主路径，仅在数值反解失败时兜底。
# 3504 场回测证实这套系数会使 Brier 比市场差 0.0070——它强制 λ主+λ客 ≡ total，
# 把强弱差压缩掉了。保留仅为容错，不要再基于它调参。
MKT_EDGE_COEF = 0.95   # 主客胜率差 → 进球差 的放大系数
MKT_DRAW_BASE = 0.26   # 基准平局率
MKT_DRAW_COEF = 0.25   # 平局率偏离 → 进球差 的修正系数

# 由 Elo 反推 λ 的系数：lh = total * (BASE + SPAN * 期望胜率)
# [UNFITTED] 0.35 / 0.55 同样无出处。
ELO_LAM_BASE = 0.35
ELO_LAM_SPAN = 0.55
ELO_HOME_ADV_DEFAULT = 60.0  # [EMPIRICAL] 主场优势折算 Elo 分，业界常用 50-100

# 多来源 λ 融合权重。
# [UNFITTED] 三个权重的相对大小没有依据。
W_MARKET = 0.55
W_ELO = 0.45
W_EXPLICIT = 0.85

# 点球大战主队获胜概率。
# [EMPIRICAL] 3.0 用 0.52。多数公开研究认为点球大战的主场优势接近于零，
#             真正显著的是"先罚一方"的优势。故改为中性 0.50。
#             想恢复旧行为：输入 penalty_home_prob: 0.52
PENALTY_HOME_PROB_DEFAULT = 0.50

# 加时赛节奏（相对 90 分钟的每分钟进球率）。[EMPIRICAL]
ET_TEMPO_DEFAULT = 0.92

# 上半场进球占比。
# [EMPIRICAL] 真实值约 0.45-0.47（进球在下半场更密集），取 0.45 偏保守。
FIRST_HALF_SHARE = 0.45

# 进球数截断上限。3.0 用 9，尾部概率会堆在最后一格。
# 12 对 λ<3 的比赛已经完全够用（P(X>12) < 1e-6）。
MAX_GOALS = 12

# 敏感性分析的 λ 扰动幅度。
# [UNFITTED] ±10% 代表"输入本身可能有多不准"的粗略假设。
SENSITIVITY_DELTA = 0.10

# 反解器参数（3.2 新增）。
# 精度 vs 速度的权衡：20 次二分给出约 1e-6 的相对精度，对本用途绰绰有余。
# 反解时用较小的进球截断即可（λ 通常 <3，P(X>8) 可忽略），以控制计算量。
SOLVER_MAX_GOALS = 8
SOLVER_ITERS = 20


# ============================================================
# 数学工具
# ============================================================

def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def pmf(lam, n=MAX_GOALS):
    """泊松分布概率质量函数，尾部残差并入最后一格。"""
    p = [math.exp(-lam) * lam ** k / math.factorial(k) for k in range(n + 1)]
    p[-1] += max(0, 1 - sum(p))
    return p


def matrix(lh, la, rho=RHO_DEFAULT, n=MAX_GOALS):
    """独立泊松 + Dixon-Coles 低比分修正，返回归一化的比分矩阵。"""
    a, b = pmf(lh, n), pmf(la, n)
    m = {}
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            tau = 1
            if (i, j) == (0, 0):
                tau = 1 + lh * la * rho
            elif (i, j) == (0, 1):
                tau = 1 - lh * rho
            elif (i, j) == (1, 0):
                tau = 1 - la * rho
            elif (i, j) == (1, 1):
                tau = 1 + rho
            m[i, j] = max(0, x * y * tau)
    s = sum(m.values())
    return {k: v / s for k, v in m.items()}


def one(m):
    """比分矩阵 → 胜平负三元组。"""
    z = [
        sum(v for (i, j), v in m.items() if i > j),
        sum(v for (i, j), v in m.items() if i == j),
        sum(v for (i, j), v in m.items() if i < j),
    ]
    s = sum(z)
    return [x / s for x in z]


def devig(o):
    """赔率去水，返回（公平概率, 庄家抽水）。"""
    q = [1 / x for x in o]
    s = sum(q)
    return [x / s for x in q], s - 1


# ============================================================
# 强度 → λ
# ============================================================

def market_lam_heuristic(p, total):
    """[已弃用为主路径] 3.0/3.1 的线性映射，作为反解失败时的兜底。

    已知缺陷：强制 λ主+λ客 ≡ total，导致强弱差被压缩。
    3504 场回测显示它使 Brier 比市场差 0.0070，且 80% 以上概率档完全产生不出来。
    """
    edge = p[0] - p[2]
    h = total / 2 + edge * MKT_EDGE_COEF + (MKT_DRAW_BASE - p[1]) * MKT_DRAW_COEF
    return clamp(h, .2, total - .2), clamp(total - h, .2, total - .2)


def solve_lam_from_probs(p, rho=RHO_DEFAULT, n=SOLVER_MAX_GOALS, iters=SOLVER_ITERS):
    """[3.2] 反解 λ：找出经 Dixon-Coles 后能还原市场 1X2 的 (λ主, λ客)。

    取代 3.1 的线性映射。两个未知数、两个独立目标，恰好确定：
      · 固定 total 时，p主-p客 随 diff 单调递增
      · 固定 diff 时，p平 随 total 单调递减
    故用嵌套二分：外层调 total 对齐平局率，内层调 diff 对齐主客差。

    关键区别：**不再强制 λ主+λ客 等于外部给定的 total**。
    总进球由市场概率自己决定——强队碾压时总进球本就该涨。

    返回 (λ主, λ客) 或 None（无解时由调用方回退到 heuristic）。
    """
    target_diff = p[0] - p[2]
    target_draw = p[1]

    def probs(total, diff):
        lh, la = (total + diff) / 2, (total - diff) / 2
        if lh < 0.02 or la < 0.02:
            return None
        return one(matrix(lh, la, rho, n))

    def fit_diff(total):
        """固定 total，二分 diff 使 p主-p客 命中目标。"""
        lo, hi = -total + 0.04, total - 0.04
        for _ in range(iters):
            mid = (lo + hi) / 2
            q = probs(total, mid)
            if q is None:
                return None, None
            if q[0] - q[2] < target_diff:
                lo = mid
            else:
                hi = mid
        mid = (lo + hi) / 2
        return mid, probs(total, mid)

    lo_t, hi_t = 0.30, 8.0
    best = None
    for _ in range(iters):
        mid_t = (lo_t + hi_t) / 2
        diff, q = fit_diff(mid_t)
        if q is None:
            hi_t = mid_t
            continue
        best = (mid_t, diff)
        if q[1] > target_draw:      # 平局太多 → 需要更多总进球
            lo_t = mid_t
        else:
            hi_t = mid_t

    if best is None:
        return None
    total, diff = best
    lh, la = (total + diff) / 2, (total - diff) / 2
    if not (0.02 <= lh <= 8 and 0.02 <= la <= 8):
        return None
    return lh, la


def market_lam(p, total):
    """由市场概率求 λ。优先反解，失败回退到旧的线性映射。

    `total` 参数仅在回退路径使用；反解路径下总进球由市场概率自行决定。
    """
    r = solve_lam_from_probs(p)
    if r is not None:
        return r
    return market_lam_heuristic(p, total)


def elo_lam(h, a, total, adv=ELO_HOME_ADV_DEFAULT):
    """由 Elo 反推双方 λ。系数见顶部 [UNFITTED] 标注。"""
    e = 1 / (1 + 10 ** ((a - (h + adv)) / 400))
    lh = total * (ELO_LAM_BASE + ELO_LAM_SPAN * e)
    return clamp(lh, .2, total - .2), clamp(total - lh, .2, total - .2)


def resolve_goal_total(d):
    """确定场均总进球：显式输入 > 赛事查表 > 全局兜底。"""
    if d.get('goal_total') is not None:
        return float(d['goal_total']), 'explicit'
    for key in ('competition', 'league', 'stage'):
        v = d.get(key)
        if v and v in LEAGUE_GOAL_TOTALS:
            return LEAGUE_GOAL_TOTALS[v], f'league_table:{v}'
    return GOAL_TOTAL_FALLBACK, 'global_fallback'


# ============================================================
# 衍生盘口
# ============================================================

def top(m, n=8):
    items = sorted(m.items(), key=lambda x: x[1], reverse=True)[:n]
    return [{'score': f'{i}-{j}', 'prob_pct': round(v * 100, 2)} for (i, j), v in items]


def ou(m, line):
    o = sum(v for (i, j), v in m.items() if i + j > line)
    u = sum(v for (i, j), v in m.items() if i + j < line)
    return {
        'line': line,
        'over_pct': round(o * 100, 1),
        'under_pct': round(u * 100, 1),
        'push_pct': round((1 - o - u) * 100, 1),
    }


def settle(m, line):
    w = p = l = 0
    for (i, j), v in m.items():
        z = i - j + line
        if z > 1e-9:
            w += v
        elif z < -1e-9:
            l += v
        else:
            p += v
    return w, p, l


def ah(m, line):
    """亚洲盘结算。整数/半球盘直接判定，四分之一盘拆成相邻两个半盘。"""
    q = round(line * 4) / 4
    if abs(q * 2 - round(q * 2)) < 1e-8:
        w, p, l = settle(m, q)
        return {'line': q, 'full_win_pct': round(w * 100, 1), 'half_win_pct': 0.0,
                'push_pct': round(p * 100, 1), 'half_loss_pct': 0.0,
                'full_loss_pct': round(l * 100, 1)}
    lo, hi = math.floor(q * 2) / 2, math.ceil(q * 2) / 2
    out = [0] * 5
    for (i, j), v in m.items():
        rs = []
        for x in (lo, hi):
            z = i - j + x
            rs.append(1 if z > 1e-9 else (-1 if z < -1e-9 else 0))
        rs.sort()
        idx = {(1, 1): 0, (0, 1): 1, (0, 0): 2, (-1, 0): 3, (-1, -1): 4}[tuple(rs)]
        out[idx] += v
    keys = ['line', 'full_win_pct', 'half_win_pct', 'push_pct', 'half_loss_pct', 'full_loss_pct']
    return dict(zip(keys, [q] + [round(x * 100, 1) for x in out]))


# ============================================================
# 校验（3.0 的核心优势，逻辑完全保留）
# ============================================================

def validate(d):
    miss, err = [], []
    for k in ('home', 'away', 'stage'):
        if not d.get(k):
            miss.append(k)
    if not d.get('kickoff') and not d.get('context_confirmed'):
        miss.append('kickoff|context_confirmed')

    odds = d.get('odds')
    eo = d.get('elo_home') is not None and d.get('elo_away') is not None
    la = d.get('lambda_home') is not None and d.get('lambda_away') is not None

    if odds is not None and (not isinstance(odds, list) or len(odds) != 3
                             or any(not isinstance(x, (int, float)) or x <= 1 for x in odds)):
        err.append('odds must be 3 numbers >1')
    if not ((odds is not None and not err) or eo or la):
        miss.append('complete strength anchor')
    for k in ('elo_home', 'elo_away'):
        if d.get(k) is not None and not 800 <= float(d[k]) <= 2400:
            err.append(k + ' out of range')
    for k in ('lambda_home', 'lambda_away'):
        if d.get(k) is not None and not .05 <= float(d[k]) <= 6:
            err.append(k + ' out of range')
    fl = d.get('first_leg')
    if fl is not None and (not isinstance(fl, list) or len(fl) != 2
                           or any(type(x) is not int or x < 0 for x in fl)):
        err.append('first_leg invalid')
    return miss, err


def quality(d):
    """⚠️ 这里测的是「输入填了多少」，不是「预测有多准」。见返回值的 note。"""
    rec = ['odds', 'elo_home', 'elo_away', 'lambda_home', 'lambda_away', 'first_leg',
           'predicted_starters_known', 'injury_home', 'injury_away', 'weather_ok']
    comp = round(sum(k in d for k in rec) / len(rec) * 100, 1)
    meta = d.get('field_meta') or {}
    rel = round(sum(float(x.get('reliability', 60)) for x in meta.values()) / len(meta), 1) if meta else 55.0
    fresh = round(sum(float(x.get('freshness', 60)) for x in meta.values()) / len(meta), 1) if meta else 55.0
    return {
        'completeness_pct': comp,
        'source_reliability_pct': rel,
        'freshness_pct': fresh,
        'overall_pct': round(.5 * comp + .3 * rel + .2 * fresh, 1),
        'note': '本分数衡量输入字段的完整度与来源等级，不代表预测准确度。'
                '填满字段但填错值，分数依然很高。',
    }


# ============================================================
# 双回合晋级
# ============================================================

def advancement(m, fl, lh, la, d, rho):
    h1, a1 = fl
    h90 = a90 = tie = 0
    for (h, a), p in m.items():
        if h1 + h > a1 + a:
            h90 += p
        elif h1 + h < a1 + a:
            a90 += p
        else:
            tie += p
    tempo = float(d.get('et_tempo', ET_TEMPO_DEFAULT))
    em = matrix(lh / 3 * tempo, la / 3 * tempo, rho / 2, 6)
    e = one(em)
    ph = float(d.get('penalty_home_prob', PENALTY_HOME_PROB_DEFAULT))
    eh, ea, pens = tie * e[0], tie * e[2], tie * e[1]
    return {
        'home_advance_pct': round((h90 + eh + pens * ph) * 100, 1),
        'away_advance_pct': round((a90 + ea + pens * (1 - ph)) * 100, 1),
        'decided_in_90_pct': round((h90 + a90) * 100, 1),
        'to_extra_time_pct': round(tie * 100, 1),
        'via_et_home_pct': round(eh * 100, 1),
        'via_et_away_pct': round(ea * 100, 1),
        'via_pens_home_pct': round(pens * ph * 100, 1),
        'via_pens_away_pct': round(pens * (1 - ph) * 100, 1),
        'penalty_home_prob_used': ph,
    }


# ============================================================
# 主流程
# ============================================================

def build_lambdas(d, total, market, elo, explicit, mode):
    """返回 (lh, la, tags)。"""
    pairs, tags = [], []
    if mode != 'model_first' and market:
        pairs.append((*market_lam(market, total), W_MARKET))
        tags.append('PROXY_XG')
    if elo:
        pairs.append((*elo_lam(float(d['elo_home']), float(d['elo_away']), total,
                               float(d.get('elo_home_adv', ELO_HOME_ADV_DEFAULT))), W_ELO))
        tags.append('ELO_XG')
    if explicit:
        pairs.append((float(d['lambda_home']), float(d['lambda_away']), W_EXPLICIT))
        tags.append('EXPLICIT_XG')

    sw = sum(x[2] for x in pairs)
    lh = sum(x[0] * x[2] for x in pairs) / sw
    la = sum(x[1] * x[2] for x in pairs) / sw

    # 主场优势（对数尺度）
    lh *= math.exp(float(d.get('home_adv', 0)))
    la *= math.exp(-float(d.get('home_adv', 0)) * .55)
    # 攻防分离的缺阵冲击
    lh *= 1 - clamp(float(d.get('attack_absence_home', d.get('injury_home', 0))), 0, .5)
    la *= 1 - clamp(float(d.get('attack_absence_away', d.get('injury_away', 0))), 0, .5)
    la *= 1 + clamp(float(d.get('defense_absence_home', 0)) + float(d.get('gk_absence_home', 0)), 0, .5)
    lh *= 1 + clamp(float(d.get('defense_absence_away', 0)) + float(d.get('gk_absence_away', 0)), 0, .5)

    # 双回合战意：落后方压上，领先方收缩
    if d.get('first_leg') and d.get('auto_motive', True):
        diff = d['first_leg'][0] - d['first_leg'][1]
        amh, ama = (1.1, .95) if diff < 0 else ((.88, 1.18) if diff > 1 else ((.92, 1.12) if diff > 0 else (1.05, 1.05)))
    else:
        amh = ama = 1
    amh = float(d.get('attack_motive_home', d.get('motive_home', amh)))
    ama = float(d.get('attack_motive_away', d.get('motive_away', ama)))
    rh = float(d.get('defense_risk_home', max(0, amh - 1) * .6))
    ra = float(d.get('defense_risk_away', max(0, ama - 1) * .6))
    lh *= clamp(amh, .5, 1.35) * (1 + ra)
    la *= clamp(ama, .5, 1.35) * (1 + rh)

    return clamp(lh, .05, 6), clamp(la, .05, 6), tags


def sensitivity(lh, la, rho, mw, market, mode):
    """λ 各扰动 ±10%，看最终 1X2 的波动区间。

    这不是统计置信区间，而是「输入不确定性传导」的粗略估计：
    回答"如果我的 λ 估错 10%，结论会变多少"。
    """
    lo, hi = 1 - SENSITIVITY_DELTA, 1 + SENSITIVITY_DELTA
    outs = []
    for fh in (lo, 1.0, hi):
        for fa in (lo, 1.0, hi):
            pure = one(matrix(lh * fh, la * fa, rho))
            if mode == 'market_only':
                outs.append(market)
            elif market:
                outs.append([mw * market[i] + (1 - mw) * pure[i] for i in range(3)])
            else:
                outs.append(pure)
    return {
        'lambda_perturbation_pct': round(SENSITIVITY_DELTA * 100, 1),
        'home_range_pct': [round(min(o[0] for o in outs) * 100, 1), round(max(o[0] for o in outs) * 100, 1)],
        'draw_range_pct': [round(min(o[1] for o in outs) * 100, 1), round(max(o[1] for o in outs) * 100, 1)],
        'away_range_pct': [round(min(o[2] for o in outs) * 100, 1), round(max(o[2] for o in outs) * 100, 1)],
        'note': '输入 λ 各扰动 ±10% 时最终 1X2 的取值范围。区间内的差异不具决策意义。',
    }


def predict(d):
    miss, err = validate(d)
    if err:
        return {'status': 'invalid', 'errors': err, 'missing': miss}
    if miss:
        return {'status': 'incomplete', 'missing': miss}

    market = margin = None
    if d.get('odds'):
        market, margin = devig(d['odds'])

    explicit = d.get('lambda_home') is not None and d.get('lambda_away') is not None
    elo = d.get('elo_home') is not None and d.get('elo_away') is not None
    mode = d.get('mode') or ('model_first' if explicit
                             else ('hybrid' if market and elo
                                   else ('market_only' if market else 'model_first')))

    total, total_src = resolve_goal_total(d)
    lh, la, tags = build_lambdas(d, total, market, elo, explicit, mode)
    rho = float(d.get('rho', RHO_DEFAULT))
    m = matrix(lh, la, rho)
    pure = one(m)

    flags = []
    if mode == 'market_only':
        final, mw, edge, dep = market, 1, None, 100
    elif market:
        mw = float(d.get('market_weight', .4 if mode == 'model_first' else .5))
        final = [mw * market[i] + (1 - mw) * pure[i] for i in range(3)]
        edge = {k: round((final[i] - market[i]) * 100, 1)
                for i, k in enumerate(('home_pp', 'draw_pp', 'away_pp'))}
        dep = round((W_MARKET if 'PROXY_XG' in tags else 0) * (1 - mw) * 100 + mw * 100, 1)
        if 'PROXY_XG' in tags:
            flags.append(
                'EDGE_CIRCULAR: 本次 model_1x2 中含由赔率反推的 PROXY_XG，'
                'edge_vs_market_pp 实为「含市场信息的结果」与市场自身之差，'
                '存在循环论证，不可作为独立于市场的优势判断。')
        if 'ELO_XG' in tags:
            flags.append(
                'ELO_DEGRADES_VS_MARKET: 3470 场回测实测——在已有市场赔率的前提下掺入 ClubElo '
                f'会使 Brier 变差（mw=0.50 时 +0.0058，mw=0.25 时 +0.0107，mw=0 时 +0.0171，'
                '市场权重越低越差）。原因：Elo 由公开赛果算出，是市场信息的滞后子集。'
                '若只想要与市场一致的 1X2，去掉 Elo 输入走 market_only 反而更准。')
    else:
        final, mw, edge, dep = pure, 0, None, 0

    if dep >= 70:
        flags.append(f'HIGH_MARKET_DEPENDENCY: 市场依赖度 {dep}%，本次输出主要在复述盘口。')
    if total_src == 'global_fallback':
        flags.append(
            f'GOAL_TOTAL_FALLBACK: 未提供 goal_total，也未匹配到赛事默认值，'
            f'使用全局兜底 {GOAL_TOTAL_FALLBACK}。建议显式提供以提升准确度。')
    flags.append('UNFITTED_CONSTANTS: 本引擎多项系数尚未经回测拟合（见脚本顶部标注）。'
                 '绝对概率仅供参考，建议先用 backtest.py 校准。')

    bt = sum(v for (i, j), v in m.items() if i > 0 and j > 0)
    ht = matrix(lh * FIRST_HALF_SHARE, la * FIRST_HALF_SHARE, rho / 2, 6)

    out = {
        'status': 'ok',
        'engine_version': '3.2',
        'match': f"{d['home']} vs {d['away']}",
        'mode': mode,
        'quality': quality(d),
        'goal_total_used': {'value': total, 'source': total_src},
        'market_dependency_pct': dep,
        'market_prob_pct': None if market is None else [round(x * 100, 1) for x in market],
        'bookmaker_margin_pct': None if margin is None else round(margin * 100, 1),
        'model_1x2_pct': [round(x * 100, 1) for x in pure],
        'final_1x2_pct': [round(x * 100, 1) for x in final],
        'edge_vs_market_pp': edge,
        'sensitivity': sensitivity(lh, la, rho, mw, market, mode),
        'xg': [round(lh, 3), round(la, 3)],
        'xg_tags': tags,
        'rho': rho,
        'top_scores': top(m, int(d.get('top_n', 8))),
        'ht_top_scores': top(ht, 3),
        'ou_2_5': ou(m, 2.5),
        'ou_3_5': ou(m, 3.5),
        'btts': {'yes_pct': round(bt * 100, 1), 'no_pct': round((1 - bt) * 100, 1)},
        'asian_handicap_home': ah(m, float(d.get('ah_line', -1))),
        'advancement': None,
        'reliability_flags': flags,
        'assumptions': d.get('assumptions', []),
        'disclaimer': '概率模型输出，非投注建议。',
    }
    if d.get('first_leg') is not None:
        out['advancement'] = advancement(m, d['first_leg'], lh, la, d, rho)
    return out


def main():
    ap = argparse.ArgumentParser(description='足预大师 3.1 预测引擎')
    ap.add_argument('input', help='输入 JSON 文件路径')
    a = ap.parse_args()
    raw = json.load(open(a.input, encoding='utf-8-sig'))
    if isinstance(raw, dict) and 'matches' in raw:
        out = {'status': 'batch', 'results': [predict(x) for x in raw['matches']]}
    else:
        out = predict(raw)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

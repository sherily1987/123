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

ENGINE_VERSION = '3.4.5'
# 去水默认 [FITTED 2026-08-02]：proportional → power
# 依据（三源独立回测，时间切分）：
#   - 独立集 devig_backtest_400（Pinnacle 收盘，芬/瑞/挪/美×100）：power Brier 0.5660 < proportional 0.5670
#   - 五大联赛 46696 场：power Brier 0.582545 / ECE 0.00134 < proportional 0.582933 / ECE 0.00780
#   - 体彩2026收盘HAD 测试集410场：power+现有K/T校准 ECE 0.0172 < proportional+K/T 0.0276
# ⚠️ 耦合说明：1X2 校准层(K=1.14/T=0.96)与O/U Platt等按 proportional 拟合；
#   power 下应重拟合 K/T（体彩训练集 raw 上 proportional 仍占优即此耦合所致，列为跟进项）。
DEVIG_METHOD_DEFAULT = 'power'

# ============================================================
# 1X2 校准层 [FITTED 2026-08-02]
# ------------------------------------------------------------
# 与本文件其他 [UNFITTED] 常数不同，以下两个系数是**真正拟合出来的**：
#   数据：中国体彩 2026 赛季全联赛收盘 HAD，已完赛且赔率完整 1348 场
#   切分：按 matchDate 时间序列切分，前 70%(943场, 01-14~05-17) 训练，
#         后 30%(405场, 05-17~08-01) 测试。测试集未参与拟合。
#   动机：1348 场实测市场去水后平局概率被系统性低估——
#         期望平局 331.9 场 vs 实际 368 场，z=+2.30（显著，|z|>1.96）。
#         且低估随平局概率升高而加剧：P平28-32%档 +6.0pp，32%+档 +7.3pp。
#   效果（测试集，未参与拟合）：
#         Brier  0.18657 → 0.18644
#         LogLoss 0.94512 → 0.94413
#         ECE    0.04697 → 0.03456（改善 26.4%，主要收益在此）
#   ⚠️ 这是**校准改善**，不是"预测更准"。argmax 命中率 55.80% → 55.31%，
#      基本不变甚至略降。它让概率数值更可信，不让你多猜中比赛。
DRAW_CALIBRATION_K = 1.14    # 平局概率乘子
CALIBRATION_TEMPERATURE = 0.96  # 温度缩放，T<1 略微锐化

# ---- 联赛感知校准 [2026-08-02 加入] ----
# 规则：识别为五大联赛(顶级)的比赛使用 football-data 46696场时间外推验证的
# 校准参数；其余联赛沿用中国体彩2026全联赛1348场拟合参数。
# 验证证据：big5_calibrate_validate_2026-08-02 —— 五大联赛 test 13997场上
# 无额外校准(K=1.0,T=1.0)优于原参数(K=1.14,T=0.96)：Brier 0.577228 vs 0.578084、
# ECE 0.00442 vs 0.01410。⚠️ 迁移未经体彩侧五大联赛子集复验，按用户指示执行。
BIG5_CALIBRATION = {'draw_k': 1.0, 'temperature': 1.0,
                    'basis': 'football-data五大联赛46696场 时间外推test验证 无额外校准最优',
                    'key': 'BIG5'}
DEFAULT_CALIBRATION = {'draw_k': DRAW_CALIBRATION_K, 'temperature': CALIBRATION_TEMPERATURE,
                       'basis': '中国体彩2026全联赛收盘HAD 1348场 时间序列切分 训练943/测试405',
                       'key': 'OTHER'}

# ---- 比分模型与分布校准 [FITTED 2026-08-02] ----
# 双变量泊松共享项 λ3=0.20 [FITTED 2026-08-21]：中国体彩 2026 全联赛收盘 HAD，
# 严格按比赛日 70/30 切分（训练949 / 测试401；训练≤05-17，测试≥05-18）。
# 测试集：完整比分 LL 2.838031→2.812950、Top1 13.72%→13.97%、Top3 36.41%→39.40%；
# O/U2.5 Brier 0.244689→0.236798，O/U3.5 Brier 0.202731→0.198775。
# 1X2 路径（λ反解/one/sensitivity）保留 DC 矩阵，保证胜平负概率不受此项改变；衍生市场用 BP。
# 温度 T=1.30 仅缩放 Top 比分的展示概率，单调变换不改变 Top-N 排名，不能被表述为命中率提升。
# 半场比分 7×7：T=1.22 —— test LogLoss 2.029→2.009、ECE 0.00322→0.00067
SCORE_MODEL = 'bp'
SCORE_LAMBDA3 = 0.20
SCORE_TEMPERATURE_FT = 1.30
SCORE_TEMPERATURE_HT = 1.22
SCORE_CALIBRATION_BASIS = ('中国体彩2026全联赛收盘HAD 严格比赛日时间切分(训练949/测试401)：'
                           '双变量泊松原始比分矩阵λ3=0.20，测试比分LL 2.838031→2.812950；'
                           'O/U2.5/3.5 Brier 0.244689→0.236798、0.202731→0.198775。'
                           'Top比分展示温度T=1.30仅校准概率大小，不改变排名。')

# 五大联赛识别映射（精确 key 匹配，避免把英冠/西乙/德乙/意乙/法乙等次级联赛误判）
_BIG5_ALIASES = {
    '英超': 'EPL', '英格兰超级联赛': 'EPL', '英格兰足球超级联赛': 'EPL',
    'premier league': 'EPL', 'premierleague': 'EPL', 'epl': 'EPL', 'e0': 'EPL',
    '西甲': 'LALIGA', '西班牙甲级联赛': 'LALIGA', 'la liga': 'LALIGA', 'laliga': 'LALIGA', 'sp1': 'LALIGA',
    '德甲': 'BUNDESLIGA', '德国甲级联赛': 'BUNDESLIGA', 'bundesliga': 'BUNDESLIGA', 'd1': 'BUNDESLIGA',
    '意甲': 'SERIEA', '意大利甲级联赛': 'SERIEA', 'serie a': 'SERIEA', 'seriea': 'SERIEA', 'i1': 'SERIEA',
    '法甲': 'LIGUE1', '法国甲级联赛': 'LIGUE1', 'ligue 1': 'LIGUE1', 'ligue1': 'LIGUE1', 'f1': 'LIGUE1',
}

# ---- 非五大联赛专属校准 [FITTED-LEAGUE 2026-08-02] ----
# 数据：football-data /new/ Pinnacle 收盘（芬超2530/瑞超3366/巴西甲5275，2012-2026），
# 按日期 70/30 时间切分，train 网格选优（draw_k×temperature），test 验证；去水 power。
# 结果（test ECE）：芬超 0.0260 vs 体彩默认 0.0356；瑞超 0.0103 vs 0.0194；巴西甲 0.0120 vs 0.0224。
# ⚠️ 传输注意：拟合源为 Pinnacle 收盘，体彩侧 sanity 芬超50/瑞超49 样本小、瑞超与默认互有胜负，
#   待体彩各联赛样本 ≥100 后应改用体彩侧重拟合。巴西杯暂用巴西甲参数代理。
_LEAGUE_KT = {
    'FIN': {'draw_k': 0.95, 'temperature': 0.95,
            'basis': '芬超 football-data Pinnacle 2530场 70/30切分 test ECE 0.0260（去水power）', 'key': 'FIN'},
    'SWE': {'draw_k': 1.05, 'temperature': 1.05,
            'basis': '瑞超 football-data Pinnacle 3366场 70/30切分 test ECE 0.0103（去水power）', 'key': 'SWE'},
    'BRA': {'draw_k': 0.90, 'temperature': 1.00,
            'basis': '巴西甲 football-data Pinnacle 5275场 70/30切分 test ECE 0.0120（去水power）', 'key': 'BRA'},
}
_LEAGUE_KT_ALIASES = {
    '芬超': 'FIN', '芬兰超级联赛': 'FIN', 'veikkausliiga': 'FIN', 'finland': 'FIN', 'fin': 'FIN',
    '瑞超': 'SWE', '瑞典超级联赛': 'SWE', 'allsvenskan': 'SWE', 'sweden': 'SWE', 'swe': 'SWE',
    '巴西甲': 'BRA', '巴西甲级联赛': 'BRA', 'brasileirao': 'BRA', 'brazil': 'BRA', 'bra': 'BRA',
    '巴西杯': 'BRA',  # 巴西杯暂无专属样本，用巴西甲参数代理
}


# [中文功能] 按比赛识别联赛并返回对应校准参数
def league_calibration(d):
    """按比赛识别联赛，返回对应校准参数 dict（含 key/basis）。"""
    raw = [str(x) for x in (d.get('competition'), d.get('stage'), d.get('league')) if x]
    s = ' '.join(raw)
    tokens = [t.strip().lower() for t in s.replace('_', ' ').split() if t.strip()]
    for cand in [s.strip().lower()] + tokens:
        if cand in _BIG5_ALIASES:
            return dict(BIG5_CALIBRATION)
        if cand in _LEAGUE_KT_ALIASES:
            return dict(_LEAGUE_KT[_LEAGUE_KT_ALIASES[cand]])
    return dict(DEFAULT_CALIBRATION)

# 星级 ⇄ 最大概率区间。[FITTED 2026-08-02 初版 → 2026-08-12 对齐 band 校准]
# ⚠️ 2026-08-12 修订：原实测命中率（87.5/69.6/56.6/47.4/36.5）来自 2026-08-02 的
#    405 场测试集，与 2026-08-06 全快照池 1478 场 band 校准严重脱节——60-69% 段
#    星级暗示 69.6% 命中，实际 band 校准仅 40-45%（高估 25-30pp，会误导"4星=高置信"）。
#    现改为 band 表同源命中率（recommendation_policy.json band_table_plus_edge，
#    主方向概率分箱实测命中率，细分开赛前高概率段）。
STAR_BANDS = [(0.70, 5), (0.60, 4), (0.50, 3), (0.40, 2), (0.0, 1)]
# band 同源命中率（2026-08-06 校准，n=1478 池）：
#   <0.40→42.57%(n909) / 0.40-0.45→40.43%(n94) / 0.45-0.50→53.85%(n117) /
#   0.50-0.55→69.01%(n71) / 0.55-0.60→52.11%(n71) / 0.60-0.65→45.07%(n71) /
#   0.65-0.70→40.00%(n45) / 0.70+→72.00%(n100)
#   星级聚合口径（按原星级边界取 band 加权平均）：
#   ★5 (≥0.70) = 72.00 (n100)
#   ★4 (0.60-0.70) = (71*45.07+45*40.00)/116 = 43.10 (n116)
#   ★3 (0.50-0.60) = (71*69.01+71*52.11)/142 = 60.56 (n142)
#   ★2 (0.40-0.50) = (94*40.43+117*53.85)/211 = 47.87 (n211)
#   ★1 (<0.40) = 42.57 (n909)
STAR_OBSERVED_HIT = {5: 72.0, 4: 43.1, 3: 60.6, 2: 47.9, 1: 42.6}
STAR_SAMPLE_N = {5: 100, 4: 116, 3: 142, 2: 211, 1: 909}


# [中文功能] 对胜平负概率施加平局修正+温度缩放
def calibrate_1x2(p, draw_k=None, temperature=None):
    """对 [主,平,客] 概率施加已拟合的平局修正 + 温度缩放。

    draw_k / temperature 缺省时使用全局常量（体彩默认参数）；
    由调用方按联赛传入不同参数（如五大联赛 K=1.0/T=1.0）。
    """
    if not p or len(p) != 3:
        return p
    k = DRAW_CALIBRATION_K if draw_k is None else float(draw_k)
    t = CALIBRATION_TEMPERATURE if temperature is None else float(temperature)
    q = [p[0], p[1] * k, p[2]]
    s = sum(q)
    if s <= 0:
        return p
    q = [x / s for x in q]
    q = [x ** t for x in q]
    s = sum(q)
    return [x / s for x in q]


# [中文功能] 由最大概率映射星级（含实测命中率与样本量）
def star_rating(pmax):
    """由最大概率给出星级。返回 (星数, 字符串, 该档实测命中率, 样本量)。"""
    for lo, s in STAR_BANDS:
        if pmax >= lo:
            return s, '★' * s + '☆' * (5 - s), STAR_OBSERVED_HIT[s], STAR_SAMPLE_N[s]
    return 1, '★☆☆☆☆', STAR_OBSERVED_HIT[1], STAR_SAMPLE_N[1]
try:
    from odds_methods import devig as _devig_method
except ImportError:
    _devig_method = None
try:
    from market_fit import fit as fit_multi_market, hafu_probs as _hafu_probs
except ImportError:
    fit_multi_market = None
    _hafu_probs = None

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
# [FITTED-CONFIRMED 2026-08-02] 1348场时间序列切分实测：训练集按比分LogLoss最优 -0.07，
#   与默认 -0.08 差 0.01；测试集 -0.08(2.80462) 反而**优于** -0.07(2.80495)。
#   判定：默认值已在最优平坦区内，**维持 -0.08**，不做改动。
RHO_DEFAULT = -0.08

# ============================================================
# 衍生盘口校准层 [FITTED 2026-08-02]
# ------------------------------------------------------------
# 数据/切分同 1X2 校准层：体彩2026全联赛1348场，训练943(01-14~05-17)/测试405(05-17~08-01)。
# 方法：Platt scaling  q = sigmoid(a * logit(p) + b)，仅在训练集拟合。
#
# 测试集实测（未参与拟合）：
#   O/U2.5  Brier 0.23524→0.23389  ECE 0.06470→0.04710（改善27.2%）  ✅采用
#   O/U3.5  Brier 0.19756→0.19506  ECE 0.06196→0.03611（改善41.7%）  ✅采用
#   BTTS    Brier 0.24071→0.24046  ECE 0.02130→0.02650（**恶化24.4%**） ❌不采用
#
# ⚠️ BTTS 原始输出 ECE 仅 0.0213，本已良好校准，Platt 反而过拟合训练集噪声。
#    故 BTTS **不施加任何校准**，保持矩阵原始输出。这是负结果，如实保留。
OU_CALIBRATION = {2.5: (1.03, -0.08), 3.5: (1.05, -0.11)}
BTTS_CALIBRATION = None  # 实测校准无效，刻意留空，勿填


# [中文功能] Platt校准变换（logit回归映射）
def _platt(p, a, b):
    p = min(max(p, 1e-9), 1 - 1e-9)
    z = a * math.log(p / (1 - p)) + b
    return 1 / (1 + math.exp(-z))

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

# 点球大战主队获胜概率（主队=次回合主场球队）。
# [FITTED 2026-08-02] 两回合样本库 24 场点球决胜：次回合主场胜 9/24 = 0.375，
#   95% CI [0.212, 0.573]（Wilson）。样本内点球主场优势为负（0.50 仍在 CI 内，n 小），
#   与"真正显著的是先罚方优势"的公开研究方向一致。可传 penalty_home_prob: 0.50 覆盖。
PENALTY_HOME_PROB_DEFAULT = 0.38

# 加时赛节奏（相对 90 分钟的每分钟进球率）。
# [FITTED 2026-08-02] 两回合样本库 31 场加时系列（49 加时球 / 178 常规球）：
#   tempo = 3×49/178 = 0.826，95% CI [0.629, 1.023]。旧值 0.92 在 CI 内但偏高。
ET_TEMPO_DEFAULT = 0.83

# 上半场进球占比。
# [VERIFIED 2026-08-01] 用体彩官方 halfTimeGoal/fullCourtGoal 实测 293 场（去重后）：
#   半场总进球 373 / 全场总进球 842 = 0.4430，与本常数 0.45 仅差 -0.0070。
#   主队 0.4437、客队 0.4422，主客几乎无差异，无需拆分。
#   逐场均值 0.4494，中位数 0.5000（因 25.9% 的比赛半场 0 球，分布左偏）。
# 结论：0.45 经实证支持，无需调整。验证脚本见 references/pitfalls.md 二.5。
# [FITTED 2026-08-02] 1348场大样本复核：训练集半场/全场进球比 0.4442、测试集 0.4502。
#   按半场比分 LogLoss 网格搜索训练集最优 0.42，测试集验证 0.42(1.98935) 略优于 0.45(1.99232)，
#   但改善仅 0.0030（0.15%），且两个独立口径（进球比 0.444/0.450）都更接近 0.45。
#   判定：改善幅度小于口径间差异，不足以支持改动。**维持 0.45**，此常数状态由 [UNFITTED] 升为 [FITTED-CONFIRMED]。
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

# [中文功能] 把数值限制在[lo,hi]区间
def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# [中文功能] 泊松概率质量函数（尾部并入最后一格）
def pmf(lam, n=MAX_GOALS):
    """泊松分布概率质量函数，尾部残差并入最后一格。"""
    p = [math.exp(-lam) * lam ** k / math.factorial(k) for k in range(n + 1)]
    p[-1] += max(0, 1 - sum(p))
    return p


# [中文功能] 独立泊松+Dixon-Coles低比分修正生成比分矩阵
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


# [中文功能] 双变量泊松比分矩阵（低比分主客进球正相关，λ3>0）
def bp_matrix(lh, la, lam3, n=MAX_GOALS):
    """双变量泊松：P(i,j) = e^{-λ3} P(i;λh)P(j;λa) Σ_k C(i,k)C(j,k) k! (λ3/(λhλa))^k。"""
    a = pmf(lh, n)
    b = pmf(la, n)
    m = {}
    denom = max(lh * la, 1e-12)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            s = 0.0
            for k in range(min(i, j) + 1):
                s += math.comb(i, k) * math.comb(j, k) * math.factorial(k) * (lam3 / denom) ** k
            m[i, j] = x * y * math.exp(-lam3) * s
    tot = sum(m.values())
    return {k: v / tot for k, v in m.items()}


def bp_matrix_stable(lh, la, lam3, n=MAX_GOALS, tail_buffer=6):
    """计算带尾部缓冲的双变量泊松矩阵，再折叠到展示网格。

    `bp_matrix` 为兼容历史生产概率保留原有截断行为；本函数先在更大的
    网格上计算，再把超出展示上限的比分合并到最后一格，避免高λ场次把
    截断误差集中到单个 (n-1,n-1) 格。它是数值稳定研究入口，不改变默认生产路由。
    """
    size = int(n)
    buffer = max(int(tail_buffer), 0)
    if size < 1:
        raise ValueError("n must be positive")
    if buffer == 0:
        return bp_matrix(lh, la, lam3, n=size)
    raw = bp_matrix(lh, la, lam3, n=size + buffer)
    folded = {}
    for (home, away), value in raw.items():
        key = (min(home, size - 1), min(away, size - 1))
        folded[key] = folded.get(key, 0.0) + value
    total = sum(folded.values())
    return {key: value / total for key, value in folded.items()} if total > 0 else folded


# [中文功能] 比分矩阵温度缩放：p^(1/T) 归一化；T=1.0 时原样返回
def temperature_scale(m, T):
    if T is None or abs(float(T) - 1.0) < 1e-9:
        return m
    inv = 1.0 / float(T)
    cells = {k: max(v, 0.0) ** inv for k, v in m.items()}
    s = sum(cells.values())
    return {k: v / s for k, v in cells.items()} if s > 0 else m


# [中文功能] 比分矩阵聚合为胜平负三元概率
def one(m):
    """比分矩阵 → 胜平负三元组。"""
    z = [
        sum(v for (i, j), v in m.items() if i > j),
        sum(v for (i, j), v in m.items() if i == j),
        sum(v for (i, j), v in m.items() if i < j),
    ]
    s = sum(z)
    return [x / s for x in z]


# [中文功能] 审计极端λ与零封概率（只提示不修改）
def audit_lambda_and_clean_sheet(lh, la, m):
    """审计极端λ和零封概率；只提示，不修改模型概率。"""
    lo, hi = min(lh, la), max(lh, la)
    ratio = hi / lo if lo > 0 else float('inf')
    home_clean = sum(v for (i, j), v in m.items() if j == 0)
    away_clean = sum(v for (i, j), v in m.items() if i == 0)
    flags = []
    # 该阈值用于识别“强弱被映射得过开”，不是有效性判定。
    if hi >= 3.2 and lo <= 0.45 or ratio >= 6.0:
        flags.append(
            f'EXTREME_LAMBDA_ASYMMETRY: λ主={lh:.3f}, λ客={la:.3f}, '
            f'高低比={ratio:.1f}；强弱差可能被放大，需核对市场/TTG/xG与伤停输入。')
    if home_clean > 0.55:
        flags.append(
            f'EXTREME_CLEAN_SHEET_HOME: 客队零球概率={home_clean*100:.1f}% (>55%)；'
            '零封结论对λ误差敏感，不能表述为稳胆。')
    if away_clean > 0.55:
        flags.append(
            f'EXTREME_CLEAN_SHEET_AWAY: 主队零球概率={away_clean*100:.1f}% (>55%)；'
            '零封结论对λ误差敏感，不能表述为稳胆。')
    return {
        'lambda_home': round(lh, 3),
        'lambda_away': round(la, 3),
        'lambda_total': round(lh + la, 3),
        'lambda_ratio_high_low': round(ratio, 3),
        'home_clean_sheet_pct': round(home_clean * 100, 1),
        'away_clean_sheet_pct': round(away_clean * 100, 1),
        'thresholds': {
            'lambda_high': 3.2,
            'lambda_low': 0.45,
            'lambda_ratio': 6.0,
            'clean_sheet_warning_pct': 55.0
        },
        'flags': flags
    }


# [中文功能] 赔率去水（默认比例法，其他方法显式启用）
def devig(o, method=DEVIG_METHOD_DEFAULT):
    """赔率去水，返回（公平概率, 庄家抽水）。默认比例法，其他方法显式启用。"""
    if _devig_method is not None:
        return _devig_method(o, method)
    q = [1 / x for x in o]
    s = sum(q)
    return [x / s for x in q], s - 1


# [中文功能] 读取并校验输入指定的去水方法
def selected_devig_method(d=None):
    d = d or {}
    method = d.get('devig_method', DEVIG_METHOD_DEFAULT)
    if method not in ('proportional', 'additive', 'power', 'shin'):
        raise ValueError('devig_method must be proportional|additive|power|shin')
    return method


# ============================================================
# 强度 → λ
# ============================================================

# [中文功能] 旧版线性λ映射（反解失败时的兜底）
def market_lam_heuristic(p, total):
    """[已弃用为主路径] 3.0/3.1 的线性映射，作为反解失败时的兜底。

    已知缺陷：强制 λ主+λ客 ≡ total，导致强弱差被压缩。
    3504 场回测显示它使 Brier 比市场差 0.0070，且 80% 以上概率档完全产生不出来。
    """
    edge = p[0] - p[2]
    h = total / 2 + edge * MKT_EDGE_COEF + (MKT_DRAW_BASE - p[1]) * MKT_DRAW_COEF
    return clamp(h, .2, total - .2), clamp(total - h, .2, total - .2)


# [中文功能] 反解λ：还原市场1X2概率的λ对
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

    # [中文功能] 由总分与差值生成λ对候选
    def probs(total, diff):
        lh, la = (total + diff) / 2, (total - diff) / 2
        if lh < 0.02 or la < 0.02:
            return None
        return one(matrix(lh, la, rho, n))

    # [中文功能] 固定总分二分差值使主客概率命中目标
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


# [中文功能] 由市场概率求λ（优先反解，失败回退线性映射）
def market_lam(p, total):
    """由市场概率求 λ。优先反解，失败回退到旧的线性映射。

    `total` 参数仅在回退路径使用；反解路径下总进球由市场概率自行决定。
    """
    r = solve_lam_from_probs(p)
    if r is not None:
        return r
    return market_lam_heuristic(p, total)


# [中文功能] 由Elo差值反推双方λ
def elo_lam(h, a, total, adv=ELO_HOME_ADV_DEFAULT):
    """由 Elo 反推双方 λ。系数见顶部 [UNFITTED] 标注。"""
    e = 1 / (1 + 10 ** ((a - (h + adv)) / 400))
    lh = total * (ELO_LAM_BASE + ELO_LAM_SPAN * e)
    return clamp(lh, .2, total - .2), clamp(total - lh, .2, total - .2)


# [中文功能] 确定场均总进球：显式>赛事查表>全局兜底
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

# [中文功能] 取概率最高的前n个比分
def top(m, n=8):
    items = sorted(m.items(), key=lambda x: x[1], reverse=True)[:n]
    return [{'score': f'{i}-{j}', 'prob_pct': round(v * 100, 2)} for (i, j), v in items]


# [中文功能] 由比分矩阵计算大小球（含走盘）
def ou(m, line, calibrate=True):
    o = sum(v for (i, j), v in m.items() if i + j > line)
    u = sum(v for (i, j), v in m.items() if i + j < line)
    push = 1 - o - u
    out = {'line': line}
    ab = OU_CALIBRATION.get(line) if calibrate else None
    if ab and push < 1e-9:
        o_raw = o
        o = _platt(o, ab[0], ab[1])
        u = 1 - o
        out['calibration'] = {
            'applied': True, 'method': 'platt', 'a': ab[0], 'b': ab[1],
            'uncalibrated_over_pct': round(o_raw * 100, 1),
            'shift_pp': round((o - o_raw) * 100, 2),
            'test_set_ece': ('0.06470→0.04710' if line == 2.5 else '0.06196→0.03611'),
            'fitted_on': '体彩2026全联赛1348场，训练943/测试405'}
    elif calibrate:
        out['calibration'] = {'applied': False,
                              'reason': '该盘口线未拟合校准系数（仅2.5/3.5已拟合）'}
    out.update({
        'over_pct': round(o * 100, 1),
        'under_pct': round(u * 100, 1),
        'push_pct': round(max(0.0, push) * 100, 1),
    })
    return out


# [中文功能] 按让球线结算主胜/平/负三态概率
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


# [中文功能] 体彩让球胜平负三态（区别于亚洲盘）
def hhad_three_way(m, line, odds=None, devig_method=DEVIG_METHOD_DEFAULT):
    """体彩HHAD三项：让球后主胜/平/负；与二项亚洲盘严格区分。"""
    w, p, l = settle(m, float(line))
    out = {
        'line': float(line),
        'model_prob_pct': [round(w*100,1), round(p*100,1), round(l*100,1)],
        'let_win_pct': round(w*100,1),
        'let_draw_pct': round(p*100,1),
        'let_loss_pct': round(l*100,1),
        'state_labels': ['让胜', '让平', '让负'],
        'integer_line_push_is_one_goal_home_win': bool(abs(float(line) - round(float(line))) < 1e-9),
    }
    if odds:
        mp, margin = devig(odds, devig_method)
        out['devig_method'] = devig_method
        out.update({'odds': odds, 'market_prob_pct': [round(x*100,1) for x in mp],
                    'market_let_win_pct': round(mp[0]*100,1),
                    'market_let_draw_pct': round(mp[1]*100,1),
                    'market_let_loss_pct': round(mp[2]*100,1),
                    'bookmaker_margin_pct': round(margin*100,1),
                    'error_pp': [round((q-r)*100,1) for q,r in zip((w,p,l),mp)],
                    'mae_pp': round(sum(abs(q-r) for q,r in zip((w,p,l),mp))/3*100,1)})
    return out


# [中文功能] 亚洲盘结算（整数/半球/四分之一盘）
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

# [中文功能] 校验输入必填字段与强度锚
def validate(d):
    miss, err = [], []
    for k in ('home', 'away', 'stage'):
        if not d.get(k):
            miss.append(k)
    try:
        selected_devig_method(d)
    except ValueError as exc:
        err.append(str(exc))
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

    mode = d.get('mode')
    if mode not in (None, 'market_only', 'hybrid', 'model_first'):
        err.append('mode must be market_only|hybrid|model_first')
    if mode == 'market_only' and odds is None:
        err.append('market_only requires complete odds')
    pr = d.get('lambda_prior') or {}
    prior_ok = pr.get('lambda_home') is not None and pr.get('lambda_away') is not None
    if prior_ok:
        for k in ('lambda_home', 'lambda_away'):
            try:
                if not .05 <= float(pr[k]) <= 6:
                    err.append('lambda_prior.' + k + ' out of range'); prior_ok = False
            except (TypeError, ValueError):
                err.append('lambda_prior.' + k + ' invalid'); prior_ok = False
    if mode == 'hybrid' and (odds is None or not (eo or la or prior_ok)):
        err.append('hybrid requires odds plus paired Elo, paired lambda, or lambda_prior')
    if mode == 'model_first' and not (eo or la):
        err.append('model_first requires paired Elo or paired lambda')

    for k, lo, hi in (
        ('home_adv', -.3, .4), ('elo_home_adv', 0, 150),
        ('market_weight', 0, 1), ('penalty_home_prob', .35, .65),
        ('rho', -.3, .3), ('et_tempo', .5, 1.3)):
        if d.get(k) is not None and not lo <= float(d[k]) <= hi:
            err.append(f'{k} out of range [{lo},{hi}]')
    for k in ('injury_home','injury_away','attack_absence_home','attack_absence_away',
              'defense_absence_home','defense_absence_away','gk_absence_home','gk_absence_away',
              'rotation_home','rotation_away','defense_risk_home','defense_risk_away'):
        if d.get(k) is not None and not 0 <= float(d[k]) <= .5:
            err.append(k + ' out of range [0,0.5]')
    hhad = d.get('hhad')
    if hhad is not None:
        ho = hhad.get('odds') if isinstance(hhad, dict) else None
        if (not isinstance(hhad, dict) or hhad.get('line') is None or
            not isinstance(ho, list) or len(ho) != 3 or any(not isinstance(x,(int,float)) or x <= 1 for x in ho)):
            err.append('hhad must be {line:number, odds:[home,draw,away] >1}')
    ouv=d.get('ou')
    if ouv is not None:
        oo=ouv.get('odds') if isinstance(ouv,dict) else None
        if not isinstance(ouv,dict) or ouv.get('line') is None or not isinstance(oo,list) or len(oo)!=2 or any(not isinstance(x,(int,float)) or x<=1 for x in oo):err.append('ou must be {line:number, odds:[over,under] >1}')
    ttg=d.get('ttg')
    if ttg is not None:
        to=ttg.get('odds') if isinstance(ttg,dict) else None
        if not isinstance(to,list) or len(to)!=8 or any(not isinstance(x,(int,float)) or x<=1 for x in to):err.append('ttg.odds must contain 8 odds for 0,1,2,3,4,5,6,7+')
    return miss, err


# [中文功能] 计算输入完整度/来源/新鲜度质量分
def quality(d):
    """Input coverage/source/freshness; freshness is derived from timestamps."""
    rec = ['odds', 'elo_home', 'elo_away', 'lambda_home', 'lambda_away', 'first_leg',
           'predicted_starters_known', 'injury_home', 'injury_away', 'weather_ok']
    comp = round(sum(k in d for k in rec) / len(rec) * 100, 1)
    meta = d.get('field_meta') or {}
    rel = round(sum(float(x.get('reliability', 60)) for x in meta.values()) / len(meta), 1) if meta else 55.0
    # Prefer the audited timestamp-derived freshness from market_fit. The
    # collector's static freshness=100 is not trusted as a live age signal.
    try:
        from market_fit import market_freshness as _market_freshness
        fm = _market_freshness(d)
        factors = [float(v.get('factor', 0.0)) * 100 for v in fm.values()
                   if v.get('status') != 'UNKNOWN']
        fresh = round(sum(factors) / len(factors), 1) if factors else 0.0
    except Exception:
        fresh = 0.0 if meta else 55.0
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

# [中文功能] 双回合晋级路径模拟（90分钟/加时/点球）
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

# [中文功能] 在基础λ上应用伤停/战意/环境等事实修正
def apply_fact_adjustments(d, lh, la):
    """Apply independent fact adjustments on top of base lambdas.

    Used by both the heuristic lambda builder and multi_market_fit so injury /
    motive / home_adv are never silently dropped on the multi-fit path.
    """
    tags = []
    lh *= math.exp(float(d.get('home_adv', 0)))
    la *= math.exp(-float(d.get('home_adv', 0)) * .55)
    # 攻防分离的缺阵冲击
    atk_h = clamp(float(d.get('attack_absence_home', d.get('injury_home', 0))), 0, .5)
    atk_a = clamp(float(d.get('attack_absence_away', d.get('injury_away', 0))), 0, .5)
    def_h = clamp(float(d.get('defense_absence_home', 0)) + float(d.get('gk_absence_home', 0)), 0, .5)
    def_a = clamp(float(d.get('defense_absence_away', 0)) + float(d.get('gk_absence_away', 0)), 0, .5)
    lh *= 1 - atk_h
    la *= 1 - atk_a
    la *= 1 + def_h
    lh *= 1 + def_a
    if atk_h or atk_a or def_h or def_a:
        tags.append('INJURY_ADJUSTED')

    # 轮换：主要削弱本方进攻，并略微增加被对手打穿风险。
    # 系数 UNFITTED，先保证字段真正进主路径，再用回测标定。
    rot_h = clamp(float(d.get('rotation_home', 0)), 0, .5)
    rot_a = clamp(float(d.get('rotation_away', 0)), 0, .5)
    if rot_h or rot_a:
        lh *= (1 - 0.70 * rot_h)
        la *= (1 - 0.70 * rot_a)
        # 本方轮换后防线不稳，给对手小幅进攻增益
        la *= (1 + 0.25 * rot_h)
        lh *= (1 + 0.25 * rot_a)
        tags.append('ROTATION_ADJUSTED')

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
    if amh != 1 or ama != 1 or rh or ra:
        tags.append('MOTIVE_ADJUSTED')
    if float(d.get('home_adv', 0)) != 0:
        tags.append('HOME_ADV_ADJUSTED')
    return clamp(lh, .05, 6), clamp(la, .05, 6), tags


# [中文功能] 综合市场/Elo/显式λ构建最终λ对
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
    if sw <= 0:
        # [FIX 2026-08-02] 无任何可用锚（市场被新鲜度剔除且无 Elo/显式λ/多市场池）：
        # 此前对空 pairs 求和除零（ZeroDivisionError），现回退到中性全局总进球拆分并打标，
        # 交给下游按 AVOID_DATA_RISK/UNFITTED 处理，而不是让调用方看到裸异常。
        lh = la = GOAL_TOTAL_FALLBACK / 2
        tags.append('NO_ANCHOR_FALLBACK')
        return clamp(lh, .05, 6), clamp(la, .05, 6), tags
    lh = sum(x[0] * x[2] for x in pairs) / sw
    la = sum(x[1] * x[2] for x in pairs) / sw
    lh, la, adj_tags = apply_fact_adjustments(d, lh, la)
    tags += adj_tags
    return lh, la, tags


# [中文功能] λ±10%扰动下的概率敏感性传导
def sensitivity(lh, la, rho, mw, market, mode, ah_line=None):
    """λ±10%不确定性传导。market_only的1X2固定，但比分衍生市场仍会波动。"""
    lo, hi = 1-SENSITIVITY_DELTA, 1+SENSITIVITY_DELTA
    outs=[]; overs=[]; bty=[]; covers=[]; top1=[]
    for fh in (lo,1.0,hi):
        for fa in (lo,1.0,hi):
            mm=matrix(lh*fh,la*fa,rho); pure=one(mm)
            final = market if mode=='market_only' else ([mw*market[i]+(1-mw)*pure[i] for i in range(3)] if market else pure)
            outs.append(final); overs.append(ou(mm,2.5)['over_pct']); bty.append(sum(v for (i,j),v in mm.items() if i>0 and j>0)*100)
            if ah_line is None:
                covers.append(0.0)
            else:
                aa=ah(mm,float(ah_line)); covers.append(aa['full_win_pct']+.5*aa['half_win_pct'])
            top1.append(top(mm,1)[0]['score'])
    r={'lambda_perturbation_pct':round(SENSITIVITY_DELTA*100,1),
       'one_x_two_status':'FIXED_TO_MARKET' if mode=='market_only' else 'LAMBDA_SENSITIVE',
       'home_range_pct':[round(min(o[0] for o in outs)*100,1),round(max(o[0] for o in outs)*100,1)],
       'draw_range_pct':[round(min(o[1] for o in outs)*100,1),round(max(o[1] for o in outs)*100,1)],
       'away_range_pct':[round(min(o[2] for o in outs)*100,1),round(max(o[2] for o in outs)*100,1)],
       'over_2_5_range_pct':[round(min(overs),1),round(max(overs),1)],
       'btts_yes_range_pct':[round(min(bty),1),round(max(bty),1)],
       'ah_effective_cover_range_pct':(None if ah_line is None else [round(min(covers),1),round(max(covers),1)]),
       'top1_score_candidates':sorted(set(top1)),
       'note':'这不是统计置信区间。market_only的最终1X2固定为市场，但比分/O-U/BTTS/AH仍随λ波动。无无显式ah_line时不输出亚洲盘敏感性。'}
    return r


# [中文功能] 单场预测主函数（校验→建模→输出）
def predict(d):
    miss, err = validate(d)
    if err:
        return {'status': 'invalid', 'errors': err, 'missing': miss}
    if miss:
        return {'status': 'incomplete', 'missing': miss}

    devig_method = selected_devig_method(d)
    market = margin = None
    if d.get('odds'):
        market, margin = devig(d['odds'], devig_method)

    explicit = d.get('lambda_home') is not None and d.get('lambda_away') is not None
    elo = d.get('elo_home') is not None and d.get('elo_away') is not None
    requested_mode = d.get('mode')
    mode = requested_mode or ('model_first' if explicit
                              else ('hybrid' if market and elo
                                    else ('market_only' if market else 'model_first')))

    total, total_src = resolve_goal_total(d)
    rho = float(d.get('rho', RHO_DEFAULT))
    multi_fit = None
    # A stale/unknown HAD observation cannot remain the final market anchor.
    # The freshness module uses Beijing time for Sporttery timestamps.
    market_freshness_meta = None
    try:
        from market_fit import market_freshness as _market_freshness
        market_freshness_meta = _market_freshness(d)
    except Exception:
        market_freshness_meta = None
    had_freshness = (market_freshness_meta or {}).get('had') or {}
    had_usable = bool(d.get('odds')) and had_freshness.get('status') not in ('STALE', 'OUTDATED', 'UNKNOWN')
    if market and not had_usable:
        flags_pre = list(d.get('assumptions') or [])
        flags_pre.append('HAD_MARKET_ANCHOR_STALE_OR_UNKNOWN: 最终1X2不将陈旧/未知时间HAD作为新鲜市场锚。')
        if mode == 'market_only':
            return {
                'status': 'market_anchor_unusable',
                'schema_version': '3.3',
                'engine_version': ENGINE_VERSION,
                'match': f"{d['home']} vs {d['away']}",
                'mode': 'market_only',
                'requested_mode': requested_mode,
                'market_freshness': market_freshness_meta,
                'market_prob_pct': [round(x * 100, 1) for x in market],
                'bookmaker_margin_pct': round(margin * 100, 1),
                'errors': ['market_only requires a fresh or aging HAD market anchor; refusing silent model_first fallback'],
                'assumptions': flags_pre,
            }
        market = None
    if fit_multi_market and (market or d.get('hhad') or d.get('ou') or d.get('ttg')
                              or d.get('hafu') or d.get('lambda_prior')):
        # If HAD is stale, it has been removed from `market`; other timestamped
        # pools may still provide a model-first multi-market fit.
        fit_data = dict(d)
        if not market:
            fit_data.pop('odds', None)
        # [FIX 2026-08-02] model_first 语义：显式 λ（xG/DC 等独立强度）必须以强权重
        # 进入多市场拟合目标，市场只作校准/对照——此前显式 λ 被多市场路径整体忽略。
        if mode == 'model_first' and explicit:
            fit_data['lambda_prior'] = {
                'lambda_home': float(d['lambda_home']),
                'lambda_away': float(d['lambda_away']),
                'weight': W_EXPLICIT,
                'source': 'explicit_model_first',
                'sample_legs': None,
            }
        # Remove pools whose timestamp audit gives zero effective weight;
        # retaining them would create a zero-loss arbitrary fit.
        for pool_name, input_key in [('hhad', 'hhad'), ('ou', 'ou'),
                                     ('ttg', 'ttg'), ('hafu', 'hafu')]:
            if (market_freshness_meta or {}).get(pool_name, {}).get('factor', 0.0) <= 0:
                fit_data.pop(input_key, None)
        if not any(fit_data.get(k) for k in ('odds', 'hhad', 'ou', 'ttg', 'hafu', 'lambda_prior')):
            multi_fit = None
        else:
            multi_fit = fit_multi_market(fit_data, matrix, one, rho)
    # [FIX 2026-08-02] 全盘口过期/未知时 multi_fit 可能为 None：
    # 此前无条件解包 multi_fit['lambda_home'] 抛 TypeError，现改为 None 时走 build_lambdas 兜底。
    if multi_fit is not None:
        lh, la = multi_fit['lambda_home'], multi_fit['lambda_away']
        tags = ['MULTI_MARKET_XG']
        if mode == 'model_first' and explicit:
            tags.append('EXPLICIT_XG_PRIOR')
        if fit_data.get('lambda_prior'):
            tags.append('PRIOR_CONSTRAINED')
        # 事实修正必须作用在 multi_fit 的基准λ上；market_only 仅用盘口结构，不附加独立事实修正。
        if mode != 'market_only':
            lh, la, adj_tags = apply_fact_adjustments(d, lh, la)
            tags += adj_tags
        # multi_fit λ 已由盘口联合拟合得到，不得再打 PROXY_XG（那是启发式 market_lam 路径标签）。
    else:
        lh, la, tags = build_lambdas(d, total, market, elo, explicit, mode)
    # 无独立锚不得把中性 λ=1.23/1.23 写成生产 1X2（43 场低依赖审计：36 场是这条回退）。
    # 有可用市场就钉回 market_only；没有可用市场就拒绝，不输出 37.4/25.3/37.4。
    forced_market_from_no_anchor = False
    if "NO_ANCHOR_FALLBACK" in tags:
        if market:
            mode = "market_only"
            forced_market_from_no_anchor = True
        else:
            return {
                "status": "no_independent_anchor",
                "schema_version": "3.3",
                "engine_version": ENGINE_VERSION,
                "match": f"{d['home']} vs {d['away']}",
                "mode": requested_mode or mode,
                "requested_mode": requested_mode,
                "xg_tags": tags,
                "errors": [
                    "NO_ANCHOR_FALLBACK cannot be used as production 1X2; "
                    "need paired Elo/lambda or a usable HAD"
                ],
            }
    m = matrix(lh, la, rho)
    pure = one(m)

    # market_only 的多盘口拟合只负责衍生市场结构，不能把异常λ传播到比分/O-U/BTTS。
    # 一旦联合拟合触发极端λ/零封审计，退回到HAD三项直接反解的λ；1X2仍固定为市场。
    lambda_guard = None
    fitted_lambda_audit = audit_lambda_and_clean_sheet(lh, la, m)
    fitted_severe = [
        flag for flag in fitted_lambda_audit['flags']
        if flag.startswith(('EXTREME_LAMBDA_ASYMMETRY', 'EXTREME_CLEAN_SHEET'))
    ]
    if mode == 'market_only' and market and multi_fit and fitted_severe:
        had_lambda = solve_lam_from_probs(market)
        if had_lambda is not None:
            rejected_lambda = [round(lh, 3), round(la, 3)]
            lh, la = had_lambda
            m = matrix(lh, la, rho)
            pure = one(m)
            tags.append('EXTREME_LAMBDA_FALLBACK_TO_HAD')
            lambda_guard = {
                'triggered': True,
                'action': 'fallback_to_had_inverse',
                'rejected_lambda': rejected_lambda,
                'rejected_flags': fitted_severe,
                'fallback_lambda': [round(lh, 3), round(la, 3)],
                'note': 'market_only联合拟合异常；衍生市场改用HAD直接反解λ，禁止传播极端拟合。',
            }

    market_solver_used = bool(market and (not multi_fit) and 'PROXY_XG' in tags and solve_lam_from_probs(market) is not None)
    # goal_total 只在启发式回退路径真正参与 λ 求解：
    # multi_market_fit 直接由 HAD/HHAD/O-U/TTG 赔率拟合，inverse_1x2 由 HAD 三项反解，两者都不吃 goal_total。
    goal_total_used = not (multi_fit or market_solver_used)

    flags = []
    if forced_market_from_no_anchor:
        flags.append(
            "NO_ANCHOR_FORCE_MARKET: 无独立强度锚，禁止 model_first 无锚 1X2；已钉回 market_only。"
        )
    lambda_audit = audit_lambda_and_clean_sheet(lh, la, m)
    if lambda_guard:
        flags.append(
            'EXTREME_LAMBDA_FALLBACK_TO_HAD: multi-market λ='
            f"{lambda_guard['rejected_lambda']}触发极端审计，已回退HAD反解λ="
            f"{lambda_guard['fallback_lambda']}；比分及衍生市场按回退结果计算。")
    flags.extend(lambda_audit['flags'])
    # 依赖度：按真实λ来源估计，不再因为误标 PROXY_XG 被抬高。
    # multi_fit 本身已是盘口拟合，基础依赖高；若叠加独立伤停/战意修正，则略降。
    independent_adj = any(t in tags for t in ('INJURY_ADJUSTED', 'MOTIVE_ADJUSTED', 'HOME_ADV_ADJUSTED', 'ELO_XG', 'EXPLICIT_XG'))
    if mode == 'market_only':
        final, mw, edge, dep = market, 1, None, 100
    elif market:
        mw = float(d.get('market_weight', .4 if mode == 'model_first' else .5))
        final = [mw * market[i] + (1 - mw) * pure[i] for i in range(3)]
        edge = {k: round((final[i] - market[i]) * 100, 1)
                for i, k in enumerate(('home_pp', 'draw_pp', 'away_pp'))}
        if multi_fit:
            dep = round(max(0.0, min(100.0, mw * 100 + (10 if not independent_adj else -5))), 1)
        elif 'PROXY_XG' in tags:
            dep = round((W_MARKET) * (1 - mw) * 100 + mw * 100, 1)
        else:
            dep = round(mw * 100, 1)
        if 'PROXY_XG' in tags and not multi_fit:
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

    # ---- 1X2 校准层 [FITTED]：平局修正 + 温度缩放（联赛感知参数）----
    final_uncal = list(final)
    if d.get('calibration', True) is False:
        calibration_out = {'applied': False, 'reason': '用户以 calibration=false 显式关闭'}
    else:
        cal_params = league_calibration(d)
        final = calibrate_1x2(final_uncal,
                              draw_k=cal_params['draw_k'],
                              temperature=cal_params['temperature'])
        shift = [round((final[i] - final_uncal[i]) * 100, 2) for i in range(3)]
        calibration_out = {
            'applied': True,
            'method': 'draw_multiplier + temperature_scaling',
            'league_key': cal_params['key'],
            'league_basis': cal_params['basis'],
            'draw_k': cal_params['draw_k'],
            'temperature': cal_params['temperature'],
            'fitted_on': cal_params['basis'],
            'uncalibrated_pct': [round(x * 100, 1) for x in final_uncal],
            'shift_pp': {'home': shift[0], 'draw': shift[1], 'away': shift[2]},
            'test_set_effect': {'brier': '0.18657→0.18644', 'log_loss': '0.94512→0.94413',
                                'ece': '0.04697→0.03456', 'argmax_hit_pct': '55.80→55.31'},
            'note': ('校准改善的是概率数值可信度（ECE降26.4%），不是命中率。'
                     'argmax命中率基本不变甚至略降——不要期待它让你多猜中比赛。'
                     '五大联赛(顶级)已按2026-08-02 football-data 46696场验证切换参数；'
                     '芬超/瑞超/巴西甲(含巴西杯代理)已按Pinnacle收盘分联赛拟合(2026-08-02)；'
                     '其余联赛沿用体彩默认参数。')}
        # 校准后重算 edge（edge 必须相对同一基准）
        if edge is not None and market:
            edge = {k: round((final[i] - market[i]) * 100, 1)
                    for i, k in enumerate(('home_pp', 'draw_pp', 'away_pp'))}

    _pmax = max(final)
    _s, _slab, _shit, _sn = star_rating(_pmax)
    _pick = ('主胜', '平局', '客胜')[final.index(_pmax)]
    confidence_out = {
        'stars': _s, 'label': _slab, 'pick': _pick,
        'pick_prob_pct': round(_pmax * 100, 1),
        'band_observed_hit_pct': _shit, 'band_sample_n': _sn,
        'basis': '按 final_1x2 最大概率落入的已拟合星级区间',
        'note': (f'★={_s}：该档在405场测试集中实测命中 {_shit}%（n={_sn}）。'
                 '星级只是最大概率的分档标签，不是独立信息；'
                 '概率百分比才是完整输出，星级不可替代概率。')}
    if _sn < 100:
        confidence_out['warning'] = f'该星级档测试样本仅 {_sn} 场，实测命中率本身有较大不确定性。'

    if dep >= 70:
        flags.append(f'HIGH_MARKET_DEPENDENCY: 市场依赖度 {dep}%，本次输出主要在复述盘口。')
    if 'ELO_XG' in tags and float(d.get('elo_home_adv', ELO_HOME_ADV_DEFAULT)) != 0 and float(d.get('home_adv',0)) != 0:
        if not d.get('extra_environment_confirmed') or not d.get('home_adv_reason'):
            flags.append('DOUBLE_HOME_ADV: Elo主场加成与home_adv同时启用且缺少额外环境确认，可能重复计权。')
    if mode == 'market_only' and not multi_fit:
        flags.append('DERIVED_FROM_1X2_ONLY: 比分、O/U、BTTS与AH由HAD的1X2反解λ推导，未受O/U、TTG或真实xG约束，必须降级解读。')
    if multi_fit and lambda_guard:
        flags.append('MULTI_MARKET_FIT_REJECTED: 联合拟合结果仅保留诊断，不用于最终λ和衍生市场。')
    elif multi_fit:
        flags.append('MULTI_MARKET_FIT: λ已由'+','.join(multi_fit['sources'])+'联合拟合；仍需用独立历史样本验证比分与衍生市场校准。')
    if d.get('hhad') is None and d.get('hhad_note'):
        flags.append('HHAD_NOT_MODELED: 仅有文字化HHAD信息，未输入结构化hhad，未进入脚本审计。')
    if total_src == 'global_fallback' and goal_total_used:
        flags.append(
            f'GOAL_TOTAL_FALLBACK: 未提供 goal_total，也未匹配到赛事默认值，'
            f'使用全局兜底 {GOAL_TOTAL_FALLBACK}，且本次 λ 确实由它推导。建议显式提供以提升准确度。')
    flags.append('DEVIG_METHOD: 使用'+devig_method+'去水；不同方法须按时间切分回测，不能默认视为更准。')
    flags.append('PARTIALLY_FITTED_CONSTANTS: 拟合状态按盘口区分，见 derived_market_status 字段。'
                 '已拟合/已验证：1X2校准层、星级区间、O/U2.5、O/U3.5、BTTS(验证后不校准)、'
                 'rho、FIRST_HALF_SHARE、比分模型(双变量泊松λ3=0.20；Top比分展示T=1.30)。'
                 '仍未独立拟合：亚洲盘、晋级/加时/点球、半场1X2聚合。'
                 '未拟合项的绝对概率仅可用于相对比较。')
    flags.append('DRAW_ARGMAX_RARE: 平局几乎不会成为三项中的最大概率——'
                 '1348场实测市场把平局列为最大概率仅 6/1348(0.4%)，实际平局率却有 27.3%。'
                 '这是三分类概率结构的固有性质，不是模型缺陷。'
                 '因此「按最大概率打单」会系统性漏掉全部平局；'
                 '要覆盖平局必须用双选(如主胜/平)或让球盘，不能靠调高平局概率解决。')

    # 衍生市场矩阵：双变量泊松（1X2 路径仍用 DC 矩阵 m，保证无损复现市场不受影响）
    m_derived = bp_matrix(lh, la, SCORE_LAMBDA3) if SCORE_MODEL == 'bp' else m
    bt = sum(v for (i, j), v in m_derived.items() if i > 0 and j > 0)
    ht = matrix(lh * FIRST_HALF_SHARE, la * FIRST_HALF_SHARE, rho / 2, 6)
    # 比分分布温度校准（仅用于 top_scores / ht_top_scores，不影响 1X2/O-U/BTTS/HHAD/AH）
    m_score = temperature_scale(m_derived, SCORE_TEMPERATURE_FT)
    ht_score = temperature_scale(ht, SCORE_TEMPERATURE_HT)

    # TTG 与比分矩阵一致性：总进球盘口是比分矩阵按 i+j 聚合后的边际约束。
    # Top1 本身可能仍是低比分（单个格子的众数），不能仅凭它判断“大/小球矛盾”；
    # 应比较完整矩阵的总进球分布和 TTG 去水分布。
    ttg_consistency = None
    if d.get('ttg'):
        ttg_odds = d['ttg']['odds']
        ttg_market, ttg_margin = devig(ttg_odds, devig_method)
        ttg_model = [0.0] * 8
        for (i, j), v in m_derived.items():
            ttg_model[min(i + j, 7)] += v
        ttg_mae = sum(abs(ttg_model[k] - ttg_market[k]) for k in range(8)) / 8 * 100
        market_over = sum(ttg_market[3:]) * 100
        model_over = sum(ttg_model[3:]) * 100
        ttg_consistency = {
            'market_prob_pct': [round(x * 100, 1) for x in ttg_market],
            'model_prob_pct': [round(x * 100, 1) for x in ttg_model],
            'market_over_2_5_pct': round(market_over, 1),
            'model_over_2_5_pct': round(model_over, 1),
            'over_2_5_gap_pp': round(model_over - market_over, 1),
            'mae_pp_8_bands': round(ttg_mae, 1),
            'bookmaker_margin_pct': round(ttg_margin * 100, 1),
            'interpretation': '比分矩阵按总进球聚合后与TTG比较；单个Top比分不代表总进球众数。'
        }
        if abs(model_over - market_over) >= 5 or ttg_mae >= 3:
            flags.append(f'TTG_SCORE_CONFLICT: 比分矩阵大2.5与TTG相差 {round(model_over-market_over,1)}pp，8档MAE {round(ttg_mae,1)}pp；Top比分与大小球结构须降级解读。')

    # 精确比分Top1与大小球是两个不同聚合层级：补充分侧Top，避免读者误以为矛盾。
    score_rows = sorted(m_derived.items(), key=lambda kv: kv[1], reverse=True)
    top_over = next(((f'{i}-{j}', round(v * 100, 2)) for (i, j), v in score_rows if i + j >= 3), None)
    top_under = next(((f'{i}-{j}', round(v * 100, 2)) for (i, j), v in score_rows if i + j <= 2), None)
    over25 = ou(m_derived, 2.5)['over_pct']
    if over25 >= 55 and top_over and top(m, int(d.get('top_n', 8)))[0]['score'].split('-'):
        top_total = sum(map(int, top(m, 1)[0]['score'].split('-')))
        if top_total <= 2:
            flags.append('OVER_DISTRIBUTED_ACROSS_SCORES: 大2.5概率过半但Top1为小比分，大球概率由多个比分合计贡献；请同时查看大球侧Top比分。')
    if 45 <= over25 <= 55:
        relation = 'OU_UNCERTAIN'
    elif over25 >= 55 and top_over and top(m, 1)[0]['score'] == top_over[0]:
        relation = 'OVER_ALIGNED_WITH_TOP_SCORE'
    elif over25 >= 50 and top_over:
        relation = 'OVER_DISTRIBUTED_ACROSS_SCORES'
    else:
        relation = 'UNDER_ALIGNED_OR_DISTRIBUTED'
    score_market_consistency = {
        'over_2_5_pct': over25, 'under_2_5_pct': round(100 - over25, 1),
        'top_score': top(m_derived, 1)[0], 'top_over_score': top_over,
        'top_under_score': top_under, 'relation': relation,
        'note': 'Top比分是单格众数；大小球是总进球分布聚合，方向不一致不代表计算矛盾。'
    }

    implied_total = lh + la
    hafu_model = None
    if _hafu_probs is not None and d.get('hafu') is not None:
        try:
            hp = _hafu_probs(lh, la, matrix, rho)
            hafu_model = {'prob_pct': [round(x * 100, 1) for x in hp],
                          'state_labels': ['HH','HD','HA','DH','DD','DA','AH','AD','AA'],
                          'source_type': 'jointly_fitted_or_derived',
                          'calibration_status': 'UNFITTED'}
        except Exception:
            hafu_model = None
    hhad_out = None
    if d.get('hhad'):
        hhad_out = hhad_three_way(m_derived, d['hhad']['line'], d['hhad']['odds'], devig_method)
        if hhad_out.get('mae_pp',0) >= 8:
            flags.append(f"HHAD_CONFLICT: 比分矩阵与官方HHAD平均偏差 {hhad_out['mae_pp']}pp，比分/大小球结构不可信，需联合拟合TTG/O-U。")
    out = {
        'status': 'ok',
        'schema_version': '3.3',
        'engine_version': ENGINE_VERSION,
        'match': f"{d['home']} vs {d['away']}",
        'mode': mode,
        'quality': quality(d),
        'goal_total_input': {'value': total, 'source': total_src,
                             'used_by_lambda_solver': goal_total_used,
                             'note': ('goal_total 未参与 λ 求解——λ 由赔率直接拟合/反解，'
                                      '填写或改动 goal_total 不会改变本次结果。')
                                     if not goal_total_used else
                                     'goal_total 参与了 λ 求解，其取值会影响比分与总进球类输出。'},
        'implied_goal_total': round(implied_total,3),
        'lambda_solver': ('had_inverse_extreme_guard' if lambda_guard else ('multi_market_fit' if multi_fit else ('inverse_1x2' if market_solver_used else ('explicit_or_elo' if not market else 'heuristic_fallback')))),
        'multi_market_fit': multi_fit,
        'lambda_guard': lambda_guard,
        'market_dependency_pct': dep,
        'market_prob_pct': None if market is None else [round(x * 100, 1) for x in market],
        'bookmaker_margin_pct': None if margin is None else round(margin * 100, 1),
        'devig_method': devig_method,
        'devig_available_methods': ['proportional', 'additive', 'power', 'shin'],
        'model_1x2': pure,
        'final_1x2': final,
        'model_1x2_pct': [round(x * 100, 1) for x in pure],
        'final_1x2_pct': [round(x * 100, 1) for x in final],
        'final_1x2_display': {
            '主胜': f"{round(final[0]*100,1)}%",
            '平局': f"{round(final[1]*100,1)}%",
            '客胜': f"{round(final[2]*100,1)}%"},
        'calibration': calibration_out,
        'confidence': confidence_out,
        'edge_vs_market_pp': edge,
        'sensitivity': sensitivity(lh, la, rho, mw, market, mode, None if d.get('ah_line') is None else float(d.get('ah_line'))),
        'xg': [round(lh, 3), round(la, 3)],
        'lambda_audit': lambda_audit,
        'xg_tags': tags,
        'rho': rho,
        'top_scores': top(m_score, int(d.get('top_n', 8))),
        'score_matrix': {f'{i}-{j}': v for (i,j),v in m_derived.items()},
        'ht_top_scores': top(ht_score, 3),
        'score_calibration': {
            'ft_temperature': SCORE_TEMPERATURE_FT,
            'ht_temperature': SCORE_TEMPERATURE_HT,
            'status': 'FITTED-CALIBRATED',
            'basis': SCORE_CALIBRATION_BASIS,
            'note': '衍生市场（比分/O-U/BTTS/HHAD/AH/晋级）使用双变量泊松原始矩阵（λ3=0.20）；Top比分显示概率另用T=1.30缩放，1X2路径维持DC矩阵与已拟合校准层。'},
        'hafu_model': hafu_model,
        'ou_2_5': ou(m_derived, 2.5),
        'ou_3_5': ou(m_derived, 3.5),
        'ttg_score_consistency': ttg_consistency,
        'score_market_consistency': score_market_consistency,
        'btts': {'yes_pct': round(bt * 100, 1), 'no_pct': round((1 - bt) * 100, 1),
                 'calibration': {'applied': False,
                                 'reason': ('已在1348场上测试过Platt校准，测试集ECE 0.02130→0.02650 反而恶化24.4%。'
                                            'BTTS原始输出本已良好校准，故刻意不施加校准。'),
                                 'test_set_ece': 0.02130}},
        'derived_market_status': {
            'note': '各衍生盘口的拟合状态互不相同，不可一概而论。',
            'one_x_two': 'FITTED — 1348场，平局修正+温度缩放，测试集ECE 0.04697→0.03456',
            'ou_2_5': 'FITTED — Platt校准，测试集ECE 0.06470→0.04710',
            'ou_3_5': 'FITTED — Platt校准，测试集ECE 0.06196→0.03611',
            'btts': 'VALIDATED_NO_CHANGE — 已验证原始输出ECE 0.0213良好，校准无效故不施加',
            'rho_dixon_coles': 'FITTED-CONFIRMED — 测试集验证 -0.08 优于拟合值 -0.07，维持默认',
            'first_half_share': 'FITTED-CONFIRMED — 1348场实测0.444/0.450，维持0.45',
            'top_scores': 'FITTED — 体彩2026严格比赛日OOS（n=401）：BP λ3=0.20，完整比分LL 2.838031→2.812950，Top1 13.72%→13.97%，Top3 36.41%→39.40%；展示T=1.30不改变排名',
            'asian_handicap': 'UNFITTED — 由比分矩阵推导，未做独立盘口回测',
            'advancement': 'FITTED-SMALL — 点球主队概率0.38(n=24, CI 0.21-0.57)、加时倍率0.83(n=31, CI 0.63-1.02)；样本仍小，绝对概率谨慎解读',
            'hafu_half_time': 'PARTIALLY-CALIBRATED — 半场比分温度T=1.22（test ECE 0.00322→0.00067）；半场1X2聚合仍由矩阵推导，未做独立盘口回测'},
        # 无显式 ah_line 时不输出亚洲盘，避免默认 -1 与体彩 HHAD 线混淆。
        'asian_handicap_home': None if d.get('ah_line') is None else ah(m_derived, float(d.get('ah_line'))),
        'sporttery_hhad_3way': hhad_out,
        'advancement': None,
        'reliability_flags': flags,
        'assumptions': d.get('assumptions', []),
        'disclaimer': '概率模型输出，非投注建议。',
    }
    if d.get('first_leg') is not None:
        out['advancement'] = advancement(m_derived, d['first_leg'], lh, la, d, rho)
    return out


# [中文功能] 核心预测引擎CLI入口
def main():
    ap = argparse.ArgumentParser(description=f'足预大师 {ENGINE_VERSION} 预测引擎')
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

#!/usr/bin/env python3
"""HAD/HHAD/O-U/TTG/HAFU 联合拟合 λ。纯标准库网格+坐标细化。

权重依据（2026-08-01 实测各盘口去水前边际）：
    HAD 12.9%  HHAD 12.9%  TTG 25.1%  HAFU 25.5%  CRS 40.9%
边际越高的盘口噪声越大，权重应越低。3.4.1 之前 TTG 权重 1.2 高于 HAD 1.0，
与该证据矛盾，现改为按边际倒数分档。CRS 边际过高，不进拟合。
"""
import math
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 盘口权重 [UNFITTED-EVIDENCE]：按实测边际分档，尚未经回测最优化
W = {'had': 1.0, 'hhad': 0.9, 'ou': 0.8, 'ttg': 0.5, 'hafu': 0.35}
FRESH_HOURS = 6.0
HALF_FRESH_HOURS = 12.0
MAX_STALE_HOURS = 24.0


# [中文功能] 解析时间字符串（兼容Z时区后缀）
def _parse_time(value):
    if not value:
        return None
    text = str(value).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
    if dt.tzinfo is None:
        # Sporttery updateDate/updateTime are Beijing local time.
        dt = dt.replace(tzinfo=CST)
    return dt


# [中文功能] 计算各盘口相对开球时间的新鲜度
def market_freshness(data):
    """Compute auditable pool age relative to kickoff; no timestamp means unknown."""
    kickoff = _parse_time(data.get('kickoff'))
    meta = data.get('field_meta') or {}
    result = {}
    for pool, field in [('had', 'odds'), ('hhad', 'hhad'), ('ou', 'ou'),
                        ('ttg', 'ttg'), ('hafu', 'hafu'), ('crs', 'crs')]:
        item = meta.get(field) or {}
        observed = _parse_time(item.get('observed_at'))
        if not observed or not kickoff:
            # Unknown age is not fresh. Keep the observation auditable but do
            # not let an untimestamped pool receive full production weight.
            result[pool] = {'status': 'UNKNOWN', 'factor': 0.0, 'age_hours': None,
                            'observed_at': item.get('observed_at')}
            continue
        age = max(0.0, (kickoff - observed).total_seconds() / 3600.0)
        if age <= FRESH_HOURS:
            status, factor = 'FRESH', 1.0
        elif age <= HALF_FRESH_HOURS:
            status, factor = 'AGING', 0.5
        elif age <= MAX_STALE_HOURS:
            status, factor = 'STALE', 0.15
        else:
            status, factor = 'OUTDATED', 0.0
        result[pool] = {'status': status, 'factor': factor,
                        'age_hours': round(age, 3),
                        'observed_at': item.get('observed_at')}
    return result


# [中文功能] 合并默认与输入的市场权重
def effective_market_weights(data):
    weights = dict(W)
    weights.update(data.get('market_weights') or {})
    freshness = market_freshness(data)
    for pool, item in freshness.items():
        if pool in weights:
            weights[pool] *= float(item.get('factor', 1.0))
    return weights, freshness
# 半场进球占比：与 predict.FIRST_HALF_SHARE 是同一个量，从那里导入避免两处定义漂移
try:
    from predict import FIRST_HALF_SHARE as HALF_SHARE
except ImportError:  # 独立调用 market_fit 时的兜底
    HALF_SHARE = 0.45

# 前瞻λ先验的软约束权重 [UNFITTED]
# 盘口项是概率平方差（典型 0.002~0.005），先验项是相对偏差平方（典型 0.15），
# 量级差约100倍。实测权重响应（六场韩职）：
#     0.006 → λ平均位移0.010，盘口loss 0.00343（几乎无感）
#     0.020 → λ平均位移0.025，盘口loss 0.00364（+7%，轻推）   ← 默认
#     0.050 → λ平均位移0.049，盘口loss 0.00433（+27%）
#     0.150 → λ平均位移0.090，盘口loss 0.00740（+117%，明显牺牲市场拟合）
# 取 0.02：λ 有可见位移但盘口拟合代价仅 +7%，符合"市场主导、历史修正"的定位。
# 调大 → 更信球队历史统计；调小 → 更信盘口。最优值须回测确定。
W_PRIOR = 0.02
# [UNFITTED] 相对偏差分母下限，避免小λ时惩罚被放大。0.3 无实证依据。
PRIOR_FLOOR = 0.3


try:
    from odds_methods import devig as _devig_method
except ImportError:
    _devig_method = None


# [中文功能] 赔率去水（按选定方法）
def devig(o, method='proportional'):
    if _devig_method is not None:
        return _devig_method(o, method)
    q = [1/float(x) for x in o]; s = sum(q)
    return [x/s for x in q], s-1


# [中文功能] 读取输入指定的去水方法（默认 power，与 predict.DEVIG_METHOD_DEFAULT 对齐，2026-08-02）
def selected_method(data):
    return str(data.get('devig_method') or 'power')


# [中文功能] 比分矩阵聚合成8档总进球概率
def total_probs(mat):
    out = {k: 0.0 for k in range(8)}
    for (h, a), p in mat.items(): out[min(h+a, 7)] += p
    return [out[k] for k in range(8)]


# [中文功能] 由比分矩阵计算让球后三态概率
def hhad_probs(mat, line):
    z = [0, 0, 0]
    for (h, a), p in mat.items():
        r = h-a+float(line); z[0 if r > 1e-9 else (1 if abs(r) <= 1e-9 else 2)] += p
    return z


# [中文功能] 由比分矩阵计算大小球概率
def ou_probs(mat, line):
    o = sum(p for (h, a), p in mat.items() if h+a > line)
    u = sum(p for (h, a), p in mat.items() if h+a < line)
    return [o, u]


# [中文功能] 由半全场拆λ卷积计算九宫格概率
def hafu_probs(lh, la, matrix, rho):
    """半全场九项 [hh,hd,ha,dh,dd,da,ah,ad,aa]。
    半场矩阵用 HALF_SHARE 拆λ，下半场用剩余部分，两段独立后卷积。"""
    m1 = matrix(lh*HALF_SHARE, la*HALF_SHARE, rho, 8)
    m2 = matrix(lh*(1-HALF_SHARE), la*(1-HALF_SHARE), rho, 8)
    z = [0.0]*9
    for (h1, a1), p1 in m1.items():
        i = 0 if h1 > a1 else (1 if h1 == a1 else 2)
        for (h2, a2), p2 in m2.items():
            H, A = h1+h2, a1+a2
            j = 0 if H > A else (1 if H == A else 2)
            z[i*3+j] += p1*p2
    return z


# [中文功能] 多盘口联合拟合的损失函数
def objective(lh, la, matrix, one, data, rho):
    m = matrix(lh, la, rho); loss = 0; parts = {}
    weights, freshness = effective_market_weights(data)
    method = selected_method(data)
    if data.get('odds'):
        t, _ = devig(data['odds'], method); q = one(m)
        v = sum((a-b)**2 for a, b in zip(q, t)); loss += weights['had']*v; parts['had'] = v
    hh = data.get('hhad')
    if hh:
        t, _ = devig(hh['odds'], method); q = hhad_probs(m, hh['line'])
        v = sum((a-b)**2 for a, b in zip(q, t)); loss += weights['hhad']*v; parts['hhad'] = v
    ou = data.get('ou')
    if ou:
        t, _ = devig(ou['odds'], method); q = ou_probs(m, float(ou.get('line', 2.5)))
        v = sum((a-b)**2 for a, b in zip(q, t)); loss += weights['ou']*v; parts['ou'] = v
    ttg = data.get('ttg')
    if ttg:
        t, _ = devig(ttg.get('odds'), method); q = total_probs(m)
        v = sum((a-b)**2 for a, b in zip(q, t)); loss += weights['ttg']*v; parts['ttg'] = v
    hf = data.get('hafu')
    if hf:
        odds = hf.get('odds') if isinstance(hf, dict) else hf
        if odds and len(odds) == 9:
            t, _ = devig(odds, method); q = hafu_probs(lh, la, matrix, rho)
            v = sum((a-b)**2 for a, b in zip(q, t)); loss += weights['hafu']*v; parts['hafu'] = v
    # 前瞻λ先验：软约束，让拟合结果不要离球队历史攻防均值太远
    pr = data.get('lambda_prior')
    if pr:
        ph, pa = float(pr.get('lambda_home')), float(pr.get('lambda_away'))
        w = float(pr.get('weight', W_PRIOR))
        v = ((lh-ph)/max(ph, PRIOR_FLOOR))**2 + ((la-pa)/max(pa, PRIOR_FLOOR))**2
        loss += w*v; parts['prior'] = v
    return loss, parts


# [中文功能] 多市场联合拟合λ（HAD+HHAD/O-U/TTG/HAFU）
def fit(data, matrix, one, rho=-.08):
    """至少HAD，附加HHAD/O-U/TTG/HAFU。返回可复现拟合结果。"""
    weights, freshness = effective_market_weights(data)
    best = (1e9, 1.3, 1.1, {})
    for ih in range(10, 81):
        lh = ih*.05
        for ia in range(5, 61):
            la = ia*.05; l, parts = objective(lh, la, matrix, one, data, rho)
            if l < best[0]: best = (l, lh, la, parts)
    _, bh, ba, _ = best
    for step in (.02, .01, .005):
        cur = best
        for dh in range(-5, 6):
            for da in range(-5, 6):
                lh = max(.05, bh+dh*step); la = max(.05, ba+da*step)
                l, parts = objective(lh, la, matrix, one, data, rho)
                if l < cur[0]: cur = (l, lh, la, parts)
        best = cur; _, bh, ba, _ = best
    sources = ['HAD']+[x for x, k in [('HHAD', 'hhad'), ('OU', 'ou'),
                                       ('TTG', 'ttg'), ('HAFU', 'hafu')] if data.get(k)]
    pr = data.get('lambda_prior')
    if pr: sources.append('PRIOR')
    out = {'lambda_home': round(best[1], 4), 'lambda_away': round(best[2], 4),
           'loss': best[0], 'loss_parts': best[3], 'sources': sources,
           'weights': {k: (float(pr.get('weight', W_PRIOR)) if k == 'prior' else weights.get(k, W.get(k)))
                       for k in best[3]},
           'freshness': freshness,
           'method': 'grid_coordinate_v2'}
    if pr:
        out['prior'] = {'lambda_home': pr.get('lambda_home'), 'lambda_away': pr.get('lambda_away'),
                        'weight': pr.get('weight', W_PRIOR), 'source': pr.get('source'),
                        'sample_legs': pr.get('sample_legs'),
                        'pulled_pp': [round(best[1]-float(pr['lambda_home']), 3),
                                      round(best[2]-float(pr['lambda_away']), 3)]}
    return out

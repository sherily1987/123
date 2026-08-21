#!/usr/bin/env python3
"""team_strength — Dixon-Coles 团队强度模型（时间衰减，R1①）。

数据：football-data 五大联赛 46696 场（含 1X2 赔率与全场比分）。
模型：λ_home = exp(home_adv + α_home + β_away)，λ_away = exp(α_away + β_home)；
目标：时间衰减加权的泊松对数似然 + Dixon-Coles τ 修正（ρ=-0.08，与引擎一致）；
权重：w = exp(-ln2·(t_max − t_match)/half_life)；
拟合：scipy L-BFGS，soft 约束 Σα≈0（拟合后重归一化）。

用途：
1) 无盘口比赛的 model_first λ（替代 Elo 启发式）；
2) 官方前瞻 λ 先验的对手强度调整；
3) 与市场 λ 对照量化分歧。
注意：仅覆盖五大联赛球队；芬超/瑞超/巴西甲等需另行按联赛拟合。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

try:
    from predict import matrix as dc_matrix, one as dc_one
except ImportError:
    dc_matrix = dc_one = None


RHO = -0.08
# 比分矩阵 Top-K 保留的 K 值（Top1/Top3/Top5 命中率的上限档位）
_SCORE_TOPK = 5
# 最近一次 load_matches 的统计，供驱动脚本读取（xg 关联缺失数等）
LAST_LOAD_STATS: dict = {}


# [中文功能] 解析日期（ISO 或 dd/mm/yy、dd/mm/yyyy）
def parse_day(value):
    if not value:
        return None
    s = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.toordinal()
        except ValueError:
            continue
    return None


# [中文功能] 加载含赔率的比赛（可选按日期截止）
# [中文功能] 球队身份主键：优先用供应商 team_id，退回队名
def team_key(row, side):
    """返回稳定的球队主键。

    供应商队名会跨赛季改写（实测同一 team_id 出现 "Manchester United" /
    "Man Utd" / "Manchester Utd" 三种写法），用队名当主键会把一支队拆成多个
    身份：评分被稀释，改名发生在测试期时整队直接判为 UNFITTED_TEAM。
    因此有 ``<side>_id`` 时一律以它为准，``id:`` 前缀避免与真实队名相撞。
    无 id 的数据源（football-data.co.uk 等）退回队名，行为与改动前一致。
    """
    tid = row.get(f"{side}_id")
    if tid not in (None, ""):
        return f"id:{tid}"
    return row.get(side)


def load_matches(jsonl_path, train_until=None, league_id=None, require_odds=True, xg_input=None):
    # target=xg 时用代理 xG 顶替进球数。任一侧缺 xg 的场次直接跳过并计数，
    # 不用 0 或均值填充——那会把"没数据"伪装成"零射门"。
    xg_by_match, xg_missing = {}, 0
    if xg_input:
        with open(xg_input, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                v = r.get("xg")
                if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
                    xg_by_match[r.get("match_id")] = [float(v[0]), float(v[1])]
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("actual") or (require_odds and not r.get("odds")):
                continue
            if league_id is not None and str(r.get("league_id")) != str(league_id):
                continue
            rf = r.get("raw_fields") or {}
            day = parse_day(r.get("kickoff")) or parse_day(rf.get("Date"))
            if day is None:
                continue
            if train_until and day > train_until:
                continue
            if xg_input:
                xg = xg_by_match.get(r.get("match_id"))
                if xg is None:
                    xg_missing += 1
                    continue
                gh, ga = xg
            else:
                gh, ga = int(r["actual"][0]), int(r["actual"][1])
            match = {
                "home": team_key(r, "home"), "away": team_key(r, "away"),
                "home_name": r.get("home"), "away_name": r.get("away"),
                "gh": gh, "ga": ga,
                "day": day, "league": str(r.get("league_id") or r.get("competition") or r.get("stage") or r.get("div") or "?"),
                "odds": [float(x) for x in r.get("odds", [])[:3]],
            }
            # 两种市场口径分开存，**不得混用**：
            #   provider_market  开赛前最后一条报价取中位数（apifootball 管线）
            #   closing_market   收盘均价去水（football-data.co.uk）——市场最强形态，更难被击败
            for field, key in (("provider_market_1x2", "provider_market"),
                               ("closing_market_1x2", "closing_market")):
                v = r.get(field)
                if isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) and x > 0 for x in v):
                    match[key] = [float(x) for x in v]
            rows.append(match)
    LAST_LOAD_STATS.update({"loaded": len(rows), "xg_missing": xg_missing,
                           "xg_input": str(xg_input) if xg_input else None})
    return rows


# [中文功能] 时间衰减权重
def decay_weights(days, half_life):
    if half_life <= 0:
        return np.ones(len(days))
    return np.exp(-np.log(2.0) * (days.max() - days) / half_life)


# [中文功能] 泊松对数似然
def pois_ll(k, lam):
    lam = np.maximum(lam, 1e-9)
    return k * np.log(lam) - lam - np.array([math.lgamma(x + 1) for x in k])


# [中文功能] DC τ 对数修正及梯度
def tau_terms(lh, la, gh, ga, rho):
    lt = np.zeros(len(lh))
    dlh = np.zeros(len(lh))
    dla = np.zeros(len(lh))
    for (i, j) in ((0, 0), (1, 0), (0, 1), (1, 1)):
        m = (gh == i) & (ga == j)
        if not m.any():
            continue
        if (i, j) == (0, 0):
            t = 1 + lh[m] * la[m] * rho
            lt[m] = np.log(np.maximum(t, 1e-9))
            dlh[m] = la[m] * rho / np.maximum(t, 1e-9)
            dla[m] = lh[m] * rho / np.maximum(t, 1e-9)
        elif (i, j) == (1, 0):
            t = 1 - la[m] * rho
            lt[m] = np.log(np.maximum(t, 1e-9))
            dla[m] = -rho / np.maximum(t, 1e-9)
        elif (i, j) == (0, 1):
            t = 1 - lh[m] * rho
            lt[m] = np.log(np.maximum(t, 1e-9))
            dlh[m] = -rho / np.maximum(t, 1e-9)
        else:
            lt[m] = math.log(max(1 + rho, 1e-9))
    return lt, dlh, dla


# [中文功能] 由样本建立主键→显示名与别名→主键的双向映射
def build_team_identity(matches):
    """返回 ``(names, aliases, ambiguous)``。

    ``names``     主键 → 最近一次出现的显示名，用于报告可读性。
    ``aliases``   显示名 → 主键，让调用方仍能用队名查询模型。
    ``ambiguous`` 同名指向多个主键的显示名 → 涉及的主键列表。

    同一主键对应多个队名是供应商改名，属正常，全部收进别名。

    同一队名指向多个主键是**真重名**（实测塞浦路斯联赛有两支 Omonia，
    id:107 与 id:2455）。此时**不建立该名字的别名**——按名字无从分辨指哪支，
    但两支球队按 team_id 仍是各自独立的实体，训练数据毫发无损。

    早期实现在此直接抛错，导致一个别名冲突中断整条多联赛管线。
    40+ 联赛规模下重名必然发生，且它并不损害按 id 主键的训练，
    故改为**丢弃该别名并记录**，既不静默合并、也不中断。
    """
    names, aliases, ambiguous = {}, {}, {}
    for m in sorted(matches, key=lambda x: x.get("day") or 0):
        for side in ("home", "away"):
            key = m[side]
            display = m.get(f"{side}_name") or key
            names[key] = display
            if display in ambiguous:
                ambiguous[display].add(key)
                continue
            if aliases.get(display, key) != key:
                ambiguous[display] = {aliases.pop(display), key}
                continue
            aliases[display] = key
    return names, aliases, {k: sorted(v) for k, v in ambiguous.items()}


# [中文功能] 按目标选 ρ：连续 xG 不适用 DC 低比分修正
def rho_for(target):
    """`tau_terms` 用 `gh == 0`、`gh == 1` 这类**整数相等判断**做 DC 修正。
    xG 是小数，这些掩码永远匹配不上，修正会**静默失效而不报错**。
    所以 target=xg 时必须显式取 0，而不是依赖它"碰巧不生效"。

    机制上也该是 0：ρ 修正的是 0-0/1-0/0-1/1-1 四个**离散比分格子**的相关性，
    对连续值没有定义。
    """
    return 0.0 if target == "xg" else RHO


# [中文功能] 构建模型对象并拟合
def fit_model(matches, half_life=500.0, penalty=1e-3, max_iter=200, target="goals"):
    rho = rho_for(target)
    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    team_names, team_aliases, ambiguous_names = build_team_identity(matches)
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.array([idx[m["home"]] for m in matches])
    ai = np.array([idx[m["away"]] for m in matches])
    gh = np.array([m["gh"] for m in matches])
    ga = np.array([m["ga"] for m in matches])
    days = np.array([m["day"] for m in matches])
    w = decay_weights(days, half_life)

    def unpack(p):
        return p[0], p[1:1 + n], p[1 + n:]

    def objective(p):
        adv, al, be = unpack(p)
        lh = np.exp(adv + al[hi] + be[ai])
        la = np.exp(al[ai] + be[hi])
        ll = w * (pois_ll(gh, lh) + pois_ll(ga, la))
        lt, _, _ = tau_terms(lh, la, gh, ga, rho)
        loss = -(ll.sum() + (w * lt).sum()) + penalty * al.sum() ** 2
        return loss

    def gradient(p):
        adv, al, be = unpack(p)
        lh = np.exp(adv + al[hi] + be[ai])
        la = np.exp(al[ai] + be[hi])
        lt, dlh, dla = tau_terms(lh, la, gh, ga, rho)
        grad = np.zeros_like(p)
        grad[0] = -(w * ((gh - lh) + dlh)).sum()
        g_alpha = np.zeros(n)
        g_beta = np.zeros(n)
        np.add.at(g_alpha, hi, -(w * ((gh - lh) + dlh)))
        np.add.at(g_alpha, ai, -(w * ((ga - la) + dla)))
        np.add.at(g_beta, ai, -(w * ((gh - lh) + dlh)))
        np.add.at(g_beta, hi, -(w * ((ga - la) + dla)))
        grad[1:1 + n] = g_alpha + 2 * penalty * al.sum()
        grad[1 + n:] = g_beta
        return grad

    p0 = np.zeros(1 + 2 * n)
    p0[0] = 0.2
    res = minimize(objective, p0, jac=gradient, method="L-BFGS-B",
                   options={"maxiter": max_iter, "ftol": 1e-8})
    adv, al, be = unpack(res.x)
    # 重归一化：Σα=0，把均值转移进 home_adv（保持 λ 不变）
    mean_al = al.mean()
    al = al - mean_al
    adv = adv + mean_al
    # 每队加权样本量与最后比赛日
    sw = np.zeros(n)
    last = np.zeros(n)
    np.add.at(sw, hi, w)
    np.add.at(sw, ai, w)
    np.maximum.at(last, hi, days)
    np.maximum.at(last, ai, days)
    return {
        "teams": teams, "home_adv": float(adv),
        "team_names": [team_names.get(t, t) for t in teams],
        "team_aliases": team_aliases,
        "ambiguous_names": ambiguous_names,
        "alpha": [float(x) for x in al], "beta": [float(x) for x in be],
        "weighted_n": [float(x) for x in sw], "last_day": [float(x) for x in last],
        "half_life": half_life, "n_matches": len(matches),
        "max_day": float(days.max()), "converged": res.success,
        "nit": int(res.nit), "fun": float(res.fun), "rho": rho, "target": target,
    }


# [中文功能] 按权重混合两套团队强度
def blend_models(model_goals, model_xg, weight):
    """`alpha = (1-w)*alpha_goals + w*alpha_xg`，beta、home_adv 同理。

    球队集合取**交集**（统计覆盖不足的队不会进 xg 模型），被丢弃的队列进
    `dropped_teams`。ρ 用进球版的值：最终输出的是离散比分，DC 修正仍然适用。
    """
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"weight 必须在 0~1（收到 {weight}）")
    idx_g, idx_x = team_index(model_goals), team_index(model_xg)
    teams = sorted(set(model_goals["teams"]) & set(model_xg["teams"]))
    dropped = sorted((set(model_goals["teams"]) | set(model_xg["teams"])) - set(teams))
    mix = lambda g, x: (1 - weight) * g + weight * x
    names_g = model_goals.get("team_names") or model_goals["teams"]
    out = {
        "teams": teams,
        "team_names": [names_g[idx_g[t]] for t in teams],
        "team_aliases": {a: k for a, k in (model_goals.get("team_aliases") or {}).items() if k in set(teams)},
        "home_adv": mix(model_goals["home_adv"], model_xg["home_adv"]),
        "alpha": [mix(model_goals["alpha"][idx_g[t]], model_xg["alpha"][idx_x[t]]) for t in teams],
        "beta": [mix(model_goals["beta"][idx_g[t]], model_xg["beta"][idx_x[t]]) for t in teams],
        "weighted_n": [model_goals.get("weighted_n", [0] * len(idx_g))[idx_g[t]] for t in teams],
        "rho": model_goals.get("rho", RHO), "target": "blend", "blend_weight": weight,
        "dropped_teams": dropped, "lifecycle": "production",
    }
    return out


# [中文功能] 主键与队名都能命中的球队索引
def team_index(model):
    """主键 → 下标，并把别名（历史队名）指向同一下标。

    旧模型文件没有 ``team_aliases``，此时退化为纯主键查找，与改动前一致。
    """
    idx = {t: i for i, t in enumerate(model["teams"])}
    for alias, key in (model.get("team_aliases") or {}).items():
        if key in idx:
            idx.setdefault(alias, idx[key])
    return idx


# [中文功能] 用已拟合模型预测一场（无盘口 model_first λ + 1X2）
def predict_match(model, home, away, day=None):
    idx = team_index(model)
    i, j = idx.get(home), idx.get(away)
    if i is None or j is None:
        return {"status": "UNFITTED_TEAM", "note": "球队不在拟合覆盖内（五大联赛外或无记录）"}
    names = model.get("team_names") or model["teams"]
    home, away = names[i], names[j]
    lh = math.exp(model["home_adv"] + model["alpha"][i] + model["beta"][j])
    la = math.exp(model["alpha"][j] + model["beta"][i])
    probs = None
    if dc_matrix is not None:
        probs = dc_one(dc_matrix(lh, la, RHO))
    return {
        "status": "VALID", "home": home, "away": away,
        "lambda_home": round(lh, 4), "lambda_away": round(la, 4),
        "home_adv": round(model["home_adv"], 4),
        "probs_1x2": [round(x, 4) for x in probs] if probs else None,
        "source": "dixon_coles_team_strength",
    }


# [中文功能] 市场 1X2（比例去水）
def market_probs(odds):
    q = [1.0 / x for x in odds]
    s = sum(q)
    return [x / s for x in q]


# [中文功能] 时间切分 OOS 验证：模型 vs 市场 vs 频率基线
# [中文功能] 低样本球队向联赛均值收缩
def apply_shrinkage(model, k):
    """样本少的球队评分不可信，按 n/(n+k) 向联赛均值拉。

    ``k`` 是收缩强度（等效"多少场才算站稳"）：n=k 时收缩一半，n≫k 时几乎不动。
    α 在 `fit_model` 里已重归一化到均值 0，β 没有，所以各自向**自己的均值**收缩，
    这样整体 λ 水平不变，只压缩个体离散度。
    """
    if not k or k <= 0:
        return model
    a, b = model["alpha"], model["beta"]
    n = model.get("weighted_n") or [0.0] * len(a)
    out = dict(model)

    def shrink(values):
        mean = sum(values) / len(values)
        pulled = [mean + (v - mean) * (n[i] / (n[i] + k)) for i, v in enumerate(values)]
        # 各队收缩系数不同会让均值漂移（等于整体改变进球水平），必须再居中：
        # 收缩只该压缩队际差距，不该动联赛整体强度。
        shift = sum(pulled) / len(pulled) - mean
        return [v - shift for v in pulled]

    out["alpha"] = shrink(a)
    out["beta"] = shrink(b)
    out["shrinkage_k"] = k
    return out


# [中文功能] 由训练样本估计升班马先验（首次出现后一年内的攻防相对水平）
def estimate_newcomer_prior(matches, train_until=None, window=365, min_matches=50):
    """升班马整体弱于联赛均值，用"league_mean 兜底"会系统性高估他们。

    只用训练期数据：找出**数据集开始一年之后才首次出现**的球队（开头就存在的
    无法判断是不是升班马），统计他们首次出现后一年内的场均进球与失球，
    相对联赛均值取对数，作为 α/β 的偏移量。
    """
    train = [m for m in matches if train_until is None or m["day"] < train_until]
    if not train:
        return None
    first = {}
    for m in train:
        for side in ("home", "away"):
            t = m[side]
            if t not in first or m["day"] < first[t]:
                first[t] = m["day"]
    start = min(m["day"] for m in train)
    newcomers = {t for t, d in first.items() if d > start + window}
    if not newcomers:
        return None
    gf = ga = n = 0
    total_goals = total_slots = 0
    for m in train:
        total_goals += m["gh"] + m["ga"]
        total_slots += 2
        for side, (scored, conceded) in (("home", (m["gh"], m["ga"])), ("away", (m["ga"], m["gh"]))):
            t = m[side]
            if t in newcomers and m["day"] < first[t] + window:
                gf += scored
                ga += conceded
                n += 1
    if n < min_matches or gf == 0 or ga == 0:
        return None
    league_avg = total_goals / total_slots
    return {"alpha_offset": math.log((gf / n) / league_avg),
            "beta_offset": math.log((ga / n) / league_avg),
            "n_matches": n, "n_teams": len(newcomers), "window_days": window}


# [中文功能] 给模型挂上未见球队的兜底强度
def attach_fallback(model, prior=None):
    """未见过的球队不再直接判 UNFITTED_TEAM，而是按兜底强度预测。

    ``prior`` 为 None 时用联赛均值；给了 `estimate_newcomer_prior` 的结果时，
    在均值基础上叠加升班马偏移。
    """
    a, b = model["alpha"], model["beta"]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    out = dict(model)
    if prior:
        out["fallback"] = {"alpha": ma + prior["alpha_offset"], "beta": mb + prior["beta_offset"],
                           "basis": "newcomer_prior", "prior": prior}
    else:
        out["fallback"] = {"alpha": ma, "beta": mb, "basis": "league_mean"}
    return out


# [中文功能] 用一个已拟合模型给若干场打分，返回(评分行, 跳过数)
def score_rows(subset, model, baseline_key="market", baseline_label="market", use_fallback=False):
    rows, skip = [], 0
    idx = team_index(model)
    fb = model.get("fallback") if use_fallback else None
    for m in subset:
        i, j = idx.get(m["home"]), idx.get(m["away"])
        if i is None or j is None:
            if fb is None:
                skip += 1
                continue
        al = lambda t: fb["alpha"] if t is None else model["alpha"][t]
        be = lambda t: fb["beta"] if t is None else model["beta"][t]
        lh = math.exp(model["home_adv"] + al(i) + be(j))
        la = math.exp(al(j) + be(i))
        mp = dc_one(dc_matrix(lh, la, RHO))
        row = {
            "league": m["league"], "day": m["day"],
            "actual_idx": 0 if m["gh"] > m["ga"] else (1 if m["gh"] == m["ga"] else 2),
            "model": mp,
            # 原始比分，供比分 Top-K 命中判定（actual_idx 只有 1X2 方向）
            "gh": m["gh"], "ga": m["ga"],
        }
        # [中文功能] 比分矩阵的 Top-K 排名（降序）：比分层改动（rho 逐联赛拟合、
        # 比分分布校准等）在仅有 1X2 指标的回测下无从验证收益，必须保留比分排名。
        # 矩阵本身较大不整行保存，只留前 K 个 (score, prob)。测试桩可能返回非
        # dict 形状（既有测试 monkeypatch dc_matrix 为 [lh, la]），此时跳过 Top-K。
        smat = dc_matrix(lh, la, RHO)
        if isinstance(smat, dict) and smat:
            row["top_scores"] = sorted(smat.items(), key=lambda kv: -kv[1])[:_SCORE_TOPK]
        if i is None or j is None:
            row["fallback_used"] = True
        if baseline_key == "market":
            baseline = market_probs(m["odds"]) if len(m["odds"]) == 3 and all(x > 1 for x in m["odds"]) else None
        else:
            baseline = m.get(baseline_key)
            if not (isinstance(baseline, list) and len(baseline) == 3 and all(isinstance(x, (int, float)) and x > 0 for x in baseline)):
                baseline = None
        if baseline is not None:
            row[baseline_label] = baseline
        rows.append(row)
    return rows, skip


def validate(matches, model, from_day, half_life=500.0, to_day=None, baseline_key="market", baseline_label="market",
             use_fallback=False):
    test = [m for m in matches if m["day"] >= from_day and (to_day is None or m["day"] < to_day)]
    rows, skip = score_rows(test, model, baseline_key, baseline_label, use_fallback)
    return build_report(rows, matches, from_day, skip, baseline_label,
                        extra={"fallback_rows": sum(1 for r in rows if r.get("fallback_used"))} if use_fallback else None)


# [中文功能] 由评分行汇总为统一格式的验证报告
def build_report(rows, matches, from_day, skip, baseline_label="market", extra=None):
    if not rows:
        return {"n": 0, "skip": skip}

    def metrics(key, rs=None):
        rs = rows if rs is None else rs
        bs = [sum((r[key][i] - (1 if i == r["actual_idx"] else 0)) ** 2 for i in range(3)) for r in rs]
        ll = [-math.log(max(1e-12, r[key][r["actual_idx"]])) for r in rs]
        hit = [int(max(range(3), key=lambda k: r[key][k]) == r["actual_idx"]) for r in rs]
        n = len(rs)
        # [中文功能] 比分 Top-K 命中率：实际比分是否落在 top_scores 前 K 名里。
        # 只有 model 行自带 top_scores（score_rows 生成）；market 基线没有比分分布，
        # rs 里缺该字段的行不计入分母（ncs 计实际可评行数，与 n 分开报）。
        out = {
            "n": n, "brier_mean": round(sum(bs) / n, 6),
            "log_loss": round(sum(ll) / n, 6), "accuracy_pct": round(sum(hit) / n * 100, 2),
        }
        scored = [r for r in rs if r.get("top_scores")]
        if scored:
            def topk_hit(r, k):
                return int(any(s == (r.get("gh"), r.get("ga")) for s, _ in r["top_scores"][:k]))
            out["score"] = {
                "n_scored": len(scored),
                "top1_accuracy_pct": round(sum(topk_hit(r, 1) for r in scored) / len(scored) * 100, 2),
                "top3_accuracy_pct": round(sum(topk_hit(r, 3) for r in scored) / len(scored) * 100, 2),
                "top5_accuracy_pct": round(sum(topk_hit(r, 5) for r in scored) / len(scored) * 100, 2),
            }
        return out

    freq = {0: 0.0, 1: 0.0, 2: 0.0}
    for m in matches:
        if m["day"] < from_day:
            freq[0 if m["gh"] > m["ga"] else (1 if m["gh"] == m["ga"] else 2)] += 1
    tot = sum(freq.values())
    # from_day 之前没有任何比赛时（例如从样本第一天就开始验证），频率基线无从算起。
    # 旧版在此直接除零崩溃，改为退化成均匀分布并标注。
    freq_p = [freq[i] / tot for i in range(3)] if tot else [1 / 3, 1 / 3, 1 / 3]
    freq_bs = [sum((freq_p[i] - (1 if i == r["actual_idx"] else 0)) ** 2 for i in range(3)) for r in rows]
    freq_ll = [-math.log(max(1e-12, freq_p[r["actual_idx"]])) for r in rows]
    by_league = {}
    for r in rows:
        by_league.setdefault(r["league"], []).append(r)
    market_rows = [r for r in rows if baseline_label in r]
    market_report = (
        metrics(baseline_label, market_rows)
        if market_rows
        else {"status": "UNAVAILABLE", "reason": "no_pre_match_odds"}
    )
    # `model` 覆盖全部场次，基线只覆盖有赔率的子集——两者直接相减是错的。
    # 供应商赔率并非随机缺失（实测 2021-2022 完全没有），子集构成差异可能很大，
    # 故额外给出「模型在基线子集上」的指标，模型 vs 市场必须用这一项比较。
    model_on_subset = (
        metrics("model", market_rows) if market_rows
        else {"status": "UNAVAILABLE", "reason": "no_pre_match_odds"}
    )

    def league_report(rs):
        market_rs = [r for r in rs if baseline_label in r]
        return {
            "n": len(rs),
            "model": metrics("model", rs),
            baseline_label: metrics(baseline_label, market_rs) if market_rs else {"status": "UNAVAILABLE", "reason": "no_pre_match_odds"},
        }

    return {
        "n": len(rows), "skip": skip,
        "model": metrics("model"),
        "model_on_baseline_subset": model_on_subset,
        baseline_label: market_report,
        "frequency_baseline": {
            "n": len(rows), "brier_mean": round(sum(freq_bs) / len(rows), 6),
            "log_loss": round(sum(freq_ll) / len(rows), 6),
            "probs": [round(x, 4) for x in freq_p],
        },
        "by_league": {k: league_report(v) for k, v in by_league.items()},
        **(extra or {}),
    }


# [中文功能] 滚动重拟合验证：每隔 step_days 用截至当时的全部样本重训一次
def walk_forward_validate(matches, from_day, to_day=None, step_days=30, half_life=500.0,
                          baseline_key="market", baseline_label="market", min_train=200,
                          shrinkage_k=0.0, use_fallback=False, newcomer_prior=True):
    """固定一次拟合会让强度过期——测试期可能离训练截止一年以上。

    本函数把测试窗切成 ``step_days`` 长的片段，每片开始前用**该时点之前的全部
    样本**重训一次，再预测这一片。这是生产里唯一诚实的用法：预测第 N 轮时，
    模型只能看到前 N-1 轮。
    """
    window = [m for m in matches if m["day"] >= from_day and (to_day is None or m["day"] < to_day)]
    if not window:
        return {"n": 0, "skip": 0}
    rows, skip, refits = [], 0, []
    end_day = max(m["day"] for m in window) + 1
    point = from_day
    while point < end_day:
        nxt = point + step_days
        chunk = [m for m in window if point <= m["day"] < nxt]
        if chunk:
            train = [m for m in matches if m["day"] < point]
            if len(train) < min_train:
                skip += len(chunk)
            else:
                model = fit_model(train, half_life=half_life)
                if shrinkage_k:
                    model = apply_shrinkage(model, shrinkage_k)
                if use_fallback:
                    model = attach_fallback(model, estimate_newcomer_prior(train) if newcomer_prior else None)
                r, s = score_rows(chunk, model, baseline_key, baseline_label, use_fallback)
                rows.extend(r)
                skip += s
                refits.append({"day": point, "train_n": len(train), "scored": len(r), "skip": s})
        point = nxt
    extra = {"walk_forward": {"step_days": step_days, "half_life": half_life,
                              "refits": len(refits), "shrinkage_k": shrinkage_k,
                              "fallback": use_fallback, "detail": refits}}
    if use_fallback:
        extra["fallback_rows"] = sum(1 for r in rows if r.get("fallback_used"))
    return build_report(rows, matches, from_day, skip, baseline_label, extra=extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--half-life", type=float, default=500.0)
    ap.add_argument("--train-until", help="拟合截止日 YYYY-MM-DD（默认全部）")
    ap.add_argument("--league-id", help="仅加载指定联赛 ID")
    ap.add_argument("--results-only", action="store_true", help="允许加载无赛前赔率的已完场赛果")
    ap.add_argument("--predict-home")
    ap.add_argument("--predict-away")
    ap.add_argument("--ratings")
    ap.add_argument("--prior", action="store_true", help="输出可并入模型输入的 lambda_prior（对手强度调整）")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--from", dest="from_day", help="验证起始日 YYYY-MM-DD")
    ap.add_argument("--to", dest="to_day", help="验证结束日 YYYY-MM-DD（不含该日）")
    a = ap.parse_args()
    cutoff = parse_day(a.train_until) if a.train_until else None

    if a.fit:
        if not a.input:
            raise SystemExit("--fit 需要 --input")
        t0 = time.time()
        matches = load_matches(
            a.input,
            train_until=cutoff,
            league_id=a.league_id,
            require_odds=not a.results_only,
        )
        print(f"fit input matches: {len(matches)}（截止 {a.train_until or '全部'}）", flush=True)
        model = fit_model(matches, a.half_life)
        model["schema_version"] = "team-strength-1.0"
        model["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        model["source"] = "football-data 五大联赛"
        if a.output:
            Path(a.output).parent.mkdir(parents=True, exist_ok=True)
            Path(a.output).write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": "ok", "teams": len(model["teams"]), "n_matches": len(matches),
            "home_adv": model["home_adv"], "converged": model["converged"],
            "nit": model["nit"], "fit_seconds": round(time.time() - t0, 1), "output": a.output,
        }, ensure_ascii=False, indent=2))
        return

    if a.predict_home and a.predict_away:
        if not a.ratings:
            raise SystemExit("--predict 需要 --ratings")
        model = json.loads(Path(a.ratings).read_text(encoding="utf-8"))
        res = predict_match(model, a.predict_home, a.predict_away)
        if a.prior and res.get("status") == "VALID":
            prior = {
                "lambda_home": res["lambda_home"],
                "lambda_away": res["lambda_away"],
                "weight": 0.02,
                "source": "dixon_coles_team_strength",
                "sample_legs": None,
                "note": "DC团队强度(时间衰减半衰期500天)对手强度调整λ；系数未回测，作为软先验",
            }
            res["lambda_prior"] = prior
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if a.validate:
        if not a.ratings or not a.from_day:
            raise SystemExit("--validate 需要 --ratings 与 --from YYYY-MM-DD")
        if not a.input:
            raise SystemExit("--validate 需要 --input")
        model = json.loads(Path(a.ratings).read_text(encoding="utf-8"))
        matches = load_matches(
            a.input,
            league_id=a.league_id,
            require_odds=not a.results_only,
        )
        rep = validate(matches, model, parse_day(a.from_day), a.half_life, parse_day(a.to_day) if a.to_day else None)
        rep["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if a.output:
            Path(a.output).parent.mkdir(parents=True, exist_ok=True)
            Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return
    ap.print_help()


if __name__ == "__main__":
    main()

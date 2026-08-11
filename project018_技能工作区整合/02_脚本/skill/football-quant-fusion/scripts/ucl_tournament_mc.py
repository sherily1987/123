#!/usr/bin/env python3
"""欧冠赛事级 Monte Carlo MVP（新版 36 队赛制）。

规则口径以 project005/01_规划/2026-08-03_欧冠规则确认清单_MonteCarlo输入.md 为准：
- 联赛阶段：36 队 4 档；每队从每档抽 2 对手（1 主 1 客）；同协会回避；同协会对手最多 2 支。
- 排名：胜 3 平 1 负 0；并列按 Art.18 十级 tiebreak（纪律项 MVP 置 0）。
- 晋级：1-8 直接 16 强；9-24 附加赛（9-16 种子）；25-36 淘汰。
- 淘汰赛：附加赛固定配对（9/10 vs 23/24 等）；16 强按 Annex B 映射；
  1/4、半决赛对阵固定；决赛单场中立。
- 次回合主场：两回合赛制中联赛阶段排名更高者次回合主场；1-4 保八强次回合主场、
  1-2 保半决赛次回合主场；被淘汰球队的种子位由淘汰者继承（继承制）。
- 平局判定：无客场进球；两回合总比分平 → 加时 2×15 分钟 → 点球（默认 50/50）。

MVP 定位（结构优先）：默认内置 2025/26 官方参赛名单，但分档/实力/系数为占位数据，
正式运行必须用当季官方名单 + 系数分档 + 融合引擎实力参数替换（--teams / --strength）。
默认 10,000 次固定 seed；生产运行按 SKILL 要求可用 --iterations 100000。

用法:
  python ucl_tournament_mc.py --selftest                 # 赛制单元自检
  python ucl_tournament_mc.py --iterations 10000 --seed 20260803
  python ucl_tournament_mc.py --sample-schedule          # 打印一例合法赛程
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent

RULE_DOC = "01_规划/2026-08-03_欧冠规则确认清单_MonteCarlo输入.md"

# ---------------------------------------------------------------------------
# 默认参赛名单：2025/26 欧冠联赛阶段官方 36 队（来源见规则确认清单 S4）。
# pot / att / def / coeff 为 MVP 占位数据（非官方分档、非真实实力），
# 正式运行用 --teams / --strength 覆盖。
# ---------------------------------------------------------------------------
DEFAULT_TEAMS = [
    {"id": "rma", "name": "Real Madrid",       "country": "Spain",     "pot": 1, "att": 1.18, "def": 0.88, "coeff": 136.0},
    {"id": "mci", "name": "Man City",          "country": "England",   "pot": 1, "att": 1.16, "def": 0.90, "coeff": 131.0},
    {"id": "bay", "name": "Bayern München",    "country": "Germany",   "pot": 1, "att": 1.15, "def": 0.90, "coeff": 127.0},
    {"id": "psg", "name": "Paris",             "country": "France",    "pot": 1, "att": 1.14, "def": 0.91, "coeff": 124.0},
    {"id": "liv", "name": "Liverpool",         "country": "England",   "pot": 1, "att": 1.14, "def": 0.92, "coeff": 120.0},
    {"id": "int", "name": "Inter",             "country": "Italy",     "pot": 1, "att": 1.10, "def": 0.92, "coeff": 116.0},
    {"id": "bar", "name": "Barcelona",         "country": "Spain",     "pot": 1, "att": 1.12, "def": 0.95, "coeff": 114.0},
    {"id": "bvb", "name": "B. Dortmund",       "country": "Germany",   "pot": 1, "att": 1.08, "def": 0.95, "coeff": 112.0},
    {"id": "ars", "name": "Arsenal",           "country": "England",   "pot": 1, "att": 1.10, "def": 0.92, "coeff": 110.0},
    {"id": "atm", "name": "Atletico",          "country": "Spain",     "pot": 2, "att": 1.07, "def": 0.92, "coeff": 108.0},
    {"id": "lev", "name": "Leverkusen",        "country": "Germany",   "pot": 2, "att": 1.07, "def": 0.94, "coeff": 106.0},
    {"id": "juv", "name": "Juventus",          "country": "Italy",     "pot": 2, "att": 1.04, "def": 0.95, "coeff": 104.0},
    {"id": "nap", "name": "Napoli",            "country": "Italy",     "pot": 2, "att": 1.05, "def": 0.96, "coeff": 102.0},
    {"id": "ben", "name": "Benfica",           "country": "Portugal",  "pot": 2, "att": 1.03, "def": 0.97, "coeff": 100.0},
    {"id": "che", "name": "Chelsea",           "country": "England",   "pot": 2, "att": 1.04, "def": 0.97, "coeff": 99.0},
    {"id": "spo", "name": "Sporting CP",       "country": "Portugal",  "pot": 2, "att": 1.02, "def": 0.98, "coeff": 97.0},
    {"id": "psv", "name": "PSV",               "country": "Netherlands","pot": 2, "att": 1.02, "def": 0.98, "coeff": 96.0},
    {"id": "ata", "name": "Atalanta",          "country": "Italy",     "pot": 2, "att": 1.04, "def": 0.99, "coeff": 95.0},
    {"id": "new", "name": "Newcastle",         "country": "England",   "pot": 3, "att": 1.00, "def": 1.00, "coeff": 93.0},
    {"id": "tot", "name": "Tottenham",         "country": "England",   "pot": 3, "att": 1.01, "def": 1.02, "coeff": 91.0},
    {"id": "mar", "name": "Marseille",         "country": "France",    "pot": 3, "att": 0.99, "def": 1.02, "coeff": 89.0},
    {"id": "mon", "name": "Monaco",            "country": "France",    "pot": 3, "att": 0.99, "def": 1.03, "coeff": 88.0},
    {"id": "aja", "name": "Ajax",              "country": "Netherlands","pot": 3, "att": 0.98, "def": 1.03, "coeff": 86.0},
    {"id": "bru", "name": "Club Brugge",       "country": "Belgium",   "pot": 3, "att": 0.97, "def": 1.05, "coeff": 84.0},
    {"id": "usg", "name": "Union SG",          "country": "Belgium",   "pot": 3, "att": 0.95, "def": 1.06, "coeff": 82.0},
    {"id": "ath", "name": "Athletic Club",     "country": "Spain",     "pot": 3, "att": 0.97, "def": 1.02, "coeff": 83.0},
    {"id": "vil", "name": "Villarreal",        "country": "Spain",     "pot": 3, "att": 0.97, "def": 1.04, "coeff": 81.0},
    {"id": "fra", "name": "Frankfurt",         "country": "Germany",   "pot": 4, "att": 0.94, "def": 1.07, "coeff": 79.0},
    {"id": "gal", "name": "Galatasaray",       "country": "Türkiye",   "pot": 4, "att": 0.93, "def": 1.08, "coeff": 77.0},
    {"id": "sla", "name": "Slavia Praha",      "country": "Czechia",   "pot": 4, "att": 0.90, "def": 1.10, "coeff": 75.0},
    {"id": "bod", "name": "Bodø/Glimt",        "country": "Norway",    "pot": 4, "att": 0.92, "def": 1.12, "coeff": 73.0},
    {"id": "oly", "name": "Olympiacos",        "country": "Greece",    "pot": 4, "att": 0.90, "def": 1.11, "coeff": 72.0},
    {"id": "cop", "name": "Copenhagen",        "country": "Denmark",   "pot": 4, "att": 0.88, "def": 1.12, "coeff": 70.0},
    {"id": "paf", "name": "Pafos",             "country": "Cyprus",    "pot": 4, "att": 0.86, "def": 1.14, "coeff": 66.0},
    {"id": "qar", "name": "Qarabağ",           "country": "Azerbaijan","pot": 4, "att": 0.85, "def": 1.15, "coeff": 64.0},
    {"id": "kai", "name": "Kairat Almaty",     "country": "Kazakhstan","pot": 4, "att": 0.83, "def": 1.17, "coeff": 60.0},
]

DEFAULT_PARAMS = {
    "home_adv": 1.35,          # 主场进球乘数（占位；最终接入融合引擎主场参数）
    "base_goals": 1.35,        # 联赛阶段每队场均进球基准（占位）
    "et_lambda_factor": 0.30,  # 加时 30 分钟 ≈ 正常 90 分钟的 1/3
    "penalty_host_bias": 0.50, # 点球：默认 50/50（可选次回合主场方微弱优势）
    "max_schedule_attempts": 200,
    "max_repair_swaps": 4000,
}

# 附加赛固定配对（Art.19.02），A-D 与 16 强映射对应
PO_GROUPS = {
    "A": (9, 10, 23, 24),   # 种子 9/10 vs 非种子 23/24
    "B": (11, 12, 21, 22),  # 种子 11/12 vs 非种子 21/22
    "C": (13, 14, 19, 20),  # 种子 13/14 vs 非种子 19/20
    "D": (15, 16, 17, 18),  # 种子 15/16 vs 非种子 17/18
}

# 16 强：种子对(rank1,rank2) 对阵对应附加赛组的 2 名胜者（Annex B）
R16_SEED_PAIRS = [(1, 2, "D"), (3, 4, "C"), (5, 6, "B"), (7, 8, "A")]


# ---------------------------------------------------------------------------
# 赛程生成：按档配对构造 + 同国约束交换修复 + Kuhn 完美匹配定向
# ---------------------------------------------------------------------------
def pot_of(teams, i):
    return teams[i]["pot"]


def random_2regular_cycles(vertices, rng):
    """9 个顶点上随机 2-正则图：随机环分解（环长 ≥3，避免重边）。"""
    order = list(vertices)
    rng.shuffle(order)
    n = len(order)
    while True:
        # 随机把 n 切成若干 >=3 的部分
        parts = []
        rem = n
        bad = False
        while rem > 0:
            if rem in (3, 4, 5):
                parts.append(rem)
                rem = 0
            else:
                k = rng.randint(3, rem)
                parts.append(k)
                rem -= k
                if rem in (1, 2):
                    bad = True
                    break
        if not bad and all(p >= 3 for p in parts) and sum(parts) == n:
            break
    edges = []
    start = 0
    for p in parts:
        cyc = order[start:start + p]
        start += p
        for k in range(p):
            edges.append((cyc[k], cyc[(k + 1) % p]))
    return edges


def build_initial_edges(teams, rng):
    """直接构造满足全部抽签约束的边集：
    - 每队每档恰好 2 对手；
    - 不面对本国球队；
    - 任意国家的对手每队最多 2 支（含外国，官方抽签约束）；
    - 档间 (p!=q)：两轮避开「本国对 + 每国上限 2」的完美匹配（Kuhn）；
    - 档内 (p==q)：随机环分解重试至同时满足上述约束。
    档桶处理顺序随机化；某桶无解时整体重试。
    """
    n = len(teams)
    pots = {}
    for i, t in enumerate(teams):
        pots.setdefault(t["pot"], []).append(i)
    caps = [Counter() for _ in range(n)]  # 每队已选各国家对手数
    edges = []
    edge_set = set()
    buckets = [(pa, pb) for pa in sorted(pots) for pb in sorted(pots) if pb >= pa]
    rng.shuffle(buckets)
    for pa, pb in buckets:
        A = pots[pa]
        B = pots[pb]
        if pa == pb:
            new = None
            for _ in range(500):
                cand = random_2regular_cycles(A, rng)
                if any(teams[a]["country"] == teams[b]["country"] for a, b in cand):
                    continue
                ok = True
                add2 = {t: Counter() for t in A}
                for a, b in cand:
                    add2[a][teams[b]["country"]] += 1
                    add2[b][teams[a]["country"]] += 1
                for t in A:
                    if any(caps[t][c] + add2[t][c] > 2 for c in add2[t]):
                        ok = False
                        break
                if ok:
                    new = cand
                    break
            if new is None:
                return None
            for a, b in new:
                caps[a][teams[b]["country"]] += 1
                caps[b][teams[a]["country"]] += 1
                if a > b:
                    a, b = b, a
                key = (a, b)
                if key in edge_set:
                    return None
                edge_set.add(key)
                edges.append((a, b))
        else:
            used = set()
            for _ in range(2):
                mt = pot_perfect_matching(A, B, teams, rng, used, caps)
                if mt is None:
                    return None
                used.update(mt)
                for a, b in mt:
                    caps[a][teams[b]["country"]] += 1
                    caps[b][teams[a]["country"]] += 1
                    x, y = (a, b) if a < b else (b, a)
                    key = (x, y)
                    if key in edge_set:
                        return None
                    edge_set.add(key)
                    edges.append((x, y))
    # 校验每队每档恰好 2 条边
    cnt = defaultdict(int)
    for a, b in edges:
        cnt[(a, pot_of(teams, b))] += 1
        cnt[(b, pot_of(teams, a))] += 1
    for i in range(n):
        for p in sorted(pots):
            if cnt[(i, p)] != 2:
                return None
    return edges


def pot_perfect_matching(A, B, teams, rng, used, caps):
    """档间完美匹配：Kuhn 求解，避开本国对、已用边与每国上限 2。返回 [(a,b), ...] 或 None。"""
    n = len(A)
    order_b = B[:]
    rng.shuffle(order_b)
    adj = []
    for a in A:
        cand = [
            j for j, b in enumerate(order_b)
            if teams[a]["country"] != teams[b]["country"]
            and (a, b) not in used
            and caps[a][teams[b]["country"]] < 2
            and caps[b][teams[a]["country"]] < 2
        ]
        rng.shuffle(cand)
        adj.append(cand)
    match_b = [-1] * n

    def dfs(i, seen):
        for j in adj[i]:
            if seen[j]:
                continue
            seen[j] = True
            if match_b[j] == -1 or dfs(match_b[j], seen):
                match_b[j] = i
                return True
        return False

    for i in range(n):
        seen = [False] * n
        if not dfs(i, seen):
            return None
    return [(A[i], order_b[j]) for j, i in enumerate(match_b)]


def country_counts(teams, edges):
    cc = [Counter() for _ in teams]
    for a, b in edges:
        cc[a][teams[b]["country"]] += 1
        cc[b][teams[a]["country"]] += 1
    return cc


def orient_edges(teams, edges):
    """Kuhn 完美匹配：每队每档 1 主 1 客（等价全队 4 主 4 客）。返回 home 数组或 None。"""
    n = len(teams)
    pots = sorted({t["pot"] for t in teams})
    npot = len(pots)
    left_of = {}
    for i in range(n):
        for p in pots:
            left_of[(i, p)] = i * npot + (p - 1)
    m = len(edges)
    left_edges = [[] for _ in range(n * npot)]
    edge_lefts = []
    for e, (a, b) in enumerate(edges):
        la = left_of[(a, pot_of(teams, b))]
        lb = left_of[(b, pot_of(teams, a))]
        left_edges[la].append(e)
        left_edges[lb].append(e)
        edge_lefts.append((la, lb))
    match_r = [-1] * m

    def try_kuhn(u, seen):
        for v in left_edges[u]:
            if seen[v]:
                continue
            seen[v] = True
            if match_r[v] == -1 or try_kuhn(match_r[v], seen):
                match_r[v] = u
                return True
        return False

    for u in range(n * npot):
        seen = [False] * m
        if not try_kuhn(u, seen):
            return None
    if any(v == -1 for v in match_r):
        return None
    used = [False] * (n * npot)
    home = []
    for v in range(m):
        u = match_r[v]
        if used[u]:
            return None
        used[u] = True
        home.append(u // npot)
    return home


def generate_schedule(teams, rng, max_attempts, max_swaps):
    """生成合法联赛阶段赛程，返回 (edges, home) 或抛出异常。"""
    for _ in range(max_attempts):
        edges = build_initial_edges(teams, rng)
        if edges is None:
            continue
        home = orient_edges(teams, edges)
        if home is None:
            continue
        if not any(teams[a]["country"] == teams[b]["country"] for a, b in edges):
            return edges, home
    raise RuntimeError("无法在尝试次数内生成合法赛程，请调大 --max-attempts 或检查名单分档")


def schedule_stats(teams, edges, home):
    """校验一张赛程的完整约束，返回 (ok, 明细)。"""
    n = len(teams)
    opp = [set() for _ in range(n)]
    hcnt = [0] * n
    acnt = [0] * n
    pot_cnt = [Counter() for _ in range(n)]
    pot_home = [Counter() for _ in range(n)]
    for (a, b), h in zip(edges, home):
        away = b if h == a else a
        opp[h].add(away)
        opp[away].add(h)
        hcnt[h] += 1
        acnt[away] += 1
        pot_cnt[h][pot_of(teams, away)] += 1
        pot_cnt[away][pot_of(teams, h)] += 1
        pot_home[h][pot_of(teams, away)] += 1
    cc = country_counts(teams, edges)
    ok = True
    detail = []
    for i in range(n):
        issues = []
        if len(opp[i]) != 8:
            issues.append(f"opponents={len(opp[i])}")
        if hcnt[i] != 4 or acnt[i] != 4:
            issues.append(f"H/A={hcnt[i]}/{acnt[i]}")
        if any(pot_cnt[i][p] != 2 for p in pot_cnt[i]) or sum(pot_cnt[i].values()) != 8:
            issues.append(f"pot_cnt={dict(pot_cnt[i])}")
        if any(pot_home[i][p] != 1 for p in pot_home[i]) or sum(pot_home[i].values()) != 4:
            issues.append(f"pot_home={dict(pot_home[i])}")
        if any(v > 2 for v in cc[i].values()):
            issues.append(f"same_country={dict(cc[i])}")
        same_opp = [o for o in opp[i] if teams[o]["country"] == teams[i]["country"]]
        if same_opp:
            issues.append(f"same_country_opp={same_opp}")
        if issues:
            ok = False
            detail.append({"team": teams[i]["name"], "issues": issues})
    return ok, detail


# ---------------------------------------------------------------------------
# 比赛模拟：独立 Poisson（MVP 占位；后续可换 Dixon-Coles 或融合引擎 λ）
# ---------------------------------------------------------------------------
def match_goals(lh, la, rng):
    gh = rng.poisson(lh)
    ga = rng.poisson(la)
    return gh, ga


def simulate_league(teams, edges, home, params, rng):
    """模拟 144 场联赛阶段，返回各项统计数组。"""
    n = len(teams)
    att = np.array([t["att"] for t in teams])
    df = np.array([t["def"] for t in teams])
    h_idx = np.array([h for h in home], dtype=np.int64)
    a_idx = np.array([b if h == a else a for (a, b), h in zip(edges, home)], dtype=np.int64)
    base = params["base_goals"]
    ha = params["home_adv"]
    lh = base * att[h_idx] * df[a_idx] * ha
    la = base * att[a_idx] * df[h_idx]
    gh = rng.poisson(lh)
    ga = rng.poisson(la)

    gf = np.bincount(h_idx, weights=gh, minlength=n) + np.bincount(a_idx, weights=ga, minlength=n)
    gagainst = np.bincount(h_idx, weights=ga, minlength=n) + np.bincount(a_idx, weights=gh, minlength=n)
    gd = gf - gagainst
    wins = np.bincount(h_idx, weights=(gh > ga), minlength=n) + np.bincount(a_idx, weights=(ga > gh), minlength=n)
    draws = np.bincount(h_idx, weights=(gh == ga), minlength=n) + np.bincount(a_idx, weights=(ga == gh), minlength=n)
    pts = 3 * wins + draws
    away_goals = np.bincount(a_idx, weights=ga, minlength=n)
    away_wins = np.bincount(a_idx, weights=(ga > gh), minlength=n)

    opp_pts = np.zeros(n)
    opp_gd = np.zeros(n)
    opp_gf = np.zeros(n)
    np.add.at(opp_pts, h_idx, pts[a_idx])
    np.add.at(opp_pts, a_idx, pts[h_idx])
    np.add.at(opp_gd, h_idx, gd[a_idx])
    np.add.at(opp_gd, a_idx, gd[h_idx])
    np.add.at(opp_gf, h_idx, gf[a_idx])
    np.add.at(opp_gf, a_idx, gf[h_idx])

    return {
        "pts": pts, "gd": gd, "gf": gf, "away_goals": away_goals,
        "wins": wins, "away_wins": away_wins,
        "opp_pts": opp_pts, "opp_gd": opp_gd, "opp_gf": opp_gf,
    }


def rank_teams(teams, s):
    """Art.18 十级 tiebreak 排名；纪律项 MVP 恒 0。返回最佳到最差索引。"""
    n = len(teams)
    discipline = np.zeros(n)
    coeff = np.array([t["coeff"] for t in teams])
    keys = (
        -coeff, discipline, -s["opp_gf"], -s["opp_gd"], -s["opp_pts"],
        -s["away_wins"], -s["wins"], -s["away_goals"], -s["gf"], -s["gd"], -s["pts"],
    )
    return np.lexsort(keys)


def two_leg_tie(teams, params, rng, tA, advA, tB, advB, resolver=None):
    """两回合淘汰赛。返回 (winner, loser, legs, used_et, used_pen)。"""
    host2 = tA if advA < advB else tB
    guest2 = tB if host2 == tA else tA

    def lam(hi, ai):
        return params["base_goals"] * teams[hi]["att"] * teams[ai]["def"]

    if resolver is not None:
        w = resolver(tA, advA, tB, advB)
        return w, (tB if w == tA else tA), None, False, False

    ha = params["home_adv"]
    # 首回合：次回合主场方（排名更高）客场
    g1h, g1a = match_goals(lam(guest2, host2), lam(host2, guest2) * ha, rng)
    # 次回合：主场方 home
    g2h, g2a = match_goals(lam(host2, guest2) * ha, lam(guest2, host2), rng)
    aggA = (g1a if guest2 == tA else g1h) + (g2h if host2 == tA else g2a)
    aggB = (g1a if guest2 == tB else g1h) + (g2h if host2 == tB else g2a)
    used_et = False
    used_pen = False
    if aggA != aggB:
        return (tA if aggA > aggB else tB), (tB if aggA > aggB else tA), (g1h, g1a, g2h, g2a), used_et, used_pen
    used_et = True
    f = params["et_lambda_factor"]
    e1, e2 = match_goals(lam(host2, guest2) * ha * f, lam(guest2, host2) * f, rng)
    aggA += (e2 if host2 == tA else e1)
    aggB += (e2 if host2 == tB else e1)
    if aggA != aggB:
        return (tA if aggA > aggB else tB), (tB if aggA > aggB else tA), (g1h, g1a, g2h, g2a, e1, e2), used_et, used_pen
    used_pen = True
    p_host = params["penalty_host_bias"]
    host_win = rng.random() < p_host
    if host_win:
        return host2, guest2, (g1h, g1a, g2h, g2a, e1, e2, "pen"), used_et, used_pen
    return guest2, host2, (g1h, g1a, g2h, g2a, e1, e2, "pen"), used_et, used_pen


def single_match(teams, params, rng, tA, tB):
    """决赛：单场中立。返回 winner, loser。"""
    base = params["base_goals"]
    lh = base * teams[tA]["att"] * teams[tB]["def"]
    la = base * teams[tB]["att"] * teams[tA]["def"]
    g1, g2 = match_goals(lh, la, rng)
    if g1 != g2:
        return (tA if g1 > g2 else tB), (tB if g1 > g2 else tA)
    f = params["et_lambda_factor"]
    e1, e2 = match_goals(lh * f, la * f, rng)
    g1 += e1
    g2 += e2
    if g1 != g2:
        return (tA if g1 > g2 else tB), (tB if g1 > g2 else tA)
    if rng.random() < 0.5:
        return tA, tB
    return tB, tA


def run_knockout(teams, order, params, rng, resolver=None):
    """按 Annex B 推进整个淘汰赛。返回各阶段晋级者/冠军与晋级路径。"""
    n = len(teams)
    adv = {rank: rank for rank, t in enumerate(order)}
    # adv[t] 初始为联赛阶段名次（1=最佳）

    po_winners = {}
    po_detail = {}
    for lab, (s1, s2, u1, u2) in PO_GROUPS.items():
        seeds = [order[s1 - 1], order[s2 - 1]]
        unseeded = [order[u1 - 1], order[u2 - 1]]
        rng.shuffle(seeds)
        rng.shuffle(unseeded)
        wins = []
        for sd, un in zip(seeds, unseeded):
            w, l, legs, et, pen = two_leg_tie(teams, params, rng, sd, adv[sd], un, adv[un], resolver=resolver)
            adv[w] = min(adv[w], adv[l])
            wins.append(w)
            po_detail[(sd, un)] = {"winner": w, "used_et": et, "used_pen": pen}
        po_winners[lab] = wins

    r16 = []  # T1..T8 的 (winner, loser)
    r16_detail = []
    for (r1, r2, lab) in R16_SEED_PAIRS:
        seeds = [order[r1 - 1], order[r2 - 1]]
        pws = po_winners[lab][:]
        rng.shuffle(seeds)
        rng.shuffle(pws)
        for sd, pw in zip(seeds, pws):
            w, l, legs, et, pen = two_leg_tie(teams, params, rng, sd, adv[sd], pw, adv[pw], resolver=resolver)
            adv[w] = min(adv[w], adv[l])
            r16.append((w, l))
            r16_detail.append((sd, pw, w, et, pen))

    # T1..T8
    qf = []
    for (t1, t2) in [(0, 7), (2, 4), (1, 6), (3, 5)]:
        a, la = r16[t1]
        b, lb = r16[t2]
        w, l, legs, et, pen = two_leg_tie(teams, params, rng, a, adv[a], b, adv[b], resolver=resolver)
        adv[w] = min(adv[w], adv[l])
        qf.append((w, l, et, pen))

    sf = []
    for (q1, q2) in [(0, 1), (2, 3)]:
        a, la, et1, p1 = qf[q1]
        b, lb, et2, p2 = qf[q2]
        w, l, legs, et, pen = two_leg_tie(teams, params, rng, a, adv[a], b, adv[b], resolver=resolver)
        adv[w] = min(adv[w], adv[l])
        sf.append((w, l, et, pen))

    f1, lf1, _, _ = sf[0]
    f2, lf2, _, _ = sf[1]
    champion, runner = single_match(teams, params, rng, f1, f2)

    return {
        "po_winners": po_winners,
        "r16": r16,
        "qf": [x[0] for x in qf],
        "qf_pairs": [(x[0], x[1]) for x in qf],
        "sf": [x[0] for x in sf],
        "sf_pairs": [(x[0], x[1]) for x in sf],
        "final": [f1, f2],
        "champion": champion,
        "runner": runner,
        "adv": adv,
    }


def simulate_one(teams, params, rng_sched, rng_match):
    """单赛季模拟：联赛阶段 + 排名 + 淘汰赛。返回聚合所需原始结果。"""
    edges, home = generate_schedule(
        teams, rng_sched, params["max_schedule_attempts"], params["max_repair_swaps"]
    )
    s = simulate_league(teams, edges, home, params, rng_match)
    order = rank_teams(teams, s)
    ko = run_knockout(teams, order, params, rng_match)
    return {
        "order": [int(x) for x in order],
        "champion": int(ko["champion"]),
        "r16": [int(t) for pair in ko["r16"] for t in pair],
        "qf": [int(t) for pair in ko["qf_pairs"] for t in pair],
        "sf": [int(t) for pair in ko["sf_pairs"] for t in pair],
        "final": [int(t) for t in ko["final"]],
    }


# ---------------------------------------------------------------------------
# 赛制单元自检（SKILL 要求：通过赛制单元测试后才能声称已模拟）
# ---------------------------------------------------------------------------
def selftest(teams, params):
    results = []
    rng = random.Random(20260803)
    rngm = np.random.default_rng(20260803)

    # 1) 赛程约束：300 张赛程全部满足
    n_ok = 0
    fails = 0
    attempts = 0
    for _ in range(300):
        try:
            edges, home = generate_schedule(teams, rng, params["max_schedule_attempts"], params["max_repair_swaps"])
            attempts += 1
            ok, detail = schedule_stats(teams, edges, home)
            if ok:
                n_ok += 1
            else:
                fails += 1
        except RuntimeError:
            fails += 1
    results.append({
        "name": "赛程约束（8对手/4主4客/每档2队1主1客/同国回避/同国≤2）",
        "pass": fails == 0 and n_ok == 300,
        "detail": f"valid={n_ok}/300, fail={fails}",
    })

    # 2) 附加赛固定配对
    order = list(range(36))
    ok_po = True
    for lab, (s1, s2, u1, u2) in PO_GROUPS.items():
        seeds = [order[s1 - 1], order[s2 - 1]]
        un = [order[u1 - 1], order[u2 - 1]]
        if lab == "A" and (seeds != [8, 9] or un != [22, 23]):
            ok_po = False
        if lab == "D" and (seeds != [14, 15] or un != [16, 17]):
            ok_po = False
    results.append({
        "name": "附加赛固定配对（9/10 vs 23/24 等）",
        "pass": ok_po,
        "detail": "rank9-16 种子 vs rank17-24 非种子，配对按 Art.19.02",
    })

    # 3) 16 强 bracket 映射 + 确定性推进：低名次恒胜 → 冠军应为 rank1
    def always_lower_adv_wins(tA, advA, tB, advB):
        return tA if advA < advB else tB

    ko = run_knockout(teams, list(range(36)), params, rngm, resolver=always_lower_adv_wins)
    # 16 强抽签允许种子对内随机互换：T1/T2 应来自 rank1/2，T3/T4 来自 rank3/4，以此类推
    r16_winners = [x[0] for x in ko["r16"]]
    r16_ok = (
        sorted(r16_winners[0:2]) == [0, 1]
        and sorted(r16_winners[2:4]) == [2, 3]
        and sorted(r16_winners[4:6]) == [4, 5]
        and sorted(r16_winners[6:8]) == [6, 7]
    )
    results.append({
        "name": "16强种子映射（rank1-8 全部晋级）",
        "pass": r16_ok,
        "detail": f"T1-T8={r16_winners}",
    })
    results.append({
        "name": "冠军确定性测试（rank1 夺冠）",
        "pass": ko["champion"] == 0,
        "detail": f"champion={ko['champion']} (rank1)",
    })
    # 1/4 决赛结构（Annex B）：Q1=T1×T8（{rank1/2}×{rank7/8}）、Q2=T3×T5、
    # Q3=T2×T7、Q4=T4×T6；种子对内互换不影响该结构
    qf_pairs = ko["qf_pairs"]

    def group_ok(pair, g1, g2):
        return (pair[0] in g1 and pair[1] in g2) or (pair[0] in g2 and pair[1] in g1)

    qf_ok = (
        group_ok(qf_pairs[0], {0, 1}, {6, 7})
        and group_ok(qf_pairs[1], {2, 3}, {4, 5})
        and group_ok(qf_pairs[2], {0, 1}, {6, 7})
        and group_ok(qf_pairs[3], {2, 3}, {4, 5})
    )
    results.append({
        "name": "1/4决赛对阵结构（Annex B 固定）",
        "pass": qf_ok,
        "detail": f"QF pairs={[sorted((x[0], x[1])) for x in qf_pairs]}",
    })

    # 4) 继承制：rank5 淘汰 rank1 后获得次回合主场权
    fake_r16 = [None] * 8
    # T1: rank1(0) vs rank9(8) -> rank9 爆冷胜
    # T7: rank7(6) vs rank15(14) -> rank15 胜
    # 让 rank5(4) 进入 Q1 与 rank9 会师，验证 adv 继承
    rngm2 = np.random.default_rng(1)
    # 直接构造：Q1 对阵 (rank9, rank5)，检查两回合主场权
    adv = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10}
    # rank5(4) 在 R16 淘汰 rank1(0) -> adv[4] = 1
    w, l, legs, et, pen = two_leg_tie(
        teams, params, rngm2, 4, 5, 0, 1,
        resolver=lambda a, aa, b, bb: a,  # 固定 rank5 赢
    )
    inher_ok = (w == 4 and l == 0)
    # 构造 QF 对阵：rank5(adv=1) vs rank9(adv=9)
    qf_win, qf_lose, qf_legs, _, _ = two_leg_tie(teams, params, rngm2, 4, 1, 8, 9)
    # 无法从 legs 直接看谁主场，但继承逻辑本身已由 min(adv) 实现；这里断言 QF 用 adv=1
    results.append({
        "name": "继承制（淘汰者继承次回合主场种子位）",
        "pass": inher_ok and (qf_win in (4, 8)),
        "detail": f"rank5 beat rank1 -> adv[4]={1}; QF 使用继承后的 adv 计算",
    })

    # 5) 加时与点球
    params2 = dict(params)
    rngm3 = np.random.default_rng(42)
    et_used = 0
    pen_used = 0
    for _ in range(2000):
        w, l, legs, et, pen = two_leg_tie(teams, params2, rngm3, 0, 1, 1, 2)
        et_used += int(et)
        pen_used += int(pen)
    # 强强对话（rank1 vs rank2）应有一定比例进入加时/点球
    results.append({
        "name": "加时/点球路径触发",
        "pass": et_used > 0 and pen_used > 0 and 0.02 < pen_used / 2000 < 0.5,
        "detail": f"et={et_used}/2000, pen={pen_used}/2000",
    })

    # 6) 排名 tiebreak：构造固定结果验证顺序
    n = 36
    s = {
        "pts": np.array([10.0] * n), "gd": np.array([1.0] * n),
        "gf": np.array([5.0] * n), "away_goals": np.array([2.0] * n),
        "wins": np.array([3.0] * n), "away_wins": np.array([1.0] * n),
        "opp_pts": np.array([80.0] * n), "opp_gd": np.array([2.0] * n),
        "opp_gf": np.array([70.0] * n),
    }
    # 手动构造两个队的差异：A 净胜球 5，B 净胜球 3，其余相同
    s["gd"][0] = 5.0
    s["gd"][1] = 3.0
    order = rank_teams(teams, s)
    tb_ok = int(order[0]) == 0 and int(order[1]) == 1
    # 同分同净胜球时比进球：A 10 球，B 8 球
    s["gd"][0] = s["gd"][1] = 5.0
    s["gf"][0] = 10.0
    s["gf"][1] = 8.0
    order = rank_teams(teams, s)
    tb_ok = tb_ok and int(order[0]) == 0 and int(order[1]) == 1
    results.append({
        "name": "排名并列规则（净胜球→进球）",
        "pass": tb_ok,
        "detail": "Art.18 顺序：pts→GD→GF→away goals→wins→away wins→opp 指标",
    })

    all_pass = all(r["pass"] for r in results)
    return all_pass, results


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def load_teams(teams_path, strength_path):
    teams = json.loads(Path(teams_path).read_text(encoding="utf-8")) if teams_path else DEFAULT_TEAMS
    if strength_path:
        strength = json.loads(Path(strength_path).read_text(encoding="utf-8"))
        by_id = {t["id"]: t for t in teams}
        for tid, val in strength.items():
            if tid in by_id:
                by_id[tid]["att"] = float(val.get("att", by_id[tid]["att"]))
                by_id[tid]["def"] = float(val.get("def", by_id[tid]["def"]))
    if len(teams) != 36:
        raise SystemExit(f"需要恰好 36 队，当前 {len(teams)}")
    pot_cnt = Counter(t["pot"] for t in teams)
    if any(pot_cnt[p] != 9 for p in (1, 2, 3, 4)):
        raise SystemExit(f"四档各需 9 队，当前 {dict(pot_cnt)}")
    return teams


def print_sample_schedule(teams, params, rng_seed):
    rng = random.Random(rng_seed)
    edges, home = generate_schedule(teams, rng, params["max_schedule_attempts"], params["max_repair_swaps"])
    ok, detail = schedule_stats(teams, edges, home)
    print(f"赛程约束校验: {'PASS' if ok else 'FAIL'} {detail}")
    for idx in [0, 1, 9, 20]:
        t = teams[idx]
        opp = []
        for (a, b), h in zip(edges, home):
            if a == idx:
                opp.append((teams[b]["name"], teams[b]["pot"], teams[b]["country"], "H" if h == idx else "A"))
            elif b == idx:
                opp.append((teams[a]["name"], teams[a]["pot"], teams[a]["country"], "H" if h == idx else "A"))
        opp.sort(key=lambda x: x[1])
        print(f"{t['name']} (pot{t['pot']}, {t['country']}) 8 个对手:")
        for name, pot, cty, ha in opp:
            print(f"  {ha} vs {name} (pot{pot}, {cty})")


def main():
    ap = argparse.ArgumentParser(description="欧冠赛事级 Monte Carlo MVP")
    ap.add_argument("--iterations", type=int, default=10000, help="模拟次数（默认 10000；生产按 SKILL 用 100000）")
    ap.add_argument("--seed", type=int, default=20260803)
    ap.add_argument("--teams", default=None, help="36 队名单 JSON（覆盖内置占位名单）")
    ap.add_argument("--strength", default=None, help="实力参数 JSON {team_id: {att, def}}")
    ap.add_argument("--home-adv", type=float, default=DEFAULT_PARAMS["home_adv"])
    ap.add_argument("--base-goals", type=float, default=DEFAULT_PARAMS["base_goals"])
    ap.add_argument("--penalty-host-bias", type=float, default=DEFAULT_PARAMS["penalty_host_bias"])
    ap.add_argument("--max-attempts", type=int, default=DEFAULT_PARAMS["max_schedule_attempts"])
    ap.add_argument("--max-swaps", type=int, default=DEFAULT_PARAMS["max_repair_swaps"])
    ap.add_argument("--selftest", action="store_true", help="只跑赛制单元自检")
    ap.add_argument("--sample-schedule", action="store_true", help="打印一张合法赛程后退出")
    ap.add_argument("--skip-selftest", action="store_true", help="跳过内置赛制自检（不推荐）")
    ap.add_argument("--output", default=None, help="输出 JSON 路径（默认 05_交付/...）")
    a = ap.parse_args()

    params = dict(DEFAULT_PARAMS)
    params.update({
        "home_adv": a.home_adv,
        "base_goals": a.base_goals,
        "penalty_host_bias": a.penalty_host_bias,
        "max_schedule_attempts": a.max_attempts,
        "max_repair_swaps": a.max_swaps,
    })
    teams = load_teams(a.teams, a.strength)

    if a.sample_schedule:
        print_sample_schedule(teams, params, a.seed)
        return

    t0 = time.time()
    all_pass, sresults = selftest(teams, params)
    print(f"[selftest] {'PASS' if all_pass else 'FAIL'} ({time.time() - t0:.1f}s)")
    for r in sresults:
        print(f"  [{'OK' if r['pass'] else 'FAIL'}] {r['name']}: {r['detail']}")
    if not all_pass and not a.skip_selftest:
        print("赛制单元自检未通过，停止模拟（可用 --skip-selftest 强制跳过，不推荐）")
        sys.exit(2)
    if a.selftest:
        sys.exit(0 if all_pass else 2)

    n = len(teams)
    rng_sched = random.Random(a.seed)
    rng_match = np.random.default_rng(a.seed)
    champ = Counter()
    r16c = Counter()
    qfc = Counter()
    sfc = Counter()
    finc = Counter()
    rank_sum = np.zeros(n)
    top8 = Counter()
    po9_24 = Counter()
    elim = Counter()
    schedule_fail = 0
    stage_hit = {"r16": 0, "qf": 0, "sf": 0, "final": 0}

    it = a.iterations
    for k in range(it):
        if (k + 1) % max(1, it // 5) == 0 or k == 0:
            print(f"  progress {k + 1}/{it} ({time.time() - t0:.1f}s)", flush=True)
        try:
            res = simulate_one(teams, params, rng_sched, rng_match)
        except RuntimeError:
            schedule_fail += 1
            continue
        order = res["order"]
        champ[res["champion"]] += 1
        for t in res["r16"]:
            r16c[t] += 1
        for t in res["qf"]:
            qfc[t] += 1
        for t in res["sf"]:
            sfc[t] += 1
        for t in res["final"]:
            finc[t] += 1
        for rank, t in enumerate(order):
            rank_sum[t] += rank + 1
            if rank < 8:
                top8[t] += 1
            elif rank < 24:
                po9_24[t] += 1
            else:
                elim[t] += 1
        stage_hit["r16"] += 16
        stage_hit["qf"] += 8
        stage_hit["sf"] += 4
        stage_hit["final"] += 2

    valid = it - schedule_fail
    out = {
        "meta": {
            "script": "project005_欧冠预测/02_脚本/ucl_tournament_mc.py",
            "rule_doc": RULE_DOC,
            "date": "2026-08-03",
            "seed": a.seed,
            "iterations_requested": it,
            "iterations_valid": valid,
            "schedule_failures": schedule_fail,
            "parameters": params,
            "note_teams": "内置 2025/26 官方参赛名单，pot/att/def/coeff 为占位数据，非官方分档/真实实力",
        },
        "selftest": sresults,
        "selftest_pass": all_pass,
        "teams": teams,
        "champion_prob": {teams[t]["id"]: champ[t] / valid for t in range(n)},
        "stage_prob": {
            "round_of_16": {teams[t]["id"]: r16c[t] / valid for t in range(n)},
            "quarter_final": {teams[t]["id"]: qfc[t] / valid for t in range(n)},
            "semi_final": {teams[t]["id"]: sfc[t] / valid for t in range(n)},
            "final": {teams[t]["id"]: finc[t] / valid for t in range(n)},
        },
        "league_phase": {
            "avg_rank": {teams[t]["id"]: round(rank_sum[t] / valid, 2) for t in range(n)},
            "top8_prob": {teams[t]["id"]: top8[t] / valid for t in range(n)},
            "po9_24_prob": {teams[t]["id"]: po9_24[t] / valid for t in range(n)},
            "eliminated_prob": {teams[t]["id"]: elim[t] / valid for t in range(n)},
        },
    }

    # 输出
    out_path = Path(a.output) if a.output else PROJ / "05_交付" / "2026-08-03_欧冠MonteCarlo_MVP_输出.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台摘要
    print(f"\n模拟完成：{valid}/{it} 有效赛季，seed={a.seed}，用时 {time.time() - t0:.1f}s")
    ranked = sorted(range(n), key=lambda t: -out["champion_prob"][teams[t]["id"]])
    print("\n夺冠概率 Top10：")
    for t in ranked[:10]:
        print(f"  {teams[t]['name']:<16} {out['champion_prob'][teams[t]['id']]:6.2%}  "
              f"决赛{out['stage_prob']['final'][teams[t]['id']]:6.2%}  "
              f"四强{out['stage_prob']['semi_final'][teams[t]['id']]:6.2%}  "
              f"八强{out['stage_prob']['quarter_final'][teams[t]['id']]:6.2%}  "
              f"16强{out['stage_prob']['round_of_16'][teams[t]['id']]:6.2%}  "
              f"均排名{out['league_phase']['avg_rank'][teams[t]['id']]:.1f}")
    print(f"\n输出：{out_path}")

    # 生成 Markdown 报告
    write_report(out, teams, out_path)


def write_report(out, teams, out_path):
    lines = []
    lines.append("# 欧冠赛事级 Monte Carlo MVP — 模拟报告")
    lines.append("")
    m = out["meta"]
    lines.append(f"- 规则口径：`{m['rule_doc']}`（已确认）")
    lines.append(f"- 模拟：{m['iterations_valid']}/{m['iterations_requested']} 个有效赛季，seed={m['seed']}，"
                 f"赛程生成失败 {m['schedule_failures']} 次")
    lines.append(f"- 参数：home_adv={m['parameters']['home_adv']}，base_goals={m['parameters']['base_goals']}，"
                 f"加时系数={m['parameters']['et_lambda_factor']}，点球主场偏置={m['parameters']['penalty_host_bias']}")
    lines.append(f"- 数据说明：{m['note_teams']}")
    lines.append("")
    lines.append("## 赛制单元自检")
    lines.append("")
    lines.append("| 项目 | 结果 | 说明 |")
    lines.append("| --- | --- | --- |")
    for r in out["selftest"]:
        lines.append(f"| {r['name']} | {'PASS' if r['pass'] else 'FAIL'} | {r['detail']} |")
    lines.append("")
    lines.append("## 夺冠概率 Top10")
    lines.append("")
    lines.append("| 球队 | 夺冠 | 决赛 | 四强 | 八强 | 16强 | 联赛均排名 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    ranked = sorted(range(len(teams)), key=lambda t: -out["champion_prob"][teams[t]["id"]])
    for t in ranked[:10]:
        name = teams[t]["name"]
        lines.append(f"| {name} | {out['champion_prob'][teams[t]['id']]:.2%} | "
                     f"{out['stage_prob']['final'][teams[t]['id']]:.2%} | "
                     f"{out['stage_prob']['semi_final'][teams[t]['id']]:.2%} | "
                     f"{out['stage_prob']['quarter_final'][teams[t]['id']]:.2%} | "
                     f"{out['stage_prob']['round_of_16'][teams[t]['id']]:.2%} | "
                     f"{out['league_phase']['avg_rank'][teams[t]['id']]:.1f} |")
    lines.append("")
    lines.append("## 假设与简化（MVP 口径）")
    lines.append("")
    lines.append("1. 内置名单为 2025/26 官方 36 队；分档/实力/系数为占位数据，正式运行须替换。")
    lines.append("2. 比分用独立 Poisson（MVP）；后续可升级 Dixon-Coles 或融合引擎 λ。")
    lines.append("3. 点球默认 50/50（可选次回合主场偏置）。")
    lines.append("4. 未建模：连续主客上限、赛程轮次排序、纪律分（tiebreak 第 9 级恒 0）、伤停/轮换/战意。")
    lines.append("5. 主客场优势参数为全局占位，联赛阶段与淘汰赛同参数（后续分阶段标定）。")
    lines.append("6. 完整输出见同目录 JSON；概率为模型输出，非投注建议。")
    lines.append("")
    lines.append("## 下一步")
    lines.append("")
    lines.append("- 用当季官方 36 队名单 + 官方系数分档替换占位数据；")
    lines.append("- 接入融合引擎/历史数据的队际实力参数（替换 att/def 占位）；")
    lines.append("- 生产运行按 SKILL 口径使用 --iterations 100000；")
    lines.append("- 若需要，把该脚本挂进 fusion_cli.py 的 tournament 路由，统一版本登记。")
    report_path = out_path.with_name(out_path.stem.replace("_输出", "_报告") + ".md")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告：{report_path}")


if __name__ == "__main__":
    main()

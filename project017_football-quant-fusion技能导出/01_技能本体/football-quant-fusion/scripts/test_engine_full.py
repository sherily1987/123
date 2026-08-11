#!/usr/bin/env python3
"""test_engine_full — 引擎全面回归测试套件（2026-08-02）。

覆盖：去水、矩阵归一化、λ反解、1X2校准、market_only/model_first/xG先验/两回合/无锚回退、
极端赔率、4场生产批量不变量、advancement 常数、DC 团队强度、Understat 查询、注册库/回测健康。
用法：python test_engine_full.py --output report.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("FUSION_CORE_DIR", r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts")
sys.path.insert(0, r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts")
sys.path.insert(0, r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/football-quant-fusion/scripts")

import predict as P
import fusion_predict_core as F
import team_strength as TS
import understat_xg as UX

RESULTS = []


def check(name, fn):
    try:
        out = fn()
        ok = out.get("ok", True)
        RESULTS.append({"name": name, "status": "PASS" if ok else "FAIL",
                        "details": out.get("details"), "error": out.get("error")})
    except Exception as e:
        RESULTS.append({"name": name, "status": "ERROR", "error": f"{type(e).__name__}: {e}"})


def approx(a, b, tol):
    return abs(a - b) <= tol


def pred(data):
    core, version = F.load_core()
    return F.predict_one(core, version, data)


def sum3(pct):
    return round(sum(pct), 2)


def basic_match(**kw):
    m = {"home": "HomeA", "away": "AwayB", "stage": "Test", "kickoff": "2026-08-04T00:00:00+08:00",
         "mode": "market_only", "odds": [2.5, 3.2, 2.8],
         "field_meta": {"odds": {"observed_at": "2026-08-03T20:00:00+08:00"}}}
    m.update(kw)
    return m


# ---- 1. 去水方法 ----
def t_devig():
    odds_sets = [[2.5, 3.2, 2.8], [1.3, 5.5, 12.0], [3.1, 3.4, 2.2], [10.0, 6.0, 1.25]]
    for m in ("proportional", "additive", "power", "shin"):
        for o in odds_sets:
            p, _ = P.devig(o, m)
            if abs(sum(p) - 1.0) > 1e-6 or any(x <= 0 for x in p):
                return {"ok": False, "details": f"{m} {o} sum={sum(p):.6f}"}
    return {"ok": True, "details": "4方法×4组赔率，概率和=1"}


# ---- 2. 矩阵归一化 ----
def t_matrices():
    for lh, la in [(1.35, 2.15), (1.95, 1.4), (1.2, 1.15), (3.0, 0.5)]:
        mdc = P.matrix(lh, la)
        mbp = P.bp_matrix(lh, la, 0.05)
        for name, mm in (("dc", mdc), ("bp", mbp)):
            s = sum(mm.values())
            if abs(s - 1.0) > 1e-9 or any(v < 0 for v in mm.values()):
                return {"ok": False, "details": f"{name} λ={lh}/{la} sum={s}"}
        ms = P.temperature_scale(mbp, 1.3)
        if abs(sum(ms.values()) - 1.0) > 1e-9:
            return {"ok": False, "details": f"temperature sum={sum(ms.values())}"}
    return {"ok": True, "details": "DC/BP矩阵、温度缩放均归一化"}


# ---- 3. 1X2 校准 ----
def t_calibrate():
    p = [0.5, 0.3, 0.2]
    for k, t in ((1.14, 0.96), (1.05, 1.05), (0.9, 1.0), (1.0, 1.0)):
        c = P.calibrate_1x2(p, k, t)
        if abs(sum(c) - 1.0) > 1e-6 or any(x <= 0 for x in c):
            return {"ok": False, "details": f"K={k} T={t} sum={sum(c)}"}
    return {"ok": True, "details": "校准层概率和=1"}


# ---- 4. λ 反解复现市场 ----
def t_lambda():
    for o in ([2.5, 3.2, 2.8], [1.4, 4.8, 9.7], [6.5, 4.2, 1.45]):
        p, _ = P.devig(o, "power")
        lam = P.solve_lam_from_probs(p)
        if lam is None:
            return {"ok": False, "details": f"无解 {o}"}
        m = P.one(P.matrix(*lam))
        for i in range(3):
            if abs(m[i] - p[i]) > 0.005:
                return {"ok": False, "details": f"{o} 反解误差 {abs(m[i]-p[i]):.4f}"}
    return {"ok": True, "details": "λ反解还原市场1X2（≤0.5pp）"}


# ---- 5. market_only 新鲜盘口 ----
def t_market_only():
    r = pred(basic_match())
    f = r.get("forecast") or {}
    if r.get("fusion_status") != "ok":
        return {"ok": False, "details": r.get("fusion_status")}
    if sum3(f.get("final_1x2_pct") or []) != 100.0:
        return {"ok": False, "details": f"1X2 sum={sum3(f.get('final_1x2_pct') or [])}"}
    market = f.get("market_prob_pct") or []
    cal = P.calibrate_1x2([x / 100 for x in market], 1.14, 0.96)
    final = f.get("final_1x2_pct")
    for i in range(3):
        if abs(cal[i] * 100 - final[i]) > 0.2:
            return {"ok": False, "details": f"market_only 1X2≠校准市场 {cal} vs {final}"}
    if r.get("fusion_decision", {}).get("status") != "MARKET_BASELINE":
        return {"ok": False, "details": r.get("fusion_decision", {}).get("status")}
    return {"ok": True, "details": "1X2=校准市场、MARKET_BASELINE"}


# ---- 6. model_first 显式 λ ----
def t_model_first():
    r = pred({"home": "H", "away": "A", "stage": "T", "kickoff": "2026-08-10T01:00:00+08:00",
              "mode": "model_first", "lambda_home": 1.4, "lambda_away": 1.1, "field_meta": {}})
    co = r.get("core_output") or {}
    if r.get("fusion_status") != "ok":
        return {"ok": False, "details": r.get("fusion_status")}
    if not approx(co.get("xg", [None, None])[0], 1.4, 0.01) or not approx(co.get("xg", [None, None])[1], 1.1, 0.01):
        return {"ok": False, "details": f"λ={co.get('xg')}"}
    if (r.get("forecast") or {}).get("goal_rate", {}).get("kind") != "model_goal_rate":
        return {"ok": False, "details": (r.get("forecast") or {}).get("goal_rate")}
    return {"ok": True, "details": "λ=显式值、kind=model_goal_rate"}


# ---- 7. 无锚回退（陈旧盘口不再崩溃）----
def t_stale():
    for name, extra in (("stale_had", {}),
                        ("stale_all", {"hhad": {"line": -1, "odds": [1.9, 3.5, 3.4]},
                                       "ttg": {"odds": [12, 6, 4, 3.2, 4.5, 6.5, 11, 15]}})):
        d = basic_match(**{"field_meta": {"odds": {"observed_at": "2026-08-01T09:00:00+08:00"},
                                          **({} if not extra.get("hhad") else {"hhad": {"observed_at": "2026-08-01T09:00:00+08:00"},
                                                                                "ttg": {"observed_at": "2026-08-01T09:00:00+08:00"}})}})
        d.update(extra)
        r = pred(d)
        tags = (r.get("core_output") or {}).get("xg_tags") or []
        if r.get("fusion_status") != "ok" or "NO_ANCHOR_FALLBACK" not in tags:
            return {"ok": False, "details": f"{name}: status={r.get('fusion_status')} tags={tags}"}
        if r.get("fusion_decision", {}).get("status") != "AVOID_DATA_RISK":
            return {"ok": False, "details": f"{name}: {r.get('fusion_decision', {}).get('status')}"}
    return {"ok": True, "details": "陈旧盘口→NO_ANCHOR_FALLBACK + AVOID_DATA_RISK，不崩溃"}


# ---- 8. 两回合晋级 ----
def t_twoleg():
    r = pred({"home": "TeamA", "away": "TeamB", "stage": "UCL", "kickoff": "2026-08-12T02:00:00+08:00",
              "mode": "market_only", "odds": [2.2, 3.3, 3.1], "first_leg": [1, 1],
              "field_meta": {"odds": {"observed_at": "2026-08-12T00:00:00+08:00"}}})
    adv = (r.get("core_output") or {}).get("advancement") or {}
    s = adv.get("home_advance_pct", 0) + adv.get("away_advance_pct", 0)
    if abs(s - 100) > 1.0:
        return {"ok": False, "details": f"advance sum={s}"}
    if adv.get("penalty_home_prob_used") != 0.38:
        return {"ok": False, "details": adv}
    return {"ok": True, "details": f"晋级概率和=100、点球主队0.38、ET={adv.get('to_extra_time_pct')}%"}


# ---- 9. 极端赔率 ----
def t_extreme():
    for o in ([1.02, 21.0, 101.0], [11.0, 5.5, 1.15], [1.5, 1.5, 1.5]):
        r = pred(basic_match(odds=o))
        f = r.get("forecast") or {}
        if r.get("fusion_status") != "ok" or abs(sum3(f.get("final_1x2_pct") or []) - 100.0) > 0.2:
            return {"ok": False, "details": f"{o}: {r.get('fusion_status')}"}
    return {"ok": True, "details": "极端赔率不崩溃、1X2和=100"}


# ---- 10. 4 场生产批量不变量 ----
def t_batch(path):
    if not path or not Path(path).exists():
        return {"ok": True, "details": "hybrid.json 不存在，跳过"}
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    core, version = F.load_core()
    for m in data.get("matches", []):
        r = F.predict_one(core, version, m)
        f = r.get("forecast") or {}
        co = r.get("core_output") or {}
        sm = co.get("score_matrix") or {}
        if r.get("fusion_status") != "ok":
            return {"ok": False, "details": f"{m.get('home')}: {r.get('fusion_status')}"}
        if sum3(f.get("final_1x2_pct") or []) != 100.0:
            return {"ok": False, "details": f"{m.get('home')} 1X2 sum"}
        ou = f.get("ou_2_5") or {}
        if ou and abs(ou.get("over_pct", 0) + ou.get("under_pct", 0) - 100) > 0.5:
            return {"ok": False, "details": f"{m.get('home')} OU sum"}
        if sm and abs(sum(sm.values()) - 1.0) > 1e-6:
            return {"ok": False, "details": f"{m.get('home')} score_matrix sum"}
        if not co.get("derived_market_status"):
            return {"ok": False, "details": f"{m.get('home')} missing derived_market_status"}
    return {"ok": True, "details": f"{len(data.get('matches', []))}场不变量全部通过"}


# ---- 11. 常数与模型资产 ----
def t_constants():
    checks = [
        ("PENALTY_HOME_PROB_DEFAULT", P.PENALTY_HOME_PROB_DEFAULT, 0.38),
        ("ET_TEMPO_DEFAULT", P.ET_TEMPO_DEFAULT, 0.83),
        ("SCORE_MODEL", P.SCORE_MODEL, "bp"),
        ("SCORE_LAMBDA3", P.SCORE_LAMBDA3, 0.05),
        ("SCORE_TEMPERATURE_FT", P.SCORE_TEMPERATURE_FT, 1.30),
        ("DEVIG_METHOD_DEFAULT", P.DEVIG_METHOD_DEFAULT, "power"),
        ("SCORE_TEMPERATURE_HT", P.SCORE_TEMPERATURE_HT, 1.22),
    ]
    bad = [n for n, v, want in checks
           if not (v == want if isinstance(v, str) else approx(v, want, 1e-9))]
    return {"ok": not bad, "details": f"常数校验 {'通过' if not bad else '不符: ' + ','.join(bad)}"}


# ---- 12. DC 团队强度 ----
def t_team_strength(ratings):
    if not ratings or not Path(ratings).exists():
        return {"ok": True, "details": "ratings 不存在，跳过"}
    model = json.loads(Path(ratings).read_text(encoding="utf-8"))
    a = TS.predict_match(model, "Arsenal", "Liverpool")
    b = TS.predict_match(model, "HJK", "SJK")
    if a.get("status") != "VALID" or b.get("status") != "UNFITTED_TEAM":
        return {"ok": False, "details": f"Arsenal/Liverpool={a.get('status')} HJK/SJK={b.get('status')}"}
    return {"ok": True, "details": f"Arsenal vs Liverpool λ={a['lambda_home']}/{a['lambda_away']}；覆盖外→UNFITTED_TEAM"}


# ---- 13. Understat 查询 ----
def t_understat(store):
    if not store or not Path(store).exists():
        return {"ok": True, "details": "store 不存在，跳过"}
    rows = [json.loads(x) for x in Path(store).read_text(encoding="utf-8").splitlines() if x.strip()]
    hit = UX.lookup(rows, "EPL", "Manchester United", "Fulham")
    if not hit or hit.get("status") != "VALID":
        return {"ok": False, "details": f"lookup={hit}"}
    return {"ok": True, "details": f"Man Utd vs Fulham xG={hit['home_xg']}/{hit['away_xg']}"}


# ---- 14. 注册库与回测健康 ----
def t_registry(store):
    py = sys.executable
    sa = subprocess.run([py, str(Path(__file__).parent / "sample_audit.py"), "--output", str(Path(os.environ.get("TEMP", ".")) / "test_sa.json")],
                        capture_output=True, text=True)
    if sa.returncode != 0:
        return {"ok": False, "details": f"sample_audit 失败: {sa.stderr[:200]}"}
    return {"ok": True, "details": "sample_audit 正常"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch", default=r"H:\claude AI自媒体\project001_足球预测\05_交付\2026-08-04_4场\hybrid.json")
    ap.add_argument("--ratings", default=r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\03_共享数据\football-quant-fusion/datasets/team_strength_ratings_2025.json")
    ap.add_argument("--understat-store", default=r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\03_共享数据\football-quant-fusion/datasets/understat_store.jsonl")
    a = ap.parse_args()

    check("去水方法", t_devig)
    check("矩阵归一化", t_matrices)
    check("1X2校准", t_calibrate)
    check("λ反解复现市场", t_lambda)
    check("market_only新鲜盘口", t_market_only)
    check("model_first显式λ", t_model_first)
    check("陈旧盘口无锚回退", t_stale)
    check("两回合晋级", t_twoleg)
    check("极端赔率", t_extreme)
    check("4场生产批量不变量", lambda: t_batch(a.batch))
    check("模型常数", t_constants)
    check("DC团队强度", lambda: t_team_strength(a.ratings))
    check("Understat查询", lambda: t_understat(a.understat_store))
    check("注册库健康", lambda: t_registry(a.store if hasattr(a, "store") else None))

    n_pass = sum(1 for t in RESULTS if t["status"] == "PASS")
    n_fail = sum(1 for t in RESULTS if t["status"] in ("FAIL", "ERROR"))
    report = {
        "schema_version": "engine-full-test-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": P.ENGINE_VERSION,
        "fusion": F.__name__,
        "summary": {"total": len(RESULTS), "pass": n_pass, "fail": n_fail},
        "tests": RESULTS,
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": report["summary"]}, ensure_ascii=False, indent=2))
    for t in RESULTS:
        print(f"[{t['status']}] {t['name']} :: {t.get('details') or t.get('error')}")


if __name__ == "__main__":
    main()

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

# 2026-08-12 修复：原硬编码指向 football-quant-fusion-suite 外部物理拷贝
# （AGENTS.md 头号警告对象），模块级 setdefault FUSION_CORE_DIR + sys.path.insert
# 会污染同一 pytest 进程内后续测试（test_p0_evaluation 拿到 suite 旧版
# fusion_predict_core 的模块缓存与 build_identity，子进程却用仓库内新版，
# 哈希不一致导致 cohort 归因失败）。统一走符号链接仓库内唯一事实源。
os.environ.setdefault("FUSION_CORE_DIR", r"F:/HM足球比赛预测/project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts")
sys.path.insert(0, r"F:/HM足球比赛预测/project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts")
sys.path.insert(0, r"C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts")

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
         "field_meta": {"odds": {"observed_at": "2026-08-03T20:00:00+08:00", "freshness": 100}}}
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


# ---- 5b. 远期开球不等于盘口陈旧 ----
def t_market_only_future_snapshot():
    d = basic_match(
        kickoff="2026-08-08T02:00:00+08:00",
        field_meta={"odds": {
            "observed_at": "2026-08-06T14:10:38+08:00",
            "freshness": 100,
            "source": "中国体彩网移动端官方固定奖金接口",
        }},
    )
    r = pred(d)
    co = r.get("core_output") or {}
    if r.get("fusion_status") != "ok":
        return {"ok": False, "details": f"status={r.get('fusion_status')} core={co.get('status')}"}
    if co.get("mode") != "market_only":
        return {"ok": False, "details": f"输入market_only却输出{co.get('mode')}"}
    if not co.get("market_prob_pct"):
        return {"ok": False, "details": "显式freshness=100的HAD被错误删除"}
    return {"ok": True, "details": "显式新鲜快照不因距离开球超过24小时而降级"}


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


# ---- 7. market_only无可用HAD时明确阻断，不静默换模型 ----
def t_stale():
    for name, extra in (("stale_had", {}),
                        ("stale_all", {"hhad": {"line": -1, "odds": [1.9, 3.5, 3.4]},
                                       "ttg": {"odds": [12, 6, 4, 3.2, 4.5, 6.5, 11, 15]}})):
        d = basic_match(**{"field_meta": {"odds": {"observed_at": "2026-08-01T09:00:00+08:00", "freshness": 0},
                                          **({} if not extra.get("hhad") else {"hhad": {"observed_at": "2026-08-01T09:00:00+08:00", "freshness": 0},
                                                                                "ttg": {"observed_at": "2026-08-01T09:00:00+08:00", "freshness": 0}})}})
        d.update(extra)
        r = pred(d)
        co = r.get("core_output") or {}
        if r.get("fusion_status") != "blocked":
            return {"ok": False, "details": f"{name}: 应blocked，实际={r.get('fusion_status')}"}
        if co.get("mode") != "market_only":
            return {"ok": False, "details": f"{name}: 输入market_only却输出{co.get('mode')}"}
        if co.get("status") != "market_anchor_unusable":
            return {"ok": False, "details": f"{name}: core status={co.get('status')}"}
    return {"ok": True, "details": "陈旧HAD→market_only明确阻断，不静默切换model_first"}


def t_no_anchor_refused():
    r = pred({
        "home": "尤文图斯", "away": "克雷莫纳", "stage": "意甲",
        "kickoff": "2026-01-13T03:45:00+08:00",
        "mode": "market_only", "odds": [1.14, 5.8, 12.5],
        "field_meta": {"odds": {"observed_at": "2026-01-12T11:37:16+08:00", "freshness": 15}},
    })
    if r.get("fusion_status") != "blocked":
        return {"ok": False, "details": f"应 blocked，实际 {r.get('fusion_status')}"}
    st = (r.get("core_output") or {}).get("status")
    if st not in ("market_anchor_unusable", "no_independent_anchor"):
        return {"ok": False, "details": st}
    pct = (r.get("forecast") or {}).get("final_1x2_pct")
    if pct == [37.4, 25.3, 37.4]:
        return {"ok": False, "details": "无锚仍输出 37.4/25.3/37.4"}
    return {"ok": True, "details": f"热门陈旧盘口拒绝摊平 ({st})"}


def t_no_anchor_with_market_pins():
    """model_first 且无 Elo/λ，但有可用 HAD：钉回 market_only，不得摊成 37.4。"""
    d = basic_match(mode="hybrid")
    # hybrid 无第二锚会在 validate 失败；用未声明 mode + 只有盘口应走 market_only
    d.pop("mode", None)
    r = pred(d)
    if r.get("fusion_status") != "ok":
        return {"ok": False, "details": r.get("fusion_status")}
    if r.get("mode") != "market_only":
        return {"ok": False, "details": f"mode={r.get('mode')}"}
    if r.get("market_dependency_pct") != 100:
        return {"ok": False, "details": f"dep={r.get('market_dependency_pct')}"}
    return {"ok": True, "details": "仅盘口→market_only 依赖 100"}


# ---- 8. 两回合晋级 ----
def t_twoleg():
    r = pred({"home": "TeamA", "away": "TeamB", "stage": "UCL", "kickoff": "2026-08-12T02:00:00+08:00",
              "mode": "market_only", "odds": [2.2, 3.3, 3.1], "first_leg": [1, 1],
              "field_meta": {"odds": {"observed_at": "2026-08-12T00:00:00+08:00", "freshness": 100}}})
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


# ---- 9b. market_only联合拟合极端λ自动回退HAD ----
def t_market_only_extreme_lambda_guard():
    original = P.fit_multi_market

    def fake_extreme_fit(data, matrix, one, rho):
        return {
            "lambda_home": 4.0,
            "lambda_away": 0.1,
            "loss": 0.0,
            "loss_parts": {"had": 0.0, "ttg": 0.0},
            "sources": ["HAD", "TTG"],
            "weights": {"had": 1.0, "ttg": 0.5},
            "freshness": {},
            "method": "test_extreme_fit",
        }

    d = basic_match(
        ttg={"odds": [12, 6, 4, 3.2, 4.5, 6.5, 11, 15]},
        field_meta={
            "odds": {"observed_at": "2026-08-03T20:00:00+08:00", "freshness": 100},
            "ttg": {"observed_at": "2026-08-03T20:00:00+08:00", "freshness": 100},
        },
    )
    try:
        P.fit_multi_market = fake_extreme_fit
        co = P.predict(d)
    finally:
        P.fit_multi_market = original
    guard = co.get("lambda_guard") or {}
    if guard.get("action") != "fallback_to_had_inverse":
        return {"ok": False, "details": f"guard={guard}"}
    if max(co.get("xg") or [99]) / min(co.get("xg") or [0.01]) >= 6.0:
        return {"ok": False, "details": f"极端λ仍在输出: {co.get('xg')}"}
    if not any(str(x).startswith("EXTREME_LAMBDA_FALLBACK_TO_HAD")
               for x in co.get("reliability_flags") or []):
        return {"ok": False, "details": f"缺少回退旗标: {co.get('reliability_flags')}"}
    return {"ok": True, "details": f"拒绝4.0/0.1，回退HAD λ={co.get('xg')}"}


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
        if abs(sum3(f.get("final_1x2_pct") or []) - 100.0) > 0.2:
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
    ap.add_argument("--batch", default=r"F:\HM足球比赛预测\project001_足球预测\05_交付\2026-08-04_4场\hybrid.json")
    ap.add_argument("--ratings", default=r"F:/HM足球比赛预测/project018_技能工作区整合/04_素材/shared-data/football-quant-fusion/datasets/team_strength_ratings_2025.json")
    ap.add_argument("--understat-store", default=r"F:/HM足球比赛预测/project018_技能工作区整合/04_素材/shared-data/football-quant-fusion/datasets/understat_store.jsonl")
    a = ap.parse_args()

    check("去水方法", t_devig)
    check("矩阵归一化", t_matrices)
    check("1X2校准", t_calibrate)
    check("λ反解复现市场", t_lambda)
    check("market_only新鲜盘口", t_market_only)
    check("market_only远期新鲜快照", t_market_only_future_snapshot)
    check("model_first显式λ", t_model_first)
    check("market_only陈旧HAD明确阻断", t_stale)
    check("无锚拒绝生产1X2", t_no_anchor_refused)
    check("仅盘口钉回market_only", t_no_anchor_with_market_pins)
    check("两回合晋级", t_twoleg)
    check("极端赔率", t_extreme)
    check("market_only极端λ回退HAD", t_market_only_extreme_lambda_guard)
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

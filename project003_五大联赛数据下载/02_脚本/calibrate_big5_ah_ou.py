#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五大联赛全盘口校准研究（big5_clean.jsonl，Pinnacle 收盘）。
协议：按日期时间切分 70/30（时间序列），train 上拟合、test 上报告。
盘口：
  1) 1X2 K/T 网格（draw_k x temperature，同 calibrate_league_kt.py 口径，作为复核）；
  2) 大小球 2.5 Platt（对 devig 后 over 概率做 logistic 校准）；
  3) 亚盘 Platt（0.5 步长整半盘，对 devig 后 home-cover 概率做校准；整数盘遇 push 剔除）。
对照：raw（去水后市场概率） vs calibrated。
CLV 代理：test 中"覆盖方"的收盘赔率均值（非真 CLV，仅价值参考）。
用法：python calibrate_big5_ah_ou.py
"""
from __future__ import annotations
import json
import math
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/skills/zu-yu-dashi-3/scripts")
from odds_methods import devig
from predict import calibrate_1x2
ROOT = Path(r"H:\claude AI自媒体\project003_五大联赛数据下载")
CLEAN = ROOT / "04_素材" / "big5_clean.jsonl"
OUT = ROOT / "05_交付" / "big5_ah_ou_calibration.json"
LEAGUES = ["ENG", "ESP", "ITA", "GER", "FRA"]
def metrics_binary(pred, y):
    n = len(pred)
    bs = sum((p - t) ** 2 for p, t in zip(pred, y)) / n
    ll = sum(-math.log(max(1e-12, p if t == 1 else 1 - p)) for p, t in zip(pred, y)) / n
    hit = sum(int((p >= 0.5) == (t == 1)) for p, t in zip(pred, y)) / n
    obs = []
    for p, t in zip(pred, y):
        obs += [(p, 1.0 if t == 1 else 0.0), (1 - p, 1.0 if t == 0 else 0.0)]
    ece = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        g = [(x, z) for x, z in obs if lo <= x < (hi if b < 9 else 1.000001)]
        if not g:
            continue
        ap = sum(x for x, _ in g) / len(g)
        aa = sum(z for _, z in g) / len(g)
        ece += len(g) / len(obs) * abs(ap - aa)
    return {"n": n, "brier": round(bs, 6), "logloss": round(ll, 6),
            "accuracy_pct": round(hit * 100, 2), "ece": round(ece, 6)}
def platt_fit(x, y):
    best = None
    for a in [v / 100.0 for v in range(10, 401, 5)]:
        for b in [v / 100.0 for v in range(-300, 301, 10)]:
            loss = 0.0
            for xi, yi in zip(x, y):
                z = a * math.log(max(1e-12, xi) / max(1e-12, 1 - xi)) + b
                p = 1.0 / (1.0 + math.exp(-z))
                loss += -math.log(max(1e-12, p if yi == 1 else 1 - p))
            if best is None or loss < best[0]:
                best = (loss, a, b)
    return best[1], best[2]
def platt_apply(x, a, b):
    out = []
    for xi in x:
        z = a * math.log(max(1e-12, xi) / max(1e-12, 1 - xi)) + b
        out.append(1.0 / (1.0 + math.exp(-z)))
    return out
def split70(rows):
    def key(r):
        d = r.get("date") if isinstance(r, dict) else r[0].get("date")
        return d or ""
    rows = sorted(rows, key=key)
    cut = int(len(rows) * 0.7)
    return rows[:cut], rows[cut:]
def calibrate_ou(rows, lg):
    use = [r for r in rows if r.get("pinnacle_close_ou25")]
    if len(use) < 200:
        return {"n": len(use), "note": "样本不足(<200)"}
    train, test = split70(use)
    x_tr = [devig(r["pinnacle_close_ou25"], "power")[0][0] for r in train]
    x_te = [devig(r["pinnacle_close_ou25"], "power")[0][0] for r in test]
    y_tr = [1 if sum(r["ft"]) > 2.5 else 0 for r in train]
    y_te = [1 if sum(r["ft"]) > 2.5 else 0 for r in test]
    a, b = platt_fit(x_tr, y_tr)
    return {
        "n": len(use), "train_n": len(train), "test_n": len(test),
        "platt": {"a": round(a, 3), "b": round(b, 3)},
        "raw_test": metrics_binary(x_te, y_te),
        "calibrated_test": metrics_binary(platt_apply(x_te, a, b), y_te),
        "over_rate": round(sum(y_te) / len(y_te) * 100, 2),
    }
def calibrate_ah(rows, lg):
    use = []
    pushes = 0
    for r in rows:
        ah = r.get("pinnacle_close_ah")
        if not ah:
            continue
        line, hg, ag = ah["line"], r["ft"][0], r["ft"][1]
        diff = hg + line - ag
        if abs(diff) < 1e-9:
            pushes += 1
            continue
        use.append((r, 1 if diff > 0 else 0))
    if len(use) < 200:
        return {"n": len(use), "pushes": pushes, "note": "样本不足(<200)"}
    train, test = split70(use)
    x_tr = [devig([r["pinnacle_close_ah"]["home"], r["pinnacle_close_ah"]["away"]], "power")[0][0] for r, _ in train]
    x_te = [devig([r["pinnacle_close_ah"]["home"], r["pinnacle_close_ah"]["away"]], "power")[0][0] for r, _ in test]
    y_tr = [y for _, y in train]
    y_te = [y for _, y in test]
    a, b = platt_fit(x_tr, y_tr)
    cal_te = platt_apply(x_te, a, b)
    clv = []
    for (r, y), p in zip(test, cal_te):
        ah = r["pinnacle_close_ah"]
        clv.append(ah["home"] if y == 1 else ah["away"])
    return {
        "n": len(use), "pushes": pushes, "train_n": len(train), "test_n": len(test),
        "platt": {"a": round(a, 3), "b": round(b, 3)},
        "raw_test": metrics_binary(x_te, y_te),
        "calibrated_test": metrics_binary(cal_te, y_te),
        "home_cover_rate": round(sum(y_te) / len(y_te) * 100, 2),
        "avg_covered_side_odds": round(sum(clv) / len(clv), 4),
    }
def calibrate_1x2_kt(rows, lg):
    use = [r for r in rows if r.get("pinnacle_close")]
    if len(use) < 200:
        return {"n": len(use), "note": "样本不足(<200)"}
    train, test = split70(use)
    def prep(sub):
        p = []
        i = []
        for r in sub:
            q, _ = devig(r["pinnacle_close"], "power")
            p.append(q)
            i.append(0 if r["ft"][0] > r["ft"][1] else (1 if r["ft"][0] == r["ft"][1] else 2))
        return p, i
    tr_p, tr_i = prep(train)
    te_p, te_i = prep(test)
    def m3(probs, idxs):
        n = len(probs)
        bs = sum(sum((p[k] - (1 if k == j else 0)) ** 2 for k in range(3)) for p, j in zip(probs, idxs)) / n
        ll = sum(-math.log(max(1e-12, p[j])) for p, j in zip(probs, idxs)) / n
        hit = sum(int(max(range(3), key=lambda k: p[k]) == j) for p, j in zip(probs, idxs)) / n
        obs = []
        for p, j in zip(probs, idxs):
            obs += [(p[k], 1 if k == j else 0) for k in range(3)]
        ece = 0.0
        for b in range(10):
            lo, hi = b / 10, (b + 1) / 10
            g = [(x, y) for x, y in obs if lo <= x < (hi if b < 9 else 1.000001)]
            if not g:
                continue
            ece += len(g) / len(obs) * abs(sum(x for x, _ in g) / len(g) - sum(z for _, z in g) / len(g))
        return {"n": n, "brier": round(bs, 6), "logloss": round(ll, 6),
                "accuracy_pct": round(hit * 100, 2), "ece": round(ece, 6)}
    best = None
    for k in [x / 100.0 for x in range(85, 141, 5)]:
        for t in [x / 100.0 for x in range(85, 121, 5)]:
            m = m3([calibrate_1x2(p, k, t) for p in tr_p], tr_i)
            if best is None or m["ece"] < best[2]["ece"]:
                best = (k, t, m)
    k, t, _ = best
    return {
        "n": len(use), "train_n": len(train), "test_n": len(test),
        "fitted": {"draw_k": k, "temperature": t, "test": m3([calibrate_1x2(p, k, t) for p in te_p], te_i)},
        "default_114_096_test": m3([calibrate_1x2(p, 1.14, 0.96) for p in te_p], te_i),
        "no_cal_test": m3([calibrate_1x2(p, 1.0, 1.0) for p in te_p], te_i),
        "raw_market_test": m3(te_p, te_i),
    }
def main():
    rows = [json.loads(x) for x in CLEAN.read_text(encoding="utf-8").splitlines() if x.strip()]
    by_lg = {lg: [r for r in rows if r["league"] == lg] for lg in LEAGUES}
    rep = {
        "schema_version": "big5-full-odds-calibration-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "protocol": "chronological 70/30; 1X2 grid by train ECE; OU/AH Platt grid by train logloss; test reported",
        "source": "big5_odds_full.csv -> big5_clean.jsonl (Pinnacle 收盘)",
        "leagues": {},
    }
    for lg in LEAGUES:
        lg_rows = by_lg[lg]
        rep["leagues"][lg] = {
            "n": len(lg_rows),
            "x1x2_kt": calibrate_1x2_kt(lg_rows, lg),
            "ou25": calibrate_ou(lg_rows, lg),
            "ah": calibrate_ah(lg_rows, lg),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    for lg, v in rep["leagues"].items():
        kt = v["x1x2_kt"]; ou = v["ou25"]; ah = v["ah"]
        print(f"--- {lg} (n={v['n']}) ---")
        if "note" in kt:
            print("  1X2 KT:", kt.get("note"))
        else:
            f = kt["fitted"]
            print(f"  1X2 KT: K={f['draw_k']} T={f['temperature']} test ECE fitted={f['test']['ece']} "
                  f"default(1.14/0.96)={kt['default_114_096_test']['ece']} nocal={kt['no_cal_test']['ece']} "
                  f"raw={kt['raw_market_test']['ece']}")
        if "note" in ou:
            print("  OU2.5:", ou.get("note"))
        else:
            print(f"  OU2.5: n={ou['n']} a={ou['platt']['a']} b={ou['platt']['b']} | raw ECE={ou['raw_test']['ece']} "
                  f"cal ECE={ou['calibrated_test']['ece']} | raw Brier={ou['raw_test']['brier']} cal Brier={ou['calibrated_test']['brier']}")
        if "note" in ah:
            print("  AH:", ah.get("note"))
        else:
            print(f"  AH: n={ah['n']} (push={ah['pushes']}) a={ah['platt']['a']} b={ah['platt']['b']} | "
                  f"raw ECE={ah['raw_test']['ece']} cal ECE={ah['calibrated_test']['ece']} | "
                  f"raw Brier={ah['raw_test']['brier']} cal Brier={ah['calibrated_test']['brier']} | "
                  f"覆盖方均赔={ah['avg_covered_side_odds']}")
    print(json.dumps({"status": "ok", "output": str(OUT)}, ensure_ascii=False))
if __name__ == "__main__":
    main()

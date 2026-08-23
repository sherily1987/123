#!/usr/bin/env python3
"""calibrate_league_kt — 联赛 1X2 校准层（K/T）研究网格。

数据：fin_swe_bra_clean.jsonl（football-data /new/，Pinnacle 收盘 1X2 + 全场比分）。
协议：按开球日期时间切分 70/30；train 上网格选优（draw_k × temperature），test 上报告。
去水：power（当前生产默认）。
对照：默认体彩 K=1.14/T=0.96 与无校准 K=1.0/T=1.0。
另用体彩2026各联赛 50 场快照做外部 sanity（样本小，仅参考）。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import core_scripts_dir  # noqa: E402
# 2026-08-16：原硬编码指向外部 football-quant-fusion-suite 的 zu-yu-dashi-3 物理拷贝
# （靠人工 cp 同步、历史上真的漂移过）。改走 core_scripts_dir()，默认仓库内唯一事实源。
sys.path.insert(0, str(core_scripts_dir()))
from odds_methods import devig
from predict import calibrate_1x2


def parse_day(value):
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date().toordinal()
        except ValueError:
            continue
    return None


def metrics(probs, idxs):
    obs = []
    bs = []
    ll = []
    hit = []
    for p, i in zip(probs, idxs):
        obs += [(p[k], 1 if k == i else 0) for k in range(3)]
        bs.append(sum((p[k] - (1 if k == i else 0)) ** 2 for k in range(3)))
        ll.append(-math.log(max(1e-12, p[i])))
        hit.append(int(max(range(3), key=lambda k: p[k]) == i))
    n = len(probs)
    ece = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        g = [(x, y) for x, y in obs if lo <= x < (hi if b < 9 else 1.000001)]
        if not g:
            continue
        ap = sum(x[0] for x in g) / len(g)
        aa = sum(x[1] for x in g) / len(g)
        ece += len(g) / len(obs) * abs(ap - aa)
    return {
        "n": n, "brier_mean": round(sum(bs) / n, 6),
        "log_loss": round(sum(ll) / n, 6),
        "accuracy_pct": round(sum(hit) / n * 100, 2),
        "ece": round(ece, 6),
    }


def run_league(rows, method="power"):
    rows = sorted(rows, key=lambda r: r["day"])
    split = int(len(rows) * 0.7)
    train, test = rows[:split], rows[split:]

    def prep(sub):
        probs_raw = []
        idxs = []
        for r in sub:
            p, _ = devig(r["pinnacle_close"], method)
            probs_raw.append(p)
            idxs.append(0 if r["ft"][0] > r["ft"][1] else (1 if r["ft"][0] == r["ft"][1] else 2))
        return probs_raw, idxs

    tr_p, tr_i = prep(train)
    te_p, te_i = prep(test)
    best = None
    for k in [x / 100.0 for x in range(85, 141, 5)]:
        for t in [x / 100.0 for x in range(85, 121, 5)]:
            m = metrics([calibrate_1x2(p, k, t) for p in tr_p], tr_i)
            if best is None or m["ece"] < best[2]["ece"]:
                best = (k, t, m)
    k, t, _ = best
    cal_te = metrics([calibrate_1x2(p, k, t) for p in te_p], te_i)
    def_te = metrics([calibrate_1x2(p, 1.14, 0.96) for p in te_p], te_i)
    nocal_te = metrics([calibrate_1x2(p, 1.0, 1.0) for p in te_p], te_i)
    raw_te = metrics(te_p, te_i)
    # A calibration candidate must not regress on any held-out metric.  The
    # small tolerance prevents floating-point/sample noise from becoming a
    # false rejection, while keeping the decision auditable and research-only.
    delta_vs_raw = {
        metric: round(cal_te[metric] - raw_te[metric], 6)
        for metric in ("brier_mean", "log_loss", "ece")
    }
    regression_tolerance = 0.0005
    no_op = k == 1.0 and t == 1.0
    admission = "no_op" if no_op else ("candidate" if all(
        delta <= regression_tolerance for delta in delta_vs_raw.values()
    ) else "hold")
    return {
        "league": rows[0]["league"], "n": len(rows), "train_n": len(train), "test_n": len(test),
        "date_range": [datetime.fromordinal(rows[0]["day"]).strftime("%Y-%m-%d"),
                       datetime.fromordinal(rows[-1]["day"]).strftime("%Y-%m-%d")],
        "fitted": {"draw_k": k, "temperature": t, "train_metrics": best[2], "test_metrics": cal_te},
        "default_other": {"draw_k": 1.14, "temperature": 0.96, "test_metrics": def_te},
        "no_cal": {"draw_k": 1.0, "temperature": 1.0, "test_metrics": nocal_te},
        "raw_market": {"test_metrics": raw_te},
        "candidate_review": {
            "decision": admission,
            "delta_fitted_minus_raw": delta_vs_raw,
            "regression_tolerance": regression_tolerance,
            "production_authorized": False,
            "reason": ("fitted parameters equal no-calibration baseline; no probability change"
                       if admission == "no_op" else
                       "all held-out Brier/LogLoss/ECE deltas within tolerance; "
                       "requires separate release review" if admission == "candidate" else
                       "at least one held-out metric regressed beyond tolerance"),
        },
    }


def sporttery_sanity(hist_path, fitted):
    """体彩快照外部 sanity：应用拟合 K/T vs 默认 vs 无校准（样本小，仅参考）。"""
    data = json.loads(Path(hist_path).read_text(encoding="utf-8"))
    rows = {"芬超": [], "瑞超": []}
    for m in data.get("matches", []):
        lg = m.get("leagueAbbName")
        if lg not in rows:
            continue
        had = m.get("closing_had")
        res = m.get("sectionsNo999")
        if not had or not res or ":" not in res:
            continue
        try:
            odds = [float(had[0]), float(had[1]), float(had[2])]
            h, a = map(int, res.split(":"))
        except Exception:
            continue
        rows[lg].append({"odds": odds, "idx": 0 if h > a else (1 if h == a else 2)})
    out = {}
    for lg, rows_lg in rows.items():
        if len(rows_lg) < 20:
            out[lg] = {"n": len(rows_lg), "note": "样本不足，仅列数量"}
            continue
        p_raw = [devig(r["odds"], "power")[0] for r in rows_lg]
        i = [r["idx"] for r in rows_lg]
        k, t = fitted.get(lg, (1.14, 0.96))
        out[lg] = {
            "n": len(rows_lg),
            "raw": metrics(p_raw, i),
            "with_fitted_kt": metrics([calibrate_1x2(p, k, t) for p in p_raw], i),
            "with_default_kt": metrics([calibrate_1x2(p, 1.14, 0.96) for p in p_raw], i),
            "fitted_used": [k, t],
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="fin_swe_bra_clean.jsonl")
    ap.add_argument("--sporttery-history", help="体彩历史 JSON（sanity）")
    ap.add_argument("--output", required=True)
    ap.add_argument("--leagues", nargs="*", default=["FIN", "SWE", "BRA"],
                    help="要评估的 league 代码；默认 FIN SWE BRA，可传 ENG ESP GER ITA FRA 等")
    a = ap.parse_args()
    rows = []
    for line in Path(a.input).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        day = parse_day(r.get("date"))
        odds = r.get("pinnacle_close")
        ft = r.get("ft")
        if day is None or not odds or not ft:
            continue
        if any(x is None or x <= 1.0 for x in odds):
            continue
        rows.append({"league": r["league"], "day": day, "ft": [int(ft[0]), int(ft[1])],
                     "pinnacle_close": [float(x) for x in odds]})
    requested = [str(league).upper() for league in a.leagues]
    available = {lg: [r for r in rows if r["league"] == lg] for lg in requested}
    # Keep small/empty queues visible rather than failing or silently dropping
    # a league; a minimum of 20 is only a reporting floor, not an admission gate.
    league_reports = {}
    for lg, league_rows in available.items():
        if len(league_rows) < 20:
            league_reports[lg] = {
                "league": lg, "n": len(league_rows), "candidate_review": {
                    "decision": "insufficient_sample", "production_authorized": False,
                    "reason": "fewer_than_20_rows_for_chronological_split",
                }
            }
        else:
            league_reports[lg] = run_league(league_rows)
    rep = {
        "schema_version": "league-kt-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devig_method": "power",
        "protocol": "chronological 70/30; grid fit by train ECE; test reported",
        "requested_leagues": requested,
        "leagues": league_reports,
    }
    if a.sporttery_history:
        fitted = {
            lg: (value["fitted"]["draw_k"], value["fitted"]["temperature"])
            for lg, value in league_reports.items() if "fitted" in value
        }
        rep["sporttery_sanity"] = sporttery_sanity(
            a.sporttery_history,
            {"芬超": fitted["FIN"], "瑞超": fitted["SWE"]}
            if "FIN" in fitted and "SWE" in fitted else {})
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    for lg, v in rep["leagues"].items():
        if "fitted" not in v:
            print(f"{lg}: {v['candidate_review']['decision']} | n={v.get('n', 0)}")
            continue
        f = v["fitted"]
        print(f"{lg}: {v['candidate_review']['decision']} | K={f['draw_k']} T={f['temperature']} | test ECE fitted={f['test_metrics']['ece']} "
              f"default(1.14/0.96)={v['default_other']['test_metrics']['ece']} nocal={v['no_cal']['test_metrics']['ece']} "
              f"raw={v['raw_market']['test_metrics']['ece']} | n={v['n']}")
    print(json.dumps({"status": "ok", "output": a.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()

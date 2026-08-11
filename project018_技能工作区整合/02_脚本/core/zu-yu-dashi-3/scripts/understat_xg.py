#!/usr/bin/env python3
"""understat_xg — Understat 真实 xG 通道（R2②）。

数据：understat/matches.json（3503 场五大联赛，含 home/away xG、进球与博彩 forecast）。
功能：
1) --build-store：规范化输出 store.jsonl；
2) --lookup：按 联赛/主客队/日期 查 xG 对（供 model_first λ 或 λ prior）；
3) --validate：xG-as-λ（Dixon-Coles）vs 实际 vs Understat 博彩 forecast 的 Brier/LogLoss/ECE，
   并按时间切分评估 xG 是否需要简单缩放校准。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/skills/zu-yu-dashi-3/scripts")
from predict import matrix as dc_matrix, one as dc_one

RHO = -0.08
LEAGUE_CN = {"EPL": "英超", "La_liga": "西甲", "Bundesliga": "德甲", "Serie_A": "意甲", "Ligue_1": "法甲"}


def parse_dt(s):
    return datetime.strptime(str(s).strip()[:19], "%Y-%m-%d %H:%M:%S")


def build_store(matches_path):
    rows = []
    for m in json.loads(Path(matches_path).read_text(encoding="utf-8")):
        try:
            rows.append({
                "league": m.get("league"), "season": str(m.get("season")),
                "datetime": m.get("datetime"), "home": m.get("home"), "away": m.get("away"),
                "home_xg": float(m["home_xg"]), "away_xg": float(m["away_xg"]),
                "home_goals": int(m["home_goals"]), "away_goals": int(m["away_goals"]),
                "forecast": [float(m["forecast_home"]), float(m["forecast_draw"]), float(m["forecast_away"])],
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def lookup(rows, league, home, away, date=None):
    cands = [r for r in rows
             if (league is None or r["league"] == league)
             and r["home"].lower() == home.lower() and r["away"].lower() == away.lower()]
    if date:
        d0 = str(date)[:10]
        cands = [r for r in cands if r["datetime"][:10] == d0]
    if not cands:
        return None
    cands.sort(key=lambda r: r["datetime"])
    r = cands[-1]
    return {
        "status": "VALID", "league": r["league"], "datetime": r["datetime"],
        "home": r["home"], "away": r["away"],
        "lambda_home": round(r["home_xg"], 4), "lambda_away": round(r["away_xg"], 4),
        "home_xg": r["home_xg"], "away_xg": r["away_xg"],
        "source": "understat",
    }


def metrics(rows, key_probs):
    obs = []
    bs = []
    ll = []
    hit = []
    for r in rows:
        p = r[key_probs]
        i = r["actual_idx"]
        obs += [(p[k], 1 if k == i else 0) for k in range(3)]
        bs.append(sum((p[k] - (1 if k == i else 0)) ** 2 for k in range(3)))
        ll.append(-math.log(max(1e-12, p[i])))
        hit.append(int(max(range(3), key=lambda k: p[k]) == i))
    n = len(rows)
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
        "n": n, "brier_mean": round(sum(bs) / n, 6), "log_loss": round(sum(ll) / n, 6),
        "accuracy_pct": round(sum(hit) / n * 100, 2), "ece": round(ece, 6),
    }


def validate(rows, scale_grid=(0.9, 1.0, 1.1, 1.2)):
    rows = sorted(rows, key=lambda r: r["datetime"])
    split = int(len(rows) * 0.7)
    train, test = rows[:split], rows[split:]

    def prepare(sub, scale):
        out = []
        for r in sub:
            p = dc_one(dc_matrix(r["home_xg"] * scale, r["away_xg"] * scale, RHO))
            r["model_xg"] = p
            r["actual_idx"] = 0 if r["home_goals"] > r["away_goals"] else (1 if r["home_goals"] == r["away_goals"] else 2)
            f = r["forecast"]
            s = sum(f)
            r["market"] = [x / s for x in f]
            out.append(r)
        return out

    best = None
    for sc in scale_grid:
        tr = prepare(train, sc)
        m = metrics(tr, "model_xg")
        if best is None or m["brier_mean"] < best[1]["brier_mean"]:
            best = (sc, m)
    sc, _ = best
    tr = prepare(train, sc)
    te = prepare(test, sc)
    by_league = {}
    for r in te:
        by_league.setdefault(r["league"], []).append(r)
    return {
        "n": len(rows), "train_n": len(train), "test_n": len(test),
        "best_scale": sc,
        "test": {
            "xg_model": metrics(te, "model_xg"),
            "market": metrics(te, "market"),
            "by_league": {k: {"n": len(v), "xg_model": metrics(v, "model_xg"),
                              "market": metrics(v, "market")} for k, v in by_league.items()},
        },
        "note": "xG-as-λ 未经任何盘口信息；market 为 Understat 内置博彩 forecast。",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-store", action="store_true")
    ap.add_argument("--matches", help="understat/matches.json")
    ap.add_argument("--store", help="store.jsonl")
    ap.add_argument("--lookup", action="store_true")
    ap.add_argument("--league")
    ap.add_argument("--home")
    ap.add_argument("--away")
    ap.add_argument("--date")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--output")
    a = ap.parse_args()

    if a.build_store:
        rows = build_store(a.matches)
        Path(a.store).parent.mkdir(parents=True, exist_ok=True)
        with open(a.store, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(json.dumps({"status": "ok", "n": len(rows), "store": a.store}, ensure_ascii=False))
        return

    rows = []
    if Path(a.store).exists():
        rows = [json.loads(x) for x in Path(a.store).read_text(encoding="utf-8").splitlines() if x.strip()]
    if a.lookup:
        print(json.dumps(lookup(rows, a.league, a.home, a.away, a.date), ensure_ascii=False, indent=2))
        return
    if a.validate:
        rep = validate(rows)
        rep["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if a.output:
            Path(a.output).parent.mkdir(parents=True, exist_ok=True)
            Path(a.output).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return
    ap.print_help()


if __name__ == "__main__":
    main()

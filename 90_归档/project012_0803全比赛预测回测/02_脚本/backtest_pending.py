#!/usr/bin/env python3
"""待回测记录自动回测：统计胜平负/比分命中率。

读取 04_素材/待回测记录/20260803/ 下的登记记录，从引擎 results 目录取官方赛果
（赛果由 fusion_cli.py settle 或 daily-pipeline 自动回填），计算：
- 胜平负（1X2 argmax）命中率：总体 + 分联赛
- 比分命中率：Top1 / Top3
- 未结算（not_finished）场次单独列出

用法:
  python backtest_pending.py                     # 默认回测整个待回测目录
  python backtest_pending.py --records-dir 04_素材/待回测记录/20260803
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
RESULTS = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest\results")


def idx_1x2(h, a):
    return "H" if h > a else ("D" if h == a else "A")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records-dir", default=str(PROJ / "04_素材" / "待回测记录" / "20260803"))
    ap.add_argument("--results-dir", default=str(RESULTS))
    ap.add_argument("--output")
    a = ap.parse_args()
    records = []
    for p in sorted(Path(a.records_dir).glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(rec, dict) and rec.get("match_id") and "output" in rec:
            records.append(p)
    results_dir = Path(a.results_dir)

    by_league = {}
    pending = []
    x1_stats = {"n": 0, "hit": 0}
    score_stats = {"n": 0, "top1": 0, "top3": 0}
    detail = []

    for rf in records:
        rec = json.loads(rf.read_text(encoding="utf-8"))
        out = rec.get("output") or {}
        core = out.get("core_output") or {}
        forecast = out.get("forecast") or {}
        pct = core.get("final_1x2_pct") or forecast.get("final_1x2_pct") or []
        tops = [x["score"] for x in (core.get("top_scores") or forecast.get("top_scores") or [])]
        rp = results_dir / f"{rec['match_id']}.json"
        if not rp.exists():
            pending.append(rec["match_id"])
            detail.append({"match_id": rec["match_id"], "match": f"{rec['match']['home']} vs {rec['match']['away']}",
                           "status": "not_finished"})
            continue
        rs = json.loads(rp.read_text(encoding="utf-8"))
        sc = rs.get("score_90") or {}
        if sc.get("home") is None or sc.get("away") is None:
            pending.append(rec["match_id"])
            detail.append({"match_id": rec["match_id"], "match": f"{rec['match']['home']} vs {rec['match']['away']}",
                           "status": "not_finished"})
            continue
        actual = f"{sc['home']}-{sc['away']}"
        pred_1x2 = ["H", "D", "A"][max(range(3), key=lambda j: pct[j])] if len(pct) == 3 else None
        hit_1x2 = pred_1x2 == idx_1x2(sc["home"], sc["away"])
        hit_t1 = tops and tops[0] == actual
        hit_t3 = actual in tops[:3]
        lg = (rec.get("match") or {}).get("competition", "未知")
        by_league.setdefault(lg, {"n": 0, "hit": 0})
        x1_stats["n"] += 1
        x1_stats["hit"] += 1 if hit_1x2 else 0
        by_league[lg]["n"] += 1
        by_league[lg]["hit"] += 1 if hit_1x2 else 0
        score_stats["n"] += 1
        score_stats["top1"] += 1 if hit_t1 else 0
        score_stats["top3"] += 1 if hit_t3 else 0
        detail.append({
            "match_id": rec["match_id"],
            "match": f"{rec['match']['home']} vs {rec['match']['away']}",
            "league": lg, "pred_1x2": pred_1x2, "actual": actual, "1x2_hit": hit_1x2,
            "pred_top3": tops[:3], "score_top1_hit": hit_t1, "score_top3_hit": hit_t3,
            "status": "settled",
        })

    def pct(n, d):
        return round(n / d * 100, 2) if d else None

    report = {
        "schema": "pending-backtest-1.0", "records_dir": a.records_dir,
        "generated_at": json.loads((Path(a.records_dir) / "index.json").read_text(encoding="utf-8"))["generated_at"]
        if (Path(a.records_dir) / "index.json").exists() else None,
        "summary": {
            "total_records": len(records),
            "settled": x1_stats["n"],
            "not_finished": len(pending),
            "x1x2": {"n": x1_stats["n"], "hit": x1_stats["hit"],
                     "hit_rate_pct": pct(x1_stats["hit"], x1_stats["n"])},
            "score": {"n": score_stats["n"], "top1_hit": score_stats["top1"],
                      "top1_hit_rate_pct": pct(score_stats["top1"], score_stats["n"]),
                      "top3_hit": score_stats["top3"],
                      "top3_hit_rate_pct": pct(score_stats["top3"], score_stats["n"])},
        },
        "by_league": {lg: {"n": v["n"], "hit": v["hit"],
                           "hit_rate_pct": pct(v["hit"], v["n"])} for lg, v in by_league.items()},
        "pending": pending,
        "detail": detail,
    }
    if a.output:
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

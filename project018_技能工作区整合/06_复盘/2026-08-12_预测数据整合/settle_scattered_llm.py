# -*- coding: utf-8 -*-
"""2026-08-12 预测数据整合：散落 LLM 轨回测结算（一次性工具，不进入生产套件）。

背景：主库 1550 条预测（459 唯一比赛）已由 fusion_backtest.py 结算（latest_before_kickoff）。
散落于 6 个待回测目录的 LLM 轨记录（llm-track-1.0 / 双轨四玩法 / band-trial）因旧格式
index.json 缺 identity 字段，backtest_dual_track.py 的 quant 门禁拒绝整场（含 LLM 侧）。
本脚本只结算 LLM 侧：direction(双选/单选) + score_picks(Top1/Top3)，赛果用官方 90 分钟。

只读：index_llm.json / llm_*.json / results/*.json。只写输出文件。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest\results")

SCATTERED = [
    ("project012_20260803", Path(r"F:\HM足球比赛预测\90_归档\project012_0803全比赛预测回测\04_素材\待回测记录\20260803")),
    ("project014", Path(r"F:\HM足球比赛预测\90_归档\project014_football-quant-fusion\04_素材\待回测记录")),
    ("今日推荐_20260808", Path(r"F:\HM足球比赛预测\project001_足球预测\05_交付\今日推荐_20260808\待回测记录\20260808")),
    ("双轨四玩法_20260809", Path(r"F:\HM足球比赛预测\project001_足球预测\05_交付\今日推荐_双轨四玩法_20260809\待回测记录\20260809")),
    ("双轨四玩法_20260810", Path(r"F:\HM足球比赛预测\project001_足球预测\05_交付\今日推荐_双轨四玩法_20260810\待回测记录\20260810")),
]


def parse_pick_letters(s: str) -> set:
    m = re.search(r"[（(]([HDA/]+)[）)]", s or "")
    if not m:
        return set()
    return {c for c in m.group(1).split("/") if c in "HDA"}


def parse_single_letter(s: str) -> str | None:
    m = re.search(r"[（(]([HDA])[）)]", s or "")
    return m.group(1) if m else None


def actual_1x2(h: int, a: int) -> str:
    return "H" if h > a else ("D" if h == a else "A")


def result_90(res: dict):
    s = res.get("score_90")
    if not isinstance(s, dict) or s.get("home") is None:
        return None
    return int(s["home"]), int(s["away"])


def load_llm_records(d: Path):
    """从 index_llm.json（含 llm_file 指向）或直接扫描 llm_*.json 提取。"""
    out = {}
    idx_path = d / "index_llm.json"
    if idx_path.exists():
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        for r in idx.get("records", []):
            mid = str(r.get("match_id", "")).split("__")[0]
            if not mid:
                continue
            pick = r.get("llm_pick", "")
            single = None
            f = r.get("llm_file")
            if f:
                p = Path(f)
                if not p.is_absolute():
                    p = d / p
                if p.exists():
                    try:
                        rec = json.loads(p.read_text(encoding="utf-8"))
                        pick = rec.get("direction", {}).get("pick", pick)
                        single = rec.get("direction", {}).get("single_preference")
                    except Exception:
                        pass
            out[mid] = {
                "match_num": r.get("match_num"),
                "pick": pick,
                "double": parse_pick_letters(pick),
                "single": parse_single_letter(single) if single else parse_single_letter(pick),
                "score_picks": r.get("llm_score_picks", []),
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    detail = []
    stats = {
        "llm_double": {"n": 0, "hit": 0},
        "llm_single": {"n": 0, "hit": 0},
        "score_top1": {"n": 0, "hit": 0},
        "score_top3": {"n": 0, "hit": 0},
    }
    by_source = {}

    for label, d in SCATTERED:
        if not d.exists():
            continue
        src = by_source.setdefault(label, {"n": 0, "scored": 0})
        # project014 等目录含多日期子目录，递归收集全部 index_llm.json
        index_files = sorted(d.rglob("index_llm.json"))
        recs = {}
        for idxf in index_files:
            recs.update(load_llm_records(idxf.parent))
        if not index_files:
            # 无 index_llm 时直接扫 llm_*.json
            recs = load_llm_records(d)
        for mid, rec in recs.items():
            src["n"] += 1
            rp = RESULTS / f"{mid}.json"
            if not rp.exists():
                detail.append({"source": label, "match_id": mid, "status": "not_finished"})
                continue
            res = json.loads(rp.read_text(encoding="utf-8"))
            if res.get("status") != "finished" or res.get("settlement_scope") != "90min":
                detail.append({"source": label, "match_id": mid, "status": "not_eligible",
                               "reason": res.get("status")})
                continue
            sc = result_90(res)
            if sc is None:
                detail.append({"source": label, "match_id": mid, "status": "no_score90"})
                continue
            h, a = sc
            actual = actual_1x2(h, a)
            src["scored"] += 1

            double = rec.get("double") or set()
            single = rec.get("single")
            score_picks = rec.get("score_picks") or []
            actual_score = f"{h}-{a}"

            if double:
                stats["llm_double"]["n"] += 1
                if actual in double:
                    stats["llm_double"]["hit"] += 1
            if single:
                stats["llm_single"]["n"] += 1
                if actual == single:
                    stats["llm_single"]["hit"] += 1
            if score_picks:
                stats["score_top1"]["n"] += 1
                stats["score_top3"]["n"] += 1
                if score_picks[0] == actual_score:
                    stats["score_top1"]["hit"] += 1
                if actual_score in score_picks[:3]:
                    stats["score_top3"]["hit"] += 1

            detail.append({
                "source": label, "match_id": mid, "match_num": rec.get("match_num"),
                "actual": actual_score, "llm_pick": rec.get("pick"),
                "llm_double_hit": bool(double) and actual in double,
                "llm_single_hit": bool(single) and actual == single,
                "score_picks": score_picks,
            })

    def rate(s):
        return round(100.0 * s["hit"] / s["n"], 2) if s["n"] else None

    summary = {
        "schema": "scattered-llm-backtest-1.0",
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "stats": {k: {**v, "hit_rate_pct": rate(v)} for k, v in stats.items()},
        "by_source": by_source,
        "total_scored": sum(s["scored"] for s in by_source.values()),
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "detail": detail}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    if args.report:
        lines = ["# 散落 LLM 轨回测结算（2026-08-12 整合）", "",
                 f"- 结算场次：{summary['total_scored']}（官方 90 分钟）", ""]
        lines.append("| 指标 | n | 命中 | 命中率 |")
        lines.append("|---|---|---|---|")
        for k, v in summary["stats"].items():
            lines.append(f"| {k} | {v['n']} | {v['hit']} | {v['hit_rate_pct']}% |")
        lines.append("")
        lines.append("| 来源 | 记录数 | 已结算 |")
        lines.append("|---|---|---|")
        for k, v in summary["by_source"].items():
            lines.append(f"| {k} | {v['n']} | {v['scored']} |")
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

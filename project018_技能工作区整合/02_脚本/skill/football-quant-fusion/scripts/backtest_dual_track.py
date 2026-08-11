#!/usr/bin/env python3
"""双轨预测回测：量化轨道（1X2 argmax + 比分 Top1/Top3）vs LLM 轨道（双选/单选 + 比分）。

来源：2026-08-03 三场双轨试点后收编（project012/02_脚本/backtest_dual_track.py）。

读取：
- `04_素材/待回测记录/<日期>/index.json`：量化轨道登记索引（pipeline 生成）；
- 同目录 `index_llm.json`：LLM 轨道登记索引；
- 共享 `backtest/results/<match_id>.json`：官方赛果（由 fusion_cli.py settle 回填）。

输出：
- JSON：逐场明细 + 汇总命中率（量化 1X2 / LLM 双选 / LLM 单选 / 比分 Top1/Top3）；
- Markdown：双轨对比报告。

纪律：样本 <100 场不评价优劣、<200 场不宣称结论；本脚本只输出命中统计与分歧清单。

用法:
  python backtest_dual_track.py --date 20260803
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from runtime_paths import data_root

HERE = Path(__file__).resolve().parent
RESULTS = data_root() / "backtest" / "results"
OFFICIAL_90MIN_SOURCE = "中国体彩网移动端官方赛果"
USER_CONFIRMED_OFFICIAL = "user_confirmed_official_sporttery_result"
NON_90MIN_SEMANTIC_MARKERS = (
    "after et", "extra time", "加时", "after pen", "penalty", "点球",
    "postponed", "延期", "cancelled", "canceled", "取消", "awarded", "判罚",
)


def idx_1x2(h, a):
    return "H" if h > a else ("D" if h == a else "A")


def _contains_non_90min_semantics(value):
    """Reject result payloads that describe anything other than ordinary 90 minutes."""
    if isinstance(value, dict):
        return any(_contains_non_90min_semantics(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_non_90min_semantics(item) for item in value)
    return isinstance(value, str) and any(marker in value.lower() for marker in NON_90MIN_SEMANTIC_MARKERS)


def classify_settlement_provenance(result):
    """Classify result source; cross-validation never scores without full user attestation."""
    source = result.get("source")
    if isinstance(source, dict) and source.get("name") == OFFICIAL_90MIN_SOURCE:
        return {"eligible": True, "reason": None, "source_provenance_class": "official_sporttery"}
    confirmed = result.get("verified_by") == USER_CONFIRMED_OFFICIAL
    documented = all(isinstance(result.get(key), str) and result[key].strip()
                     for key in ("verification_note", "evidence_reference"))
    if confirmed and documented:
        return {"eligible": True, "reason": None, "source_provenance_class": "user_confirmed_official"}
    return {"eligible": False, "reason": "cross_validation_not_eligible",
            "source_provenance_class": "cross_validation_not_eligible"}


def validate_90min_settlement(result):
    """Return eligibility for scoring under the official 90-minute contract."""
    if result.get("status") != "finished":
        return {"eligible": False, "reason": "invalid_status"}
    if result.get("settlement_scope") != "90min":
        return {"eligible": False, "reason": "invalid_scope"}
    if _contains_non_90min_semantics(result):
        return {"eligible": False, "reason": "invalid_non_90min_semantics"}
    score = result.get("score_90")
    if not isinstance(score, dict) or any(
        not isinstance(score.get(side), int) or isinstance(score.get(side), bool) or score[side] < 0
        for side in ("home", "away")
    ):
        return {"eligible": False, "reason": "invalid_score"}
    if not classify_settlement_provenance(result)["eligible"]:
        return {"eligible": False, "reason": "invalid_source"}
    return {"eligible": True, "reason": None}


def official_half_time_score(result):
    """Only expose an official half-time score; never infer it from full time."""
    score = result.get("score_ht")
    if not isinstance(score, dict) or any(
        not isinstance(score.get(side), int) or isinstance(score.get(side), bool) or score[side] < 0
        for side in ("home", "away")
    ):
        return None
    return score


def parse_pick_letters(s):
    """从 '双选 主胜/平局（H/D）' 中提取 {H,D}。"""
    m = re.search(r"[（(]([HDA/]+)[）)]", s or "")
    if not m:
        return set()
    return {c for c in m.group(1).split("/") if c in "HDA"}


def parse_single_letter(s):
    m = re.search(r"[（(]([HDA])[）)]", s or "")
    return m.group(1) if m else None


IDENTITY_HASH_FIELDS = ("engine_bundle_sha256", "prediction_code_sha256", "config_sha256")


def validate_quant_identity(record):
    """Production statistics require a prematch market-baseline identity."""
    snapshot = record.get("snapshot", record.get("snapshot_type"))
    if snapshot != "prematch":
        return {"eligible": False, "reason": "identity_invalid_snapshot"}
    if record.get("route") != "market_baseline" and record.get("mode") != "market_only":
        return {"eligible": False, "reason": "identity_invalid_route_or_mode"}
    if not isinstance(record.get("prediction_as_of"), str) or not record["prediction_as_of"].strip():
        return {"eligible": False, "reason": "identity_missing_prediction_as_of"}
    identity = record.get("build_identity") or record.get("model") or record
    if any(not isinstance(identity.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", identity[key])
           for key in IDENTITY_HASH_FIELDS):
        return {"eligible": False, "reason": "identity_invalid_hashes"}
    return {"eligible": True, "reason": None}


def load_quant(records_dir):
    """从 index.json 读取量化登记（final_1x2_pct + top_score_1..3）。"""
    idx = json.loads((records_dir / "index.json").read_text(encoding="utf-8"))
    out = {}
    for r in idx.get("records", []):
        pct = r.get("final_1x2_pct") or []
        argmax = max(range(3), key=lambda i: pct[i]) if len(pct) == 3 else None
        out[r["match_id"]] = {
            "match_num": r.get("match_num"),
            "match": f"{r['home']} vs {r['away']}",
            "league": r.get("league"),
            "pred_1x2": "HDA"[argmax] if argmax is not None else None,
            "top_scores": [r.get("top_score_1"), r.get("top_score_2"), r.get("top_score_3")],
            "pct": pct,
            "eligibility": validate_quant_identity(r),
        }
    return out


def load_llm(records_dir):
    idx_path = records_dir / "index_llm.json"
    if not idx_path.exists():
        return {}
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    out = {}
    for r in idx.get("records", []):
        pick = r.get("llm_pick", "")
        single = None
        f = r.get("llm_file")
        if f:
            p = Path(f)
            if not p.is_absolute():
                p = records_dir / p
            if p.exists():
                rec = json.loads(p.read_text(encoding="utf-8"))
                pick = rec.get("direction", {}).get("pick", pick)
                single = rec.get("direction", {}).get("single_preference")
        out[r["match_id"]] = {
            "match_num": r.get("match_num"),
            "pick": pick,
            "double": parse_pick_letters(pick),
            "single": parse_single_letter(single) if single else parse_single_letter(pick),
            "score_picks": r.get("llm_score_picks", []),
            "note": r.get("note"),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="待回测目录日期，如 20260803")
    ap.add_argument("--records-dir", default=None)
    ap.add_argument("--results-dir", default=str(RESULTS))
    ap.add_argument("--output", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--match-id", action="append", default=None,
                    help="Only score these match ids (repeatable; used by auto primary evaluation).")
    a = ap.parse_args()

    if not a.records_dir and not a.date:
        raise SystemExit("必须提供 --records-dir 或 --date（默认从当前项目根目录的 04_素材/待回测记录/<date> 读取）")
    records_dir = Path(a.records_dir) if a.records_dir else Path.cwd() / "04_素材" / "待回测记录" / a.date
    results_dir = Path(a.results_dir)
    if not records_dir.exists():
        raise SystemExit(f"待回测记录目录不存在：{records_dir}")
    quant = load_quant(records_dir)
    llm_index_exists = (records_dir / "index_llm.json").exists()
    llm = load_llm(records_dir)
    match_ids = sorted(set(quant) | set(llm))
    if a.match_id:
        match_ids = [mid for mid in match_ids if mid in set(a.match_id)]

    stats = {
        "quant_1x2": {"n": 0, "hit": 0},
        "llm_double": {"n": 0, "hit": 0},
        "llm_single": {"n": 0, "hit": 0},
        "score_top1": {"n": 0, "hit": 0, "by_track": {"quant": {"n": 0, "hit": 0}, "llm": {"n": 0, "hit": 0}}},
        "score_top3": {"n": 0, "hit": 0, "by_track": {"quant": {"n": 0, "hit": 0}, "llm": {"n": 0, "hit": 0}}},
    }
    detail = []
    divergence = []

    for mid in match_ids:
        q = quant.get(mid)
        if q and not q["eligibility"]["eligible"]:
            detail.append({"match_id": mid, "status": "not_eligible", "reason": q["eligibility"]["reason"]})
            continue
        rp = results_dir / f"{mid}.json"
        if not rp.exists():
            detail.append({"match_id": mid, "status": "not_finished"})
            continue
        res = json.loads(rp.read_text(encoding="utf-8"))
        eligibility = validate_90min_settlement(res)
        provenance = classify_settlement_provenance(res)
        if not eligibility["eligible"]:
            detail.append({
                "match_id": mid, "status": "not_eligible",
                "reason": provenance["reason"] if eligibility["reason"] == "invalid_source" else eligibility["reason"],
                "source_provenance_class": provenance["source_provenance_class"],
            })
            continue
        actual = idx_1x2(res["score_90"]["home"], res["score_90"]["away"])
        actual_score = f"{res['score_90']['home']}-{res['score_90']['away']}"
        row = {
            "match_id": mid,
            "actual": actual_score,
            "actual_1x2": actual,
            "status": "settled",
            "source_provenance_class": provenance["source_provenance_class"],
        }
        if official_half_time_score(res) is None:
            row["half_time_status"] = "unresolved_missing_official_halftime_score"
            row["half_time_scored"] = False
        else:
            row["half_time_status"] = "settled_official_halftime_score"
            row["half_time_scored"] = True
            row["actual_ht"] = f"{res['score_ht']['home']}-{res['score_ht']['away']}"
        if not llm_index_exists:
            row["llm_track_status"] = "missing_index"
        if q:
            stats["quant_1x2"]["n"] += 1
            q_hit = q["pred_1x2"] == actual
            stats["quant_1x2"]["hit"] += int(q_hit)
            row["quant"] = {
                "match_num": q["match_num"],
                "match": q["match"],
                "pred_1x2": q["pred_1x2"],
                "hit": q_hit,
                "top_scores": q["top_scores"],
                "score_top1_hit": q["top_scores"][0] == actual_score,
                "score_top3_hit": actual_score in q["top_scores"],
            }
            for k in ("score_top1", "score_top3"):
                stats[k]["n"] += 1
                stats[k]["by_track"]["quant"]["n"] += 1
                if row["quant"][f"{k}_hit"]:
                    stats[k]["hit"] += 1
                    stats[k]["by_track"]["quant"]["hit"] += 1
        l = llm.get(mid)
        if l:
            row["llm"] = {
                "match_num": l["match_num"],
                "pick": l["pick"],
                "double": sorted(l["double"]),
                "single": l["single"],
                "double_hit": actual in l["double"] if l["double"] else None,
                "single_hit": l["single"] == actual if l["single"] else None,
                "score_picks": l["score_picks"],
                "score_top1_hit": (l["score_picks"] or ["?"])[0] == actual_score,
                "score_top3_hit": actual_score in l["score_picks"],
            }
            if l["double"]:
                stats["llm_double"]["n"] += 1
                stats["llm_double"]["hit"] += int(row["llm"]["double_hit"])
            if l["single"]:
                stats["llm_single"]["n"] += 1
                stats["llm_single"]["hit"] += int(row["llm"]["single_hit"])
            for k in ("score_top1", "score_top3"):
                stats[k]["by_track"]["llm"]["n"] += 1
                if row["llm"][f"{k}_hit"]:
                    stats[k]["by_track"]["llm"]["hit"] += 1
            if q and l and q["pred_1x2"] != l["single"] and l["single"]:
                divergence.append({
                    "match_id": mid,
                    "match": q["match"],
                    "quant": q["pred_1x2"],
                    "llm_single": l["single"],
                    "actual": actual,
                    "winner": "quant" if q["pred_1x2"] == actual else ("llm" if l["single"] == actual else "both_miss"),
                })
        detail.append(row)

    def rate(x):
        return round(100 * x["hit"] / x["n"], 2) if x["n"] else None

    provenance_counts = {
        "official_formal": sum(d.get("status") == "settled" for d in detail),
        "cross_validation": sum(d.get("source_provenance_class") == "cross_validation_not_eligible" for d in detail),
    }

    report = {
        "schema": "dual-track-backtest-1.0",
        "date": a.date,
        "records_dir": str(records_dir),
        "generated_at": None,
        "summary": {
            "settled": len([d for d in detail if d.get("status") == "settled"]),
            "settlement_provenance": provenance_counts,
            "quant_1x2": {"n": stats["quant_1x2"]["n"], "hit": stats["quant_1x2"]["hit"], "hit_rate_pct": rate(stats["quant_1x2"])},
            "llm_double": {"n": stats["llm_double"]["n"], "hit": stats["llm_double"]["hit"], "hit_rate_pct": rate(stats["llm_double"])},
            "llm_single": {"n": stats["llm_single"]["n"], "hit": stats["llm_single"]["hit"], "hit_rate_pct": rate(stats["llm_single"])},
            "score": {
                "top1": {"n": stats["score_top1"]["n"], "hit": stats["score_top1"]["hit"],
                         "hit_rate_pct": rate(stats["score_top1"]),
                         "quant": rate(stats["score_top1"]["by_track"]["quant"]),
                         "llm": rate(stats["score_top1"]["by_track"]["llm"])},
                "top3": {"n": stats["score_top3"]["n"], "hit": stats["score_top3"]["hit"],
                         "hit_rate_pct": rate(stats["score_top3"]),
                         "quant": rate(stats["score_top3"]["by_track"]["quant"]),
                         "llm": rate(stats["score_top3"]["by_track"]["llm"])},
            },
        },
        "divergence": divergence,
        "detail": detail,
        "caveat": "n=3 单日样本，不构成两轨优劣结论；按 SKILL 纪律累计 >=100 场评估命中率、>=200 场做结论。",
    }

    import datetime
    report["generated_at"] = datetime.datetime.now().astimezone().isoformat()

    out_path = Path(a.output) if a.output else Path.cwd() / "05_交付" / f"backtest_dual_track_{a.date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown 报告
    s = report["summary"]
    lines = [
        f"# 双轨预测回测报告（{a.date}）",
        "",
        f"- 已结算：{s['settled']} 场",
        f"- 量化轨道 1X2（argmax）：{s['quant_1x2']['hit']}/{s['quant_1x2']['n']}"
        f"（{s['quant_1x2']['hit_rate_pct']}%）",
        f"- LLM 轨道 双选：{s['llm_double']['hit']}/{s['llm_double']['n']}"
        f"（{s['llm_double']['hit_rate_pct']}%）；单选偏好：{s['llm_single']['hit']}/{s['llm_single']['n']}"
        f"（{s['llm_single']['hit_rate_pct']}%）",
        f"- 比分 Top1：{s['score']['top1']['hit']}/{s['score']['top1']['n']}"
        f"（量化 {s['score']['top1']['quant']}% / LLM {s['score']['top1']['llm']}%）",
        f"- 比分 Top3：{s['score']['top3']['hit']}/{s['score']['top3']['n']}"
        f"（量化 {s['score']['top3']['quant']}% / LLM {s['score']['top3']['llm']}%）",
        "",
        "## 逐场明细",
        "",
        "| 场次 | 赛果 | 量化1X2 | LLM双选 | LLM单选 | 量化比分Top3 | LLM比分Top3 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for d in detail:
        if d.get("status") != "settled":
            continue
        q = d.get("quant") or {}
        l = d.get("llm") or {}
        lines.append(
            f"| {q.get('match_num', l.get('match_num', d['match_id']))} "
            f"({q.get('match','')}) | {d['actual']} | {q.get('pred_1x2','-')} "
            f"{'✔' if q.get('hit') else '✘'} | {','.join(l.get('double') or []) or '-'} "
            f"{'✔' if l.get('double_hit') else '✘'} | {l.get('single') or '-'} "
            f"{'✔' if l.get('single_hit') else '✘'} | "
            f"{' '.join(x for x in (q.get('top_scores') or []) if x) or '-'} "
            f"{'✔' if q.get('score_top3_hit') else '✘'} | "
            f"{' '.join(x for x in (l.get('score_picks') or []) if x) or '-'} "
            f"{'✔' if l.get('score_top3_hit') else '✘'} |"
        )
    lines.append("")
    lines.append("## 分歧场次（量化 argmax vs LLM 单选偏好）")
    lines.append("")
    if report["divergence"]:
        lines.append("| 场次 | 量化 | LLM单选 | 实际 | 谁对 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for dv in report["divergence"]:
            lines.append(f"| {dv['match']} | {dv['quant']} | {dv['llm_single']} | {dv['actual']} | {dv['winner']} |")
    else:
        lines.append("无分歧场次。")
    lines.append("")
    lines.append("## 结论边界")
    lines.append("")
    lines.append(report["caveat"])
    lines.append("")
    lines.append("完整逐场数据见同目录 JSON。")
    report_path = Path(a.report) if a.report else out_path.with_name(out_path.stem + ".md")
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\n输出：{out_path}")
    print(f"报告：{report_path}")


if __name__ == "__main__":
    main()

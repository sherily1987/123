#!/usr/bin/env python3
"""影子 hybrid：不登记，不改当前生产概率。

对每场：生产保持 market_only；若路由器能给出 λ prior，另跑 --research-route，
结果写入工单 research.hybrid（research_only=true）。
赛后 --score 只评 hybrid 相对同场市场，不并入 current。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fusion_predict_core import load_core, predict_one
from intl_kelly_index import intl_kelly_for_match
from odds_movement_features import movement_feature
from job_ticket import (
    hybrid_from_fusion_output,
    identity_from,
    jobs_root,
    load_job,
    upsert_job,
)
from production_router import BIG5, GOALS_ONLY, load_event_rows, route_match
from runtime_paths import backtest_store, data_root, workspace_root
from sales_day_collect import build_field_meta


WEIGHT_SWEEP = (0.40, 0.50, 0.60, 0.70, 0.80)
LOCAL_MATCH_TZ = timezone(timedelta(hours=8))


def _parse_kickoff(value) -> datetime | None:
    """Parse Sporttery local timestamps and ISO timestamps into aware UTC time."""
    if not value:
        return None
    text = str(value).strip().replace("/", "-")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_MATCH_TZ)
    return dt.astimezone(timezone.utc)


def post_kickoff_reason(match: dict, *, now: datetime | None = None) -> str | None:
    kickoff = _parse_kickoff(match.get("kickoff") or match.get("kickoff_iso"))
    if kickoff is None:
        return "KICKOFF_TIME_UNPARSEABLE"
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return "POST_KICKOFF_NOT_USABLE" if observed.astimezone(timezone.utc) >= kickoff else None


def intl_store() -> Path:
    return data_root() / "odds" / "intl_production.jsonl"


def movement_store() -> Path:
    return data_root() / "odds" / "production_movement.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def default_events_path() -> str | None:
    folder = workspace_root() / "project021_五大联赛APIFootball训练" / "04_素材" / "标准化"
    return str(folder) if folder.is_dir() else None


def load_rows(path: str | Path | None) -> list:
    return load_event_rows(path)


def to_fusion_input(raw: dict, collected_at: str | None = None) -> dict:
    if raw.get("odds") and raw.get("home") and (raw.get("sporttery_meta") or raw.get("kickoff")):
        out = dict(raw)
        out.setdefault("mode", "market_only")
        return out
    now = collected_at or datetime.now(timezone.utc).isoformat()
    odds = raw.get("model_odds") or raw.get("odds")
    if not odds:
        raise ValueError("no odds")
    kickoff = raw.get("kickoff_iso") or raw.get("kickoff")
    d = {
        "home": raw["home"],
        "away": raw["away"],
        "competition": raw.get("league") or raw.get("competition"),
        "stage": raw.get("league") or raw.get("stage") or raw.get("competition"),
        "kickoff": kickoff,
        "mode": "market_only",
        "odds": list(odds)[:3],
        "context_confirmed": True,
        "prediction_as_of": now,
        "collected_at": now,
        "field_meta": build_field_meta(raw, now) if raw.get("match_id") else {},
        "assumptions": [],
        "sporttery_meta": {
            "match_id": raw.get("match_id") or (raw.get("sporttery_meta") or {}).get("match_id"),
            "match_num": raw.get("match_num") or (raw.get("sporttery_meta") or {}).get("match_num"),
        },
    }
    if raw.get("model_hhad"):
        d["hhad"] = raw["model_hhad"]
    if raw.get("hhad"):
        d["hhad"] = raw["hhad"]
    if isinstance(raw.get("ttg"), dict) and "odds" in raw["ttg"]:
        d["ttg"] = raw["ttg"]
    elif isinstance(raw.get("ttg"), dict) and all(k in raw["ttg"] for k in "0123456"):
        d["ttg"] = {"odds": [raw["ttg"][k] for k in ["0", "1", "2", "3", "4", "5", "6", "7+"]]}
    if isinstance(raw.get("hafu"), dict) and "odds" in raw["hafu"]:
        d["hafu"] = raw["hafu"]
    return d


def iter_matches(payload) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("matches"), list):
        return payload["matches"]
    if isinstance(payload, list):
        return payload
    return [payload]


def in_scope(match: dict) -> str | None:
    comp = str(match.get("competition") or match.get("stage") or match.get("league") or "").strip()
    if comp in BIG5 or comp in GOALS_ONLY:
        return None
    return f"league_not_in_scope:{comp or '?'}"


def brier(pct, actual_idx: int) -> float:
    probs = [float(x) / 100.0 if float(x) > 1.5 else float(x) for x in pct]
    return sum((p - (1.0 if i == actual_idx else 0.0)) ** 2 for i, p in enumerate(probs))


def actual_idx(score_90) -> int | None:
    if isinstance(score_90, dict) and score_90.get("home") is not None:
        h, a = int(score_90["home"]), int(score_90["away"])
    elif isinstance(score_90, str) and "-" in score_90:
        h, a = (int(x) for x in score_90.split("-", 1))
    else:
        return None
    return 0 if h > a else (2 if h < a else 1)


def _research_blob(match: dict, hybrid: dict) -> dict:
    """hybrid 数字与研究侧车打包；侧车不进 predict 输入。"""
    blob = dict(hybrid)
    blob["research_only"] = True
    blob["intl_kelly"] = intl_kelly_for_match(match, intl_store())
    blob["odds_movement"] = movement_feature(match, load_jsonl(movement_store()))
    return blob


def _attach_routing_audit(blob: dict, routed: dict, market_input: dict, research_run_at: str) -> dict:
    """Persist the time boundary used by the independent-prior router.

    The job's ``input`` deliberately remains the immutable market snapshot.
    The router works on a copy, so its no-future-leakage evidence must travel
    with the research sidecar instead of being silently discarded.
    """
    audit = ((routed.get("field_meta") or {}).get("production_router") or {})
    if audit:
        blob["routing_audit"] = dict(audit)
    blob["market_input_as_of"] = market_input.get("prediction_as_of") or market_input.get("collected_at")
    blob["research_run_at"] = research_run_at
    return blob


def weight_sweep(core, version, routed: dict, prior: dict, *, weights=WEIGHT_SWEEP) -> list[dict]:
    """Record alternative hybrid blends without mutating the primary route.

    Every candidate uses exactly the same independent prior, market snapshot
    and pre-match input; only ``market_weight`` differs.  They remain sidecar
    research rows until a time-separated, paired evaluation admits one.
    """
    variants: list[dict] = []
    for weight in weights:
        try:
            market_weight = float(weight)
        except (TypeError, ValueError):
            continue
        if not 0.0 <= market_weight <= 1.0:
            continue
        candidate = dict(routed)
        candidate["market_weight"] = market_weight
        out = predict_one(core, version, candidate)
        blob = hybrid_from_fusion_output(out, prior=prior)
        blob.update({"research_only": True, "market_weight": market_weight})
        variants.append(blob)
    return variants


def run_one(core, version, match: dict, understat, events, min_history: int, sales_day: str | None) -> dict:
    ident = identity_from(match)
    if sales_day:
        ident["sales_day"] = sales_day
    gate_reason = post_kickoff_reason(match)
    if gate_reason:
        return {"match_id": ident.get("match_id"), "status": "skipped", "reason": gate_reason}
    skip = in_scope(match)
    if skip:
        upsert_job(jobs_root(), ident, input_obj=match,
                   research=_research_blob(match, hybrid_from_fusion_output({}, skip_reason=skip)))
        return {"match_id": ident.get("match_id"), "status": "skipped", "reason": skip}

    research_run_at = datetime.now(timezone.utc).isoformat()
    routed = route_match(match, understat, events, min_history, enable_experimental=True)
    prior = routed.get("lambda_prior")
    if not prior or routed.get("research_only") is not True:
        reason = ((routed.get("field_meta") or {}).get("production_router") or {}).get("fallback_reason") or "no_prior"
        skipped_blob = _attach_routing_audit(
            _research_blob(match, hybrid_from_fusion_output({}, skip_reason=reason)),
            routed, match, research_run_at)
        upsert_job(jobs_root(), ident, input_obj=match,
                   research=skipped_blob)
        return {"match_id": ident.get("match_id"), "status": "skipped", "reason": reason}

    out = predict_one(core, version, routed)
    if out.get("research_only") is not True:
        out["research_only"] = True
    blob = _research_blob(match, hybrid_from_fusion_output(out, prior=prior))
    blob = _attach_routing_audit(blob, routed, match, research_run_at)
    blob["weight_sweep"] = weight_sweep(core, version, routed, prior)
    path = upsert_job(jobs_root(), ident, input_obj=match, research=blob)
    return {
        "match_id": ident.get("match_id"),
        "status": "ok" if out.get("fusion_status") == "ok" else out.get("fusion_status"),
        "job": str(path),
        "final_1x2_pct": blob.get("final_1x2_pct"),
        "dep": blob.get("market_dependency_pct"),
        "source": prior.get("source"),
    }


def score_day(sales_day: str) -> dict:
    root = jobs_root()
    store = backtest_store()
    day_dir = root / sales_day
    rows = []
    if not day_dir.exists():
        return {"sales_day": sales_day, "n": 0, "rows": []}
    for path in sorted(day_dir.glob("sporttery-*.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        hybrid = (job.get("research") or {}).get("hybrid") or {}
        pct = hybrid.get("final_1x2_pct")
        market = hybrid.get("market_1x2_pct")
        if not pct or not market or hybrid.get("skip_reason"):
            continue
        mid = (job.get("identity") or {}).get("match_id")
        result_path = store / "results" / f"{mid}.json"
        score = None
        if result_path.exists():
            score = (json.loads(result_path.read_text(encoding="utf-8")) or {}).get("score_90")
        if score is None and job.get("settlement"):
            score = job["settlement"].get("score_90")
        idx = actual_idx(score)
        if idx is None:
            continue
        quant = next((o for o in (job.get("outputs") or []) if o.get("track") == "quant"), None)
        qpct = (quant or {}).get("final_1x2_pct")
        row = {
            "match_id": mid,
            "match": f"{(job.get('identity') or {}).get('home')} vs {(job.get('identity') or {}).get('away')}",
            "actual_idx": idx,
            "brier_hybrid": round(brier(pct, idx), 4),
            "brier_market": round(brier(market, idx), 4),
            "brier_quant": round(brier(qpct, idx), 4) if qpct else None,
        }
        row["delta_hybrid_minus_market"] = round(row["brier_hybrid"] - row["brier_market"], 4)
        rows.append(row)
    n = len(rows)
    summary = {"sales_day": sales_day, "n": n, "rows": rows}
    if n:
        summary["mean_delta"] = round(sum(r["delta_hybrid_minus_market"] for r in rows) / n, 4)
        summary["hybrid_better"] = sum(1 for r in rows if r["delta_hybrid_minus_market"] < 0)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="影子 hybrid（research_only，不登记，不改生产概率）")
    ap.add_argument("--input", help="单场融合裸 dict / 批量 / 体彩 raw")
    ap.add_argument("--sales-day", help="工单日期；--score 时必填")
    ap.add_argument("--score", action="store_true", help="只评已落盘的 hybrid，不跑预测")
    ap.add_argument("--understat-store", default=str(data_root() / "datasets" / "understat_store.jsonl"))
    ap.add_argument("--apifootball-events", default=default_events_path(),
                    help="APIfootball/标准化事件 JSON/JSONL，或含 *_events.jsonl 的目录")
    ap.add_argument("--min-history", type=int, default=5)
    ap.add_argument("--output", help="摘要 JSON")
    args = ap.parse_args(argv)

    if args.score:
        if not args.sales_day:
            raise SystemExit("--score 需要 --sales-day")
        report = score_day(args.sales_day)
        text = json.dumps(report, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        return 0

    if not args.input:
        raise SystemExit("--input 或 --score 必须给一个")
    payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    sales_day = args.sales_day or payload.get("sales_day")
    understat = load_rows(args.understat_store)
    events = load_rows(args.apifootball_events)
    core, version = load_core()
    results = []
    for raw in iter_matches(payload):
        try:
            match = to_fusion_input(raw)
        except ValueError as exc:
            results.append({"status": "skipped", "reason": str(exc), "home": raw.get("home")})
            continue
        results.append(run_one(core, version, match, understat, events, args.min_history, sales_day))
    report = {
        "research_only": True,
        "model_version_window": "current production unchanged",
        "n": len(results),
        "ok": sum(1 for r in results if r.get("status") == "ok"),
        "skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

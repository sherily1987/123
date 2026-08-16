#!/usr/bin/env python3
"""比分 λ 来源研究：市场反解 vs 赛前代理 xG 强度。不改生产常数。

当场 *_xg.jsonl 是 POST_MATCH，不能直接当 λ。本脚本按生产协议滚动重拟合
（step=30、half_life=500、min_train=200）：只用开球日之前的进球/代理 xG
拟合团队强度，再预测该片的 λ。库内无 Understat 真实 xG。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import tune_score_params_by_league as base  # noqa: E402

ROOT = HERE.parents[1]
STRENGTH = ROOT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts"
if str(STRENGTH) not in sys.path:
    sys.path.insert(0, str(STRENGTH))
import team_strength as strength  # noqa: E402

STEP_DAYS = 30
HALF_LIFE = 500.0
MIN_TRAIN = 200
BLEND_W = 0.4
SCALE_GRID = (0.8, 0.9, 1.0, 1.1, 1.2)
MIN_TEST = base.MIN_TEST
LL_WIN = base.LL_WIN

GROUP_SLUGS = {
    "big5": ["premier_league", "la_liga", "bundesliga", "serie_a", "ligue_1"],
    "nordic": ["norway_eliteserien", "sweden_allsvenskan", "finland_veikkausliiga"],
    "j1": ["apisports_japan_j1_league"],
}
MARKET_FILE = {
    "apisports_japan_j1_league": "apisports_japan_j1_league_events_closing_attached.jsonl",
}


def market_file(slug: str) -> str:
    return MARKET_FILE.get(slug, f"{slug}_events_provider_market.jsonl")


def predict_lambda(model, home, away):
    idx = strength.team_index(model)
    i, j = idx.get(home), idx.get(away)
    if i is None or j is None:
        return None
    lh = math.exp(model["home_adv"] + model["alpha"][i] + model["beta"][j])
    la = math.exp(model["alpha"][j] + model["beta"][i])
    return float(lh), float(la)


def load_xg_map(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        val = rec.get("xg")
        if isinstance(val, list) and len(val) == 2:
            try:
                out[rec.get("match_id")] = [float(val[0]), float(val[1])]
            except (TypeError, ValueError):
                continue
    return out


def load_finished(path: Path, xg_map: dict) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        actual = rec.get("actual")
        if not (isinstance(actual, (list, tuple)) and len(actual) >= 2):
            continue
        try:
            h, a = int(actual[0]), int(actual[1])
        except (TypeError, ValueError):
            continue
        if h < 0 or a < 0:
            continue
        day = strength.parse_day(rec.get("kickoff"))
        if day is None:
            continue
        mid = rec.get("match_id")
        rows.append({
            "match_id": mid,
            "day": day,
            "day_iso": str(rec.get("kickoff") or "")[:10],
            "home": strength.team_key(rec, "home"),
            "away": strength.team_key(rec, "away"),
            "gh": h,
            "ga": a,
            "ft": (min(h, base.N - 1), min(a, base.N - 1)),
            "probs": base.market_probs(rec),
            "xg": xg_map.get(mid),
        })
    rows.sort(key=lambda r: (r["day"], str(r["match_id"])))
    return rows


def strength_rows(rows: list[dict], xg: bool) -> list[dict]:
    out = []
    for rec in rows:
        if xg:
            if not rec.get("xg"):
                continue
            gh, ga = rec["xg"]
        else:
            gh, ga = rec["gh"], rec["ga"]
        out.append({
            "home": rec["home"], "away": rec["away"],
            "gh": gh, "ga": ga, "day": rec["day"],
            "match_id": rec["match_id"],
        })
    return out


def first_fit_day(rows: list[dict], min_train: int) -> int | None:
    days = sorted({r["day"] for r in rows})
    for day in days:
        if sum(1 for r in rows if r["day"] < day) >= min_train:
            return day
    return None


def walk_lambdas(goals, xg_rows, eval_ids, step=STEP_DAYS, half_life=HALF_LIFE,
                 min_train=MIN_TRAIN, blend_w=BLEND_W):
    """滚动拟合。每片只用 day < point 的样本。返回 {match_id: {source: (lh,la)}}。"""
    eval_days = [m["day"] for m in goals if m["match_id"] in eval_ids]
    if not eval_days:
        return {}, []
    point = first_fit_day(goals, min_train)
    if point is None:
        return {}, []
    end_day = max(eval_days) + 1
    by_id = {m["match_id"]: m for m in goals}
    out, refits = {}, []
    while point < end_day:
        nxt = point + step
        chunk = [mid for mid in eval_ids
                 if mid in by_id and point <= by_id[mid]["day"] < nxt]
        if chunk:
            train_g = [m for m in goals if m["day"] < point]
            train_x = [m for m in xg_rows if m["day"] < point]
            model_g = (strength.fit_model(train_g, half_life=half_life)
                       if len(train_g) >= min_train else None)
            model_x = (strength.fit_model(train_x, half_life=half_life, target="xg")
                       if len(train_x) >= min_train else None)
            blended = (strength.blend_models(model_g, model_x, blend_w)
                       if model_g is not None and model_x is not None else None)
            refits.append({
                "point": point,
                "train_n_goals": len(train_g),
                "train_n_xg": len(train_x),
                "train_max_day": max((m["day"] for m in train_g), default=None),
                "chunk_n": len(chunk),
            })
            for mid in chunk:
                rec = by_id[mid]
                slot = {}
                if model_g is not None:
                    lam = predict_lambda(model_g, rec["home"], rec["away"])
                    if lam:
                        slot["goals"] = lam
                if model_x is not None:
                    lam = predict_lambda(model_x, rec["home"], rec["away"])
                    if lam:
                        slot["xg"] = lam
                if blended is not None:
                    lam = predict_lambda(blended, rec["home"], rec["away"])
                    if lam:
                        slot["blend"] = lam
                if slot:
                    out[mid] = slot
        point = nxt
    return out, refits


def slice_metrics(m, y):
    out = base.metrics(m, y)
    zz = (y[:, 0] == 0) & (y[:, 1] == 0)
    blow = (y[:, 0] >= 3) | (y[:, 1] >= 3)
    for name, mask in (("zero_zero", zz), ("blowout_3plus", blow)):
        if int(mask.sum()) == 0:
            out[name] = {"n": 0}
            continue
        idx = np.where(mask)[0]
        ll = float(-np.log(np.clip(m[idx, y[idx, 0], y[idx, 1]], 1e-12, 1.0)).mean())
        p00 = float(m[idx, 0, 0].mean()) if name == "zero_zero" else None
        out[name] = {
            "n": int(mask.sum()),
            "score_log_loss": round(ll, 5),
            "mean_p00": None if p00 is None else round(p00, 4),
        }
    return out


def scored(lh, la, y):
    return slice_metrics(
        base.temperature_scale(base.bp_matrices(lh, la, base.DEFAULT_LAM3), base.DEFAULT_T),
        y,
    )


def pick_scale(lh, la, y):
    best = None
    for s in SCALE_GRID:
        met = base.metrics(
            base.temperature_scale(
                base.bp_matrices(lh * s, la * s, base.DEFAULT_LAM3), base.DEFAULT_T),
            y,
        )
        row = {"scale": s, **met}
        if best is None or row["score_log_loss"] < best["score_log_loss"]:
            best = row
    return best


def decide_adopt(market_ll, cand_ll, cand_top3, market_top3, n_test):
    if n_test < MIN_TEST:
        return False, "too_small"
    dll = market_ll - cand_ll
    if dll >= LL_WIN:
        return True, f"test_log_loss_improved_{dll:.4f}"
    if dll >= 0 and cand_top3 - market_top3 >= 1.0:
        return True, "test_top3_plus_1pp_ll_not_worse"
    return False, "keep_market_lambda"


def load_league(norm: Path, slug: str) -> dict:
    xg_map = load_xg_map(norm / f"{slug}_xg.jsonl")
    events = norm / f"{slug}_events.jsonl"
    market = norm / market_file(slug)
    src = events if events.exists() else market
    if not src.exists():
        return {"slug": slug, "status": "missing_events"}
    rows = load_finished(src, xg_map)
    if market.exists() and market != src:
        by_id = {r["match_id"]: r for r in load_finished(market, xg_map)}
        for rec in rows:
            hit = by_id.get(rec["match_id"])
            if hit and hit.get("probs"):
                rec["probs"] = hit["probs"]
    market_n = sum(1 for r in rows if r["probs"])
    xg_n = sum(1 for r in rows if r.get("xg"))
    return {
        "slug": slug,
        "status": "ok",
        "n_finished": len(rows),
        "n_market": market_n,
        "n_xg": xg_n,
        "xg_basis": None,
        "rows": rows,
    }


def attach_xg_basis(norm: Path, league: dict) -> None:
    path = norm.parent.parent / "05_交付" / "league_xg_plan.json"
    if not path.exists():
        return
    plan = json.loads(path.read_text(encoding="utf-8")).get("leagues") or {}
    info = plan.get(league["slug"]) or {}
    league["xg_basis"] = info.get("basis")
    league["xg_plan_share"] = info.get("match_share")
    league["xg_plan_note"] = info.get("note")


def fit_group(leagues: list[dict]) -> dict:
    eval_rows = []
    coverage = []
    refit_n = 0
    for lg in leagues:
        if lg.get("status") != "ok":
            coverage.append({k: lg.get(k) for k in ("slug", "status")})
            continue
        rows = lg["rows"]
        marketable = [r for r in rows if r["probs"]]
        lh_m, la_m, kept = base.solve_lambdas(
            [{"probs": r["probs"], "ft": r["ft"], "day": r["day_iso"], "match_id": r["match_id"]}
             for r in marketable]
        )
        if not kept:
            coverage.append({"slug": lg["slug"], "status": "no_market_lambda"})
            continue
        id_to_row = {r["match_id"]: r for r in rows}
        eval_ids = {k["match_id"] for k in kept if k.get("match_id") in id_to_row}
        goals = strength_rows(rows, xg=False)
        xg_rows = strength_rows(rows, xg=True)
        print(f"  {lg['slug']} walk-forward market={len(eval_ids)} xg={len(xg_rows)}", flush=True)
        walked, refits = walk_lambdas(goals, xg_rows, eval_ids)
        refit_n += len(refits)
        for i, rec in enumerate(kept):
            mid = rec.get("match_id")
            ev = id_to_row.get(mid)
            if ev is None:
                continue
            slot = walked.get(mid) or {}
            item = {
                "day": rec["day"],
                "ft": rec["ft"],
                "market": (float(lh_m[i]), float(la_m[i])),
                "goals": slot.get("goals"),
                "xg": slot.get("xg"),
                "blend": slot.get("blend"),
                "oracle_xg": tuple(ev["xg"]) if ev.get("xg") else None,
                "slug": lg["slug"],
            }
            eval_rows.append(item)
        coverage.append({
            "slug": lg["slug"],
            "status": "ok",
            "finished": lg["n_finished"],
            "market": lg["n_market"],
            "xg_rows": lg["n_xg"],
            "xg_basis": lg.get("xg_basis"),
            "xg_plan_share": lg.get("xg_plan_share"),
            "walked": len(walked),
            "refits": len(refits),
        })
    eval_rows.sort(key=lambda r: r["day"])
    n = len(eval_rows)
    if n < MIN_TEST * 2:
        return {"status": "too_small", "n": n, "coverage": coverage, "refits": refit_n}
    split = int(n * 0.7)
    paired = [r for r in eval_rows if r["market"] and r["goals"] and r["xg"] and r["blend"]]
    if len(paired) < MIN_TEST * 2:
        return {
            "status": "too_small_paired",
            "n": n,
            "paired_n": len(paired),
            "coverage": coverage,
            "refits": refit_n,
            "split_day": eval_rows[split]["day"] if n else None,
        }
    split_day = eval_rows[split]["day"]
    train = [r for r in paired if r["day"] < split_day]
    test = [r for r in paired if r["day"] >= split_day]
    if len(test) < MIN_TEST:
        return {
            "status": "too_small_test",
            "n": n, "paired_n": len(paired),
            "train_n": len(train), "test_n": len(test),
            "coverage": coverage, "refits": refit_n, "split_day": split_day,
        }

    def stack(rows, key):
        arr = np.array([rows[0][key]] + [r[key] for r in rows[1:]], dtype=float)
        return arr[:, 0], arr[:, 1]

    y_tr = np.array([r["ft"] for r in train])
    y_te = np.array([r["ft"] for r in test])
    sources = {}
    for key, tune_scale in (("market", False), ("goals", False), ("xg", True), ("blend", True)):
        lh_tr, la_tr = stack(train, key)
        lh_te, la_te = stack(test, key)
        scale = 1.0
        train_pick = None
        if tune_scale:
            train_pick = pick_scale(lh_tr, la_tr, y_tr)
            scale = float(train_pick["scale"])
        sources[key] = {
            "scale": scale,
            "scale_selected_on": "train" if tune_scale else "fixed_1",
            "train_scale_pick": train_pick,
            "train": scored(lh_tr * scale, la_tr * scale, y_tr),
            "test": scored(lh_te * scale, la_te * scale, y_te),
        }
    oracle_tr = [r for r in train if r["oracle_xg"]]
    oracle_te = [r for r in test if r["oracle_xg"]]
    if oracle_tr and oracle_te:
        lh_otr, la_otr = stack(oracle_tr, "oracle_xg")
        lh_ote, la_ote = stack(oracle_te, "oracle_xg")
        sources["oracle_same_match_xg"] = {
            "leaked": True,
            "scale": 1.0,
            "n_train": len(oracle_tr),
            "n_test": len(oracle_te),
            "train": scored(lh_otr, la_otr, np.array([r["ft"] for r in oracle_tr])),
            "test": scored(lh_ote, la_ote, np.array([r["ft"] for r in oracle_te])),
        }

    market_te = sources["market"]["test"]
    best_name, best = None, None
    for name in ("xg", "blend"):
        te = sources[name]["test"]
        if best is None or te["score_log_loss"] < best["test"]["score_log_loss"]:
            best_name, best = name, sources[name]
    adopt, reason = decide_adopt(
        market_te["score_log_loss"], best["test"]["score_log_loss"],
        best["test"]["top3_acc_pct"], market_te["top3_acc_pct"],
        market_te["n"],
    )
    return {
        "status": "ok",
        "n_market_eval": n,
        "paired_n": len(paired),
        "train_n": len(train),
        "test_n": len(test),
        "first_day": paired[0]["day"],
        "last_day": paired[-1]["day"],
        "split_day": split_day,
        "coverage": coverage,
        "refits": refit_n,
        "sources": sources,
        "best_honest": best_name,
        "adopt_over_market": adopt,
        "adopt_reason": reason,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, default=base.PROJ)
    args = ap.parse_args()
    project = args.project.resolve()
    norm = project / "04_素材" / "标准化"
    report = {
        "schema": "score-xg-lambda-research-1.0",
        "research_only": True,
        "production_unchanged": "SCORE_MODEL=bp SCORE_LAMBDA3=0.05 SCORE_TEMPERATURE_FT=1.30",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "protocol": {
            "lambda_market": "1X2 invert",
            "lambda_xg": "walk_forward proxy_xg team_strength",
            "step_days": STEP_DAYS,
            "half_life": HALF_LIFE,
            "min_train": MIN_TRAIN,
            "blend_weight": BLEND_W,
            "scale_grid": list(SCALE_GRID),
            "real_xg": "unavailable_in_project021",
            "same_match_xg": "oracle_leaked_only",
        },
        "groups": {},
    }
    for name, slugs in GROUP_SLUGS.items():
        print(name, flush=True)
        leagues = []
        for slug in slugs:
            lg = load_league(norm, slug)
            attach_xg_basis(norm, lg)
            leagues.append(lg)
        result = fit_group(leagues)
        report["groups"][name] = {
            "slugs": slugs,
            "files": [market_file(s) for s in slugs],
            **{k: v for k, v in result.items()},
        }
        print(name, result.get("status"), "paired=", result.get("paired_n"),
              "adopt=", result.get("adopt_over_market"),
              "best=", result.get("best_honest"), flush=True)
    out = project / "05_交付" / "score_xg_lambda_research.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()

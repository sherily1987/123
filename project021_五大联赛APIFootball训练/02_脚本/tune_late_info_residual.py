#!/usr/bin/env python3
"""伤停/首发残差回测：只在赔率快照之后、开球之前进模型。不改生产。

伤停来源：体彩 getInjurySuspensionV1 前瞻（preview.json）。
首发：扫描 fusion 输出的 lineups_status；赛前 VALID 才能进残差。
当场事后伤停/阵容一律不算。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = ROOT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts"
STORE = ROOT / "project018_技能工作区整合" / "04_素材" / "shared-data" / "football-quant-fusion"
PROJ = ROOT / "project021_五大联赛APIFootball训练"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
import predict as P  # noqa: E402

CST = timezone(timedelta(hours=8))
MIN_TEST = 200
LL_WIN = 0.005
ABSENCE_KEYS = (
    "attack_absence_home", "attack_absence_away",
    "defense_absence_home", "defense_absence_away",
    "gk_absence_home", "gk_absence_away",
)


def parse_dt(value):
    if value in (None, ""):
        return None
    s = str(value).strip().replace("Z", "+00:00")
    dt = None
    if "T" in s:
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = None
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(s[:19] if fmt.endswith("%S") else s[:16], fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(timezone.utc)


def is_late_info(info_at, odds_at, kickoff) -> bool:
    if info_at is None or odds_at is None or kickoff is None:
        return False
    return odds_at < info_at < kickoff


def absence_dict(inj: dict) -> dict:
    out = {k: 0.0 for k in ABSENCE_KEYS}
    for side, sfx in (("home", "home"), ("away", "away")):
        block = (inj or {}).get(side) or {}
        for fld in ("attack_absence", "defense_absence", "gk_absence"):
            try:
                out[f"{fld}_{sfx}"] = float(block.get(fld) or 0)
            except (TypeError, ValueError):
                out[f"{fld}_{sfx}"] = 0.0
    return out


def absence_sum(adj: dict) -> float:
    return sum(float(adj.get(k) or 0) for k in ABSENCE_KEYS)


def brier(p, yidx: int) -> float:
    return sum((p[i] - (1.0 if i == yidx else 0.0)) ** 2 for i in range(3))


def log_loss(p, yidx: int) -> float:
    return -math.log(max(1e-12, p[yidx]))


def outcome_idx(h: int, a: int) -> int:
    return 0 if h > a else (1 if h == a else 2)


def metrics(rows: list[dict], key: str) -> dict:
    if not rows:
        return {"n": 0}
    bs = [r[key]["brier"] for r in rows]
    ll = [r[key]["log_loss"] for r in rows]
    hit = [int(r[key]["pick"] == r["y"]) for r in rows]
    return {
        "n": len(rows),
        "brier": round(sum(bs) / len(bs), 6),
        "log_loss": round(sum(ll) / len(ll), 6),
        "accuracy_pct": round(100.0 * sum(hit) / len(hit), 2),
    }


def decide_adopt(market_ll, adj_ll, n_test):
    if n_test < MIN_TEST:
        return False, "too_small"
    dll = market_ll - adj_ll
    if dll >= LL_WIN:
        return True, f"test_log_loss_improved_{dll:.4f}"
    return False, "keep_market_snapshot"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def discover_previews(roots: list[Path]) -> list[Path]:
    found = []
    for root in roots:
        if not root.exists():
            continue
        for name in ("preview.json", "hybrid_input.json"):
            found.extend(root.rglob(name))
    uniq, seen = [], set()
    for p in found:
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    uniq.sort(key=lambda p: (0 if p.name == "preview.json" else 1, str(p)))
    return uniq


def load_late_info_events(path: Path) -> list[dict]:
    out = []
    for rec in iter_jsonl(path):
        if rec.get("kind") != "injury":
            continue
        mid = rec.get("match_id")
        if mid is None:
            continue
        absn = rec.get("absence") or {}
        adj = {k: float(absn.get(k) or 0) for k in ABSENCE_KEYS}
        out.append({
            "match_id": int(mid),
            "home": rec.get("home"),
            "away": rec.get("away"),
            "kickoff": parse_dt(rec.get("kickoff")),
            "info_at": parse_dt(rec.get("collected_at")),
            "absence": adj,
            "source": str(path),
            "injury_count": int((absn.get("home") or {}).get("count") or 0)
            + int((absn.get("away") or {}).get("count") or 0),
        })
    return out


def preview_matches(path: Path) -> list[dict]:
    data = load_json(path)
    fetched = parse_dt(data.get("fetched_at"))
    rows = data.get("matches") if isinstance(data, dict) else None
    if rows is None and isinstance(data, dict) and data.get("injuries"):
        rows = [data]
    if not isinstance(rows, list):
        return []
    out = []
    for rec in rows:
        mid = rec.get("match_id") or (rec.get("sporttery_meta") or {}).get("match_id")
        if mid is None:
            continue
        inj = rec.get("injuries")
        adj = None
        if isinstance(inj, dict):
            adj = absence_dict(inj)
        else:
            adj = {k: float(rec.get(k) or 0) for k in ABSENCE_KEYS}
        kick = parse_dt(rec.get("kickoff") or rec.get("kickoff_iso"))
        out.append({
            "match_id": int(mid),
            "home": rec.get("home"),
            "away": rec.get("away"),
            "kickoff": kick,
            "info_at": fetched,
            "absence": adj,
            "source": str(path),
            "injury_count": int(((inj or {}).get("home") or {}).get("count") or 0)
            + int(((inj or {}).get("away") or {}).get("count") or 0)
            if isinstance(inj, dict) else int(absence_sum(adj) > 0),
        })
    return out


def load_movement(paths: list[Path]) -> dict[int, list[dict]]:
    by: dict[int, list[dict]] = {}
    for path in paths:
        for rec in iter_jsonl(path) or []:
            if rec.get("pool") not in (None, "HAD"):
                continue
            odds = rec.get("odds")
            if isinstance(odds, dict):
                try:
                    trip = [float(odds["h"]), float(odds["d"]), float(odds["a"])]
                except (KeyError, TypeError, ValueError):
                    continue
            elif isinstance(odds, (list, tuple)) and len(odds) >= 3:
                try:
                    trip = [float(odds[0]), float(odds[1]), float(odds[2])]
                except (TypeError, ValueError):
                    continue
            else:
                continue
            if min(trip) <= 1:
                continue
            mid = rec.get("match_id") or rec.get("sporttery_match_id")
            try:
                mid = int(str(mid).replace("sporttery-", ""))
            except (TypeError, ValueError):
                continue
            ts = parse_dt(rec.get("updated_at") or rec.get("observed_at"))
            if ts is None:
                continue
            by.setdefault(mid, []).append({"at": ts, "odds": trip, "source": path.name})
    for mid, rows in by.items():
        rows.sort(key=lambda r: r["at"])
    return by


def latest_before(quotes: list[dict], t) -> dict | None:
    hit = None
    for q in quotes:
        if q["at"] < t:
            hit = q
    return hit


def latest_between(quotes: list[dict], lo, hi) -> dict | None:
    hit = None
    for q in quotes:
        if lo <= q["at"] < hi:
            hit = q
    return hit


def load_result(store: Path, match_id: int) -> tuple[int, int] | None:
    path = store / "backtest" / "results" / f"sporttery-{match_id}.json"
    if not path.exists():
        return None
    rec = load_json(path)
    if rec.get("status") != "finished":
        return None
    sc = rec.get("score_90") or {}
    try:
        return int(sc["home"]), int(sc["away"])
    except (KeyError, TypeError, ValueError):
        return None


def market_probs(odds: list[float]) -> list[float]:
    p, _ = P.devig(odds, "power")
    return [float(p[0]), float(p[1]), float(p[2])]


def pack_probs(p, yidx: int) -> dict:
    return {
        "p": [round(x, 6) for x in p],
        "brier": round(brier(p, yidx), 6),
        "log_loss": round(log_loss(p, yidx), 6),
        "pick": int(max(range(3), key=lambda i: p[i])),
    }


def adjusted_probs(odds: list[float], adj: dict) -> list[float] | None:
    p = market_probs(odds)
    lam = P.solve_lam_from_probs(p)
    if lam is None:
        return None
    lh, la, _ = P.apply_fact_adjustments(adj, lam[0], lam[1])
    return P.one(P.matrix(lh, la))


def scan_lineups(forward: Path) -> dict:
    counts = {"files": 0, "VALID": 0, "POST_MATCH_NOT_USABLE": 0,
              "NOT_ATTACHED": 0, "MISSING": 0, "other": 0}
    if not forward.exists():
        return counts
    for path in forward.rglob("*_output.json"):
        if path.name.endswith(".registry-core.json"):
            continue
        counts["files"] += 1
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        status = None
        feat = data.get("api_features") or data.get("features") or {}
        if isinstance(feat, dict):
            status = feat.get("lineups_status")
        if status is None:
            blob = json.dumps(data, ensure_ascii=False)
            if "POST_MATCH_NOT_USABLE" in blob and "lineups_status" in blob:
                status = "POST_MATCH_NOT_USABLE"
            elif "NOT_ATTACHED" in blob:
                status = "NOT_ATTACHED"
        if status in counts:
            counts[status] += 1
        elif status:
            counts["other"] += 1
    return counts


def score_group(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "adopt_over_market": False, "adopt_reason": "too_small"}
    market = metrics(rows, "market")
    adj = metrics(rows, "adjusted")
    adopt, reason = decide_adopt(market["log_loss"], adj["log_loss"], market["n"])
    out = {
        "n": market["n"],
        "market": market,
        "adjusted": adj,
        "delta_log_loss": round(market["log_loss"] - adj["log_loss"], 6),
        "delta_brier": round(market["brier"] - adj["brier"], 6),
        "adopt_over_market": adopt,
        "adopt_reason": reason,
    }
    clv = [r for r in rows if r.get("later")]
    if clv:
        out["later_market"] = metrics(clv, "later")
        out["clv_n"] = len(clv)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, default=PROJ)
    ap.add_argument("--store", type=Path, default=STORE)
    args = ap.parse_args()
    project = args.project.resolve()
    store = args.store.resolve()
    roots = [
        store / "forward",
        ROOT / "project001_足球预测" / "05_交付",
        project / "05_交付",
    ]
    previews = discover_previews(roots)
    collected = []
    for path in previews:
        collected.extend(preview_matches(path))
    late_path = store / "late_info" / "events.jsonl"
    if late_path.exists():
        collected.extend(load_late_info_events(late_path))
        previews.append(late_path)
    collected.sort(key=lambda r: r.get("info_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    quotes = load_movement([
        store / "odds" / "production_movement.jsonl",
        store / "odds" / "movement.jsonl",
    ])
    inventory = {
        "preview_files": [str(p) for p in previews],
        "preview_matches": len(collected),
        "with_absence": sum(1 for r in collected if absence_sum(r["absence"]) > 0),
        "lineups": scan_lineups(store / "forward"),
    }
    residual, ungated, skipped = [], [], []
    seen = set()
    for rec in collected:
        if absence_sum(rec["absence"]) <= 0:
            skipped.append({"match_id": rec["match_id"], "reason": "zero_absence"})
            continue
        key = rec["match_id"]
        if key in seen:
            continue
        seen.add(key)
        actual = load_result(store, rec["match_id"])
        if actual is None:
            skipped.append({"match_id": rec["match_id"], "reason": "no_result"})
            continue
        qlist = quotes.get(rec["match_id"]) or []
        if rec["info_at"] is None or rec["kickoff"] is None:
            skipped.append({"match_id": rec["match_id"], "reason": "missing_timestamp"})
            continue
        early = latest_before(qlist, rec["info_at"])
        later = latest_between(qlist, rec["info_at"], rec["kickoff"])
        if early is None:
            skipped.append({"match_id": rec["match_id"], "reason": "no_odds_before_info"})
            continue
        y = outcome_idx(*actual)
        adj_p = adjusted_probs(early["odds"], rec["absence"])
        if adj_p is None:
            skipped.append({"match_id": rec["match_id"], "reason": "lambda_unsolved"})
            continue
        mkt_p = market_probs(early["odds"])
        row = {
            "match_id": rec["match_id"],
            "home": rec["home"],
            "away": rec["away"],
            "actual": list(actual),
            "y": y,
            "info_at": rec["info_at"].isoformat(),
            "odds_at": early["at"].isoformat(),
            "kickoff": rec["kickoff"].isoformat(),
            "hours_after_odds": round((rec["info_at"] - early["at"]).total_seconds() / 3600, 2),
            "absence": rec["absence"],
            "late": is_late_info(rec["info_at"], early["at"], rec["kickoff"]),
            "market": pack_probs(mkt_p, y),
            "adjusted": pack_probs(adj_p, y),
        }
        if later:
            row["later"] = pack_probs(market_probs(later["odds"]), y)
            row["later_at"] = later["at"].isoformat()
        if row["late"]:
            residual.append(row)
        else:
            ungated.append(row)

    report = {
        "schema": "late-info-residual-1.0",
        "research_only": True,
        "production_unchanged": "MARKET_BASELINE market_only; SCORE_MODEL=bp; no fusion retune",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "protocol": {
            "gate": "odds_snapshot < injury_fetched_at < kickoff",
            "injury_source": "sporttery getInjurySuspensionV1 preview",
            "lineup_source": "fusion api_features.lineups_status",
            "adjustment": "predict.apply_fact_adjustments on market-inverted lambda",
            "min_test": MIN_TEST,
            "coefficients": "UNFITTED position_and_start_rate_heuristic",
        },
        "inventory": inventory,
        "skipped": skipped,
        "residual": score_group(residual),
        "ungated_contrast": score_group(ungated),
        "residual_matches": residual,
        "ungated_matches": ungated,
    }
    print("previews", len(previews), "absence", inventory["with_absence"],
          "residual", report["residual"].get("n"),
          "adopt", report["residual"].get("adopt_over_market"),
          "lineups_valid", inventory["lineups"].get("VALID"), flush=True)
    out = project / "05_交付" / "late_info_residual_research.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()

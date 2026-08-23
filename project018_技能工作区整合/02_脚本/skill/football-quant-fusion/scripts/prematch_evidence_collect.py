#!/usr/bin/env python3
"""Collect and audit match-bound pre-match evidence from Sporttery preview APIs.

This is the first automatic evidence pass.  It intentionally writes sidecar
snapshots instead of rewriting a registered prediction.  A later rolling
refresh can replace the sidecar for the same match with a new snapshot.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CORE = HERE.parents[2] / "core" / "zu-yu-dashi-3" / "scripts"
SPEC = importlib.util.spec_from_file_location("fetch_match_preview", CORE / "fetch_match_preview.py")
if not SPEC or not SPEC.loader:
    raise RuntimeError(f"preview collector unavailable: {CORE}")
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)

UTC = timezone.utc
REQUIRED = ("team_stats", "recent_form", "injury", "suspensions", "starting_xi")


def _feature_analysis(feature: dict[str, Any]) -> dict[str, Any]:
    """Expose the mobile preview's feature panels without relabeling facts.

    The endpoint returns aggregate panels with names such as ``last`` and
    ``eachSameHomeAway``.  We retain those raw objects and add stable semantic
    aliases; the source-field map makes the interpretation auditable across
    leagues and future endpoint revisions.
    """
    feature = feature or {}
    return {
        "source_field_map": {
            "goals_avg": "feature.goalAvg",
            "conceded_avg": "feature.lossGoalAvg",
            "h2h_last7": "feature.last",
            "recent_home_away": "feature.eachHomeAway",
            "same_home_away_recent": "feature.sameHomeAway",
            "same_home_away_extended": "feature.eachSameHomeAway",
        },
        "goals_avg": feature.get("goalAvg") or {},
        "conceded_avg": feature.get("lossGoalAvg") or {},
        "h2h_last7": feature.get("last") or {},
        "recent_home_away": feature.get("eachHomeAway") or {},
        "same_home_away_recent": feature.get("sameHomeAway") or {},
        "same_home_away_extended": feature.get("eachSameHomeAway") or {},
    }


def _parse(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _entry(status: str, value: Any, *, source_id: str, source_url: str, collected_at: str,
           reason: str | None = None) -> dict[str, Any]:
    return {"status": status, "value": value, "source_id": source_id,
            "source_url": source_url, "refreshed_at": collected_at,
            "missing_reason": reason}


def _audit(match: dict[str, Any], facts: dict[str, Any], collected_at: str) -> dict[str, Any]:
    source_id = "sporttery.preview"
    source_url = f"https://m.sporttery.cn/zqlszl/bssj/?mid={match.get('match_id')}"
    feature = facts.get("feature") or {}
    feature_analysis = _feature_analysis(feature)
    strength = facts.get("strength")
    recent_home = (facts.get("recent_home") or [])[:5]
    recent_away = (facts.get("recent_away") or [])[:5]
    injuries = facts.get("injuries") or {}
    team_stats = {"strength": strength, "feature": feature,
                  "feature_analysis": feature_analysis,
                  "home_standing": (facts.get("tables") or [])[:1]}
    has_stats = bool(strength or feature)
    has_form = bool(recent_home and recent_away)
    scope_verified = all((item.get("league_id") is not None) for item in [*recent_home, *recent_away])
    home_inj, away_inj = injuries.get("home") or {}, injuries.get("away") or {}
    injury_value = {"home": home_inj, "away": away_inj}
    has_injury = bool(home_inj or away_inj)
    injury_response_present = isinstance(injuries, dict) and any(
        side in injuries for side in ("home", "away")
    )
    suspension_value = {
        "home": [p for p in (home_inj.get("list") or []) if p.get("suspensionFlag")],
        "away": [p for p in (away_inj.get("list") or []) if p.get("suspensionFlag")],
    }
    has_suspension = bool(suspension_value["home"] or suspension_value["away"])
    injury_status = "VALID" if has_injury else "EMPTY_UNCONFIRMED" if injury_response_present else "UNAVAILABLE"
    suspension_status = "VALID" if has_suspension else "EMPTY_UNCONFIRMED" if injury_response_present else "UNAVAILABLE"
    # Sporttery preview exposes roster/absence information, not an official
    # starting XI.  XI is therefore pending for the rolling near-kickoff pass.
    kickoff = _parse(match.get("kickoff"))
    refresh_points = []
    if kickoff:
        for minutes in (120, 90, 60, 45, 30, 15):
            refresh_points.append((kickoff - timedelta(minutes=minutes)).isoformat())
    entries = {
        "team_stats": _entry("VALID" if has_stats else "UNAVAILABLE", team_stats,
                             source_id=source_id, source_url=source_url, collected_at=collected_at,
                             reason=None if has_stats else "PREVIEW_STATS_EMPTY"),
        "recent_form": _entry("VALID" if has_form and scope_verified and len(recent_home) >= 5 and len(recent_away) >= 5 else "PARTIAL" if has_form else "UNAVAILABLE",
                              {"home": recent_home, "away": recent_away}, source_id=source_id,
                              source_url=source_url, collected_at=collected_at,
                              reason=None if has_form and scope_verified and len(recent_home) >= 5 and len(recent_away) >= 5 else "RECENT_FORM_SCOPE_UNVERIFIED" if has_form and not scope_verified else "RECENT_FORM_LT_5"),
        "injury": _entry(injury_status, injury_value,
                             source_id=source_id, source_url=source_url, collected_at=collected_at,
                             reason=None if has_injury or injury_response_present else "INJURY_ENDPOINT_UNAVAILABLE"),
        "suspensions": _entry(suspension_status, suspension_value,
                               source_id=source_id, source_url=source_url, collected_at=collected_at,
                               reason=None if has_suspension or injury_response_present else "SUSPENSION_ENDPOINT_UNAVAILABLE"),
        "starting_xi": _entry("PENDING_REFRESH", None, source_id="official.lineup.pending",
                              source_url=source_url, collected_at=collected_at,
                              reason="OFFICIAL_XI_NOT_PUBLISHED_OR_NOT_ATTACHED"),
    }
    missing = [name for name, item in entries.items() if item["status"] not in {"VALID", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}]
    return {"schema_version": "evidence-audit-1.1", "critical_fields": list(REQUIRED),
            "entries": entries, "missing_fields": missing, "evidence_gap": bool(missing),
            "evidence_status": "GAP" if missing else "OK",
            "evidence_gap_reasons": [f"{n.upper()}_{entries[n]['missing_reason'] or entries[n]['status']}" for n in missing],
            "kickoff": match.get("kickoff"), "collected_at": collected_at,
            "lineup_refresh_schedule": refresh_points,
            "source_policy": {
                "sporttery_preview": "official mobile endpoint",
                "third_party_content_notice": "page-level notice may apply; preserve field-level provenance",
                "international": "research_only"}}


def collect_one(match: dict[str, Any], *, terms: int = 10, hist: int = 5) -> dict[str, Any]:
    mid = match.get("match_id")
    if mid is None:
        raise ValueError("match_id required")
    collected_at = datetime.now(UTC).isoformat(timespec="seconds")
    kickoff = _parse(match.get("kickoff"))
    now = datetime.now(UTC)
    if kickoff and now >= kickoff:
        audit = {"schema_version": "evidence-audit-1.1", "critical_fields": list(REQUIRED),
                 "entries": {}, "missing_fields": list(REQUIRED), "evidence_gap": True,
                 "evidence_status": "POST_KICKOFF", "evidence_gap_reasons": ["POST_KICKOFF_NOT_USABLE"],
                 "kickoff": match.get("kickoff"), "collected_at": collected_at,
                 "lineup_refresh_schedule": [], "source_policy": {"international": "research_only"}}
        return {"schema_version": "prematch-evidence-snapshot-1.0", "match_id": mid,
                "identity": {k: match.get(k) for k in ("home", "away", "competition", "kickoff", "match_num")},
                "collected_at": collected_at, "facts": {}, "evidence_audit": audit,
                "collection_guard": "POST_KICKOFF_NOT_USABLE"}
    facts = preview.collect(int(str(mid).replace("sporttery-", "")), terms=terms, hist=hist)
    audit = _audit(match, facts, collected_at)
    facts = {**facts, "feature_analysis": _feature_analysis(facts.get("feature") or {})}
    return {"schema_version": "prematch-evidence-snapshot-1.0", "match_id": mid,
            "identity": {k: match.get(k) for k in ("home", "away", "competition", "kickoff", "match_num")},
            "collected_at": collected_at, "facts": facts, "evidence_audit": audit}


def collect_file(input_path: Path, output_dir: Path, *, match_ids: set[str] | None = None,
                 terms: int = 10, hist: int = 5) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and isinstance(payload.get("matches"), list):
        matches = payload["matches"]
    elif isinstance(payload, dict):
        matches = [payload]
    else:
        matches = payload
    rows, statuses = [], []
    output_dir.mkdir(parents=True, exist_ok=True)
    for match in matches if isinstance(matches, list) else []:
        key = str(match.get("match_id") or (match.get("sporttery_meta") or {}).get("match_id") or "")
        if key and not key.startswith("sporttery-"):
            key = f"sporttery-{key}"
        if key:
            match = {**match, "match_id": key}
        if match_ids and key not in match_ids and key.removeprefix("sporttery-") not in match_ids:
            continue
        try:
            row = collect_one(match, terms=terms, hist=hist)
            path = output_dir / f"{key}.json"
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            rows.append({"match_id": key, "status": "ok", "evidence_gap": row["evidence_audit"]["evidence_gap"], "path": str(path)})
        except Exception as exc:
            rows.append({"match_id": key, "status": "error", "reason": str(exc)[:200]})
        statuses.append(rows[-1])
    return {"schema_version": "prematch-evidence-run-1.0", "input": str(input_path),
            "output_dir": str(output_dir), "count": len(statuses), "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True, help="raw/input JSON with matches")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--match-id", action="append")
    ap.add_argument("--terms", type=int, default=10)
    ap.add_argument("--hist", type=int, default=5)
    args = ap.parse_args()
    print(json.dumps(collect_file(args.input, args.output_dir, match_ids=set(args.match_id or []), terms=args.terms, hist=args.hist), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

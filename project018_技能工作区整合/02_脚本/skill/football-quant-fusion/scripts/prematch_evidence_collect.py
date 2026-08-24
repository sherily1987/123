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
import os
import re
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

ENRICHMENT = HERE.parents[2] / "llm" / "football-llm-predictor" / "llm_evidence_enrichment.py"
ENRICHMENT_SPEC = importlib.util.spec_from_file_location("llm_evidence_enrichment", ENRICHMENT)
if not ENRICHMENT_SPEC or not ENRICHMENT_SPEC.loader:
    raise RuntimeError(f"API-Sports enrichment unavailable: {ENRICHMENT}")
enrichment = importlib.util.module_from_spec(ENRICHMENT_SPEC)
ENRICHMENT_SPEC.loader.exec_module(enrichment)

UTC = timezone.utc
REQUIRED = ("team_stats", "recent_form", "injury", "suspensions", "starting_xi")


def _load_team_aliases() -> dict[str, list[str]]:
    path = HERE.parent / "config" / "intl_odds_sources.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    aliases = payload.get("team_aliases") or {}
    return aliases if isinstance(aliases, dict) else {}


def _api_sports_payload(match: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch optional independent pre-match enrichment when an API key exists.

    Sporttery remains the production odds source. API-Sports is evidence-only;
    a missing key or provider failure is returned as a traceable gap rather
    than treated as a healthy squad.
    """
    if os.environ.get("ENABLE_API_SPORTS_EVIDENCE", "0") != "1":
        return None
    if not os.environ.get("API_FOOTBALL_KEY", "").strip():
        return None
    try:
        client = enrichment.ApiSportsClient(timeout=20)
        kickoff = str(match.get("kickoff") or match.get("kickoff_iso") or "")
        # Sporttery's kickoff field is local China time without an offset.
        if kickoff and not re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", kickoff):
            kickoff = kickoff + "+08:00"
        kwargs = {"aliases": _load_team_aliases()}
        # A provider fixture ID is more reliable than date + multilingual
        # team-name matching, especially for future fixtures and cup ties.
        fixture_id = match.get("api_sports_fixture_id")
        if fixture_id is None and isinstance(match.get("evidence_sources"), dict):
            fixture_id = match["evidence_sources"].get("api_sports_fixture_id")
        if fixture_id is not None:
            kwargs["fixture_id"] = fixture_id
        return client.collect_match(match.get("home"), match.get("away"), kickoff, **kwargs)
    except Exception as exc:
        return {"status": "UNAVAILABLE", "reason": f"collector:{type(exc).__name__}"}


def _scrapling_fallback(match: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any] | None:
    """Try the mapped Scrapling source before optional API enrichment.

    This is deliberately evidence-only.  It consumes a match-embedded source
    map (``evidence_sources``/``scrapling_sources``) and never invents a URL;
    daily discovery remains the caller's responsibility when no source map is
    available.  Valid API fields win, while missing/partial fields can be
    filled by the browser snapshot with field-level provenance.
    """
    if not (audit.get("missing_fields") or audit.get("evidence_gap")):
        return None
    sources = match.get("evidence_sources")
    mapping: dict[str, Any] = dict(sources) if isinstance(sources, dict) else {}
    for key in ("scrapling_url", "scrapling_sources", "fotmob_match_id",
                "predicted_xi_source_url", "official_url"):
        if match.get(key) is not None:
            mapping[key] = match[key]
    if not (mapping.get("scrapling_url") or mapping.get("scrapling_sources")
            or mapping.get("url") or mapping.get("fotmob_match_id")):
        return None
    try:
        script = HERE / "bb_browser_evidence_collect.py"
        spec = importlib.util.spec_from_file_location("bb_browser_evidence_collect", script)
        if not spec or not spec.loader:
            return {"status": "UNAVAILABLE", "reason": "scrapling_adapter_missing"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        snapshot = module.collect_one({**match, "evidence_sources": mapping}, mapping)
        snapshot["route"] = "scrapling_first_then_api"
        snapshot["research_only"] = True
        return snapshot
    except Exception as exc:
        return {"status": "UNAVAILABLE", "reason": f"scrapling:{type(exc).__name__}",
                "research_only": True}


def _merge_scrapling_audit(primary: dict[str, Any], fallback: dict[str, Any]) -> None:
    """Project fallback fields into the unified audit without API overwrite."""
    fb_audit = fallback.get("evidence_audit") or {}
    primary_entries = primary.setdefault("entries", {})
    for name, item in (fb_audit.get("entries") or {}).items():
        if not isinstance(item, dict):
            continue
        current = primary_entries.get(name) or {}
        current_status = str(current.get("status") or "UNAVAILABLE").upper()
        if current_status not in {"VALID", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}:
            primary_entries[name] = item
    missing = [name for name, item in primary_entries.items()
               if str((item or {}).get("status") or "").upper() not in
               {"VALID", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}]
    primary["missing_fields"] = missing
    primary["evidence_gap"] = bool(missing)
    primary["evidence_status"] = "GAP" if missing else "OK"
    primary["evidence_gap_reasons"] = [
        f"{name.upper()}_{(primary_entries[name].get('missing_reason') or primary_entries[name].get('status') or 'UNKNOWN')}"
        for name in missing
    ]


_PRESENT_STATUSES = {
    "VALID", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG",
    "EXPLICIT_XG", "PREDICTED",
}


def _merge_api_audit(primary: dict[str, Any], api_audit: dict[str, Any]) -> None:
    """Use API-Sports only for fields still missing after Scrapling."""
    primary_entries = primary.setdefault("entries", {})
    for name, item in (api_audit.get("entries") or {}).items():
        if not isinstance(item, dict):
            continue
        current = primary_entries.get(name) or {}
        if str(current.get("status") or "").upper() not in _PRESENT_STATUSES:
            primary_entries[name] = item
    missing = [name for name, item in primary_entries.items()
               if str((item or {}).get("status") or "").upper() not in _PRESENT_STATUSES]
    primary["missing_fields"] = missing
    primary["evidence_gap"] = bool(missing)
    primary["evidence_status"] = "GAP" if missing else "OK"
    primary["evidence_gap_reasons"] = [
        f"{name.upper()}_{(primary_entries[name].get('missing_reason') or primary_entries[name].get('status') or 'UNKNOWN')}"
        for name in missing
    ]
    primary["api_sports_attempt"] = api_audit.get("api_sports_attempt") or primary.get("api_sports_attempt")


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
    api = facts.get("api_sports") or {}
    api_ok = api.get("status") == "ok"
    api_recent = api.get("recent") or {}
    api_injuries = api.get("injuries") or []
    api_lineups = api.get("lineups") or []
    feature = facts.get("feature") or {}
    feature_analysis = _feature_analysis(feature)
    strength = facts.get("strength")
    recent_home = (api_recent.get("home") or facts.get("recent_home") or [])[:5]
    recent_away = (api_recent.get("away") or facts.get("recent_away") or [])[:5]
    recent_source_id = "api-sports.io" if api_recent.get("home") and api_recent.get("away") else source_id
    recent_source_url = "https://v3.football.api-sports.io/fixtures" if recent_source_id == "api-sports.io" else source_url
    injuries = facts.get("injuries") or {}
    if api_ok:
        team_ids = api.get("team_ids") or {}
        api_injuries_by_side = {"home": [], "away": []}
        for item in api_injuries:
            team_id = (item.get("team") or {}).get("id")
            side = "home" if team_id == team_ids.get("home") else "away" if team_id == team_ids.get("away") else None
            if side:
                api_injuries_by_side[side].append(item)
        injuries = api_injuries_by_side
    team_stats = {"strength": strength, "feature": feature,
                  "feature_analysis": feature_analysis,
                  "home_standing": (facts.get("tables") or [])[:1]}
    has_stats = bool(strength or feature)
    has_form = bool(recent_home and recent_away)
    # Sporttery preview carries numeric league_id; API-Sports normalization
    # carries the league name. Either is a traceable competition scope.
    scope_verified = all(
        (item.get("league_id") is not None or item.get("league"))
        for item in [*recent_home, *recent_away]
    )
    home_inj, away_inj = injuries.get("home") or {}, injuries.get("away") or {}
    injury_value = {"home": home_inj, "away": away_inj}
    has_injury = bool(home_inj or away_inj)
    injury_response_present = isinstance(injuries, dict) and any(
        side in injuries for side in ("home", "away")
    )
    def _suspensions(value):
        if isinstance(value, dict):
            return [p for p in (value.get("list") or []) if p.get("suspensionFlag")]
        if isinstance(value, list):
            return [p for p in value if "susp" in str((p.get("player") or {}).get("type") or p.get("reason") or "").casefold()]
        return []
    suspension_value = {"home": _suspensions(home_inj), "away": _suspensions(away_inj)}
    has_suspension = bool(suspension_value["home"] or suspension_value["away"])
    api_injury_source = api_ok and bool(api.get("injuries") is not None)
    injury_status = "VALID" if has_injury else "EMPTY_UNCONFIRMED" if injury_response_present or api_injury_source else "UNAVAILABLE"
    suspension_status = "VALID" if has_suspension else "EMPTY_UNCONFIRMED" if injury_response_present or api_injury_source else "UNAVAILABLE"
    # Sporttery preview exposes roster/absence information, not an official
    # starting XI.  XI is therefore pending for the rolling near-kickoff pass.
    kickoff = _parse(match.get("kickoff"))
    refresh_points = []
    if kickoff:
        for minutes in (120, 90, 60, 45, 30, 15):
            refresh_points.append((kickoff - timedelta(minutes=minutes)).isoformat())
    # Keep the provider's completeness verdict when available.  Older test
    # doubles/sidecars may omit it, so derive the same two-sided rule locally:
    # one non-empty team sheet is partial evidence, never a complete XI.
    provider_lineup_status = str(api.get("lineups_status") or "").upper()
    lineup_sides_with_xi = sum(
        1 for row in api_lineups
        if isinstance(row, dict) and len(row.get("startXI") or []) > 0
    )
    if provider_lineup_status in {"", "OK", "VALID"} and lineup_sides_with_xi >= 2:
        lineup_status = "VALID"
    elif provider_lineup_status == "PARTIAL" or 0 < lineup_sides_with_xi < 2:
        lineup_status = "PARTIAL"
    else:
        lineup_status = "PENDING_REFRESH"
    lineup_source_id = "api-sports.io" if api_lineups else "official.lineup.pending"
    lineup_source_url = f"https://v3.football.api-sports.io/fixtures/lineups?fixture={api.get('fixture_id')}" if api_lineups else source_url
    entries = {
        "team_stats": _entry("VALID" if has_stats else "UNAVAILABLE", team_stats,
                             source_id=source_id, source_url=source_url, collected_at=collected_at,
                             reason=None if has_stats else "PREVIEW_STATS_EMPTY"),
        "recent_form": _entry("VALID" if has_form and scope_verified and len(recent_home) >= 5 and len(recent_away) >= 5 else "PARTIAL" if has_form else "UNAVAILABLE",
                              {"home": recent_home, "away": recent_away}, source_id=recent_source_id,
                              source_url=recent_source_url, collected_at=collected_at,
                              reason=None if has_form and scope_verified and len(recent_home) >= 5 and len(recent_away) >= 5 else "RECENT_FORM_SCOPE_UNVERIFIED" if has_form and not scope_verified else "RECENT_FORM_LT_5"),
            "injury": _entry(injury_status, injury_value,
                             source_id="api-sports.io" if api_injury_source else source_id,
                             source_url=f"https://v3.football.api-sports.io/injuries?fixture={api.get('fixture_id')}" if api_injury_source else source_url,
                             collected_at=collected_at,
                             reason=None if has_injury or injury_response_present else "INJURY_ENDPOINT_UNAVAILABLE"),
            "suspensions": _entry(suspension_status, suspension_value,
                                   source_id="api-sports.io" if api_injury_source else source_id,
                                   source_url=f"https://v3.football.api-sports.io/injuries?fixture={api.get('fixture_id')}" if api_injury_source else source_url,
                                   collected_at=collected_at,
                                   reason=None if has_suspension or injury_response_present else "SUSPENSION_ENDPOINT_UNAVAILABLE"),
        "starting_xi": _entry(lineup_status, api_lineups or None, source_id=lineup_source_id,
                              source_url=lineup_source_url, collected_at=collected_at,
                              reason=None if lineup_status == "VALID" else "OFFICIAL_XI_NOT_PUBLISHED_OR_NOT_ATTACHED"),
    }
    missing = [name for name, item in entries.items() if item["status"] not in {"VALID", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}]
    return {"schema_version": "evidence-audit-1.1", "critical_fields": list(REQUIRED),
            "entries": entries, "missing_fields": missing, "evidence_gap": bool(missing),
            "evidence_status": "GAP" if missing else "OK",
            "evidence_gap_reasons": [f"{n.upper()}_{entries[n]['missing_reason'] or entries[n]['status']}" for n in missing],
            "kickoff": match.get("kickoff"), "collected_at": collected_at,
            "lineup_refresh_schedule": refresh_points,
            "api_sports_attempt": {
                "status": api.get("status", "NOT_REQUESTED"),
                "reason": api.get("reason") if api else "NOT_REQUESTED",
                "research_only": True,
            },
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
    # Scrapling is the preferred dynamic evidence route.  It runs before the
    # optional API-Sports call and remains research-only.
    scrapling = _scrapling_fallback(match, audit)
    if scrapling and scrapling.get("status") != "UNAVAILABLE":
        facts["scrapling"] = scrapling
        _merge_scrapling_audit(audit, scrapling)
    elif scrapling:
        facts["scrapling"] = scrapling
    # API-Sports is a secondary fill-only source.  Re-audit after the call so
    # it can fill fields Scrapling did not provide, without overwriting them.
    api_payload = _api_sports_payload(match)
    if api_payload is not None:
        facts["api_sports"] = api_payload
        _merge_api_audit(audit, _audit(match, facts, collected_at))
    facts = {**facts, "feature_analysis": _feature_analysis(facts.get("feature") or {})}
    return {"schema_version": "prematch-evidence-snapshot-1.0", "match_id": mid,
            "identity": {k: match.get(k) for k in ("home", "away", "competition", "kickoff", "match_num")},
            "collected_at": collected_at, "facts": facts, "evidence_audit": audit}


def collect_file(input_path: Path, output_dir: Path, *, match_ids: set[str] | None = None,
                 terms: int = 10, hist: int = 5,
                 scrapling_url_map: Path | None = None) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and isinstance(payload.get("matches"), list):
        matches = payload["matches"]
    elif isinstance(payload, dict):
        matches = [payload]
    else:
        matches = payload
    rows, statuses = [], []
    source_health = {
        "api_sports": {"NOT_REQUESTED": 0, "ok": 0, "UNAVAILABLE": 0, "SOURCE_CONFLICT": 0},
        "scrapling": {"attempted": 0, "ok": 0, "UNAVAILABLE": 0},
        "evidence_gap": 0,
    }
    source_map: dict[str, Any] = {}
    if scrapling_url_map:
        try:
            loaded = json.loads(scrapling_url_map.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                source_map = loaded
        except (OSError, ValueError):
            source_map = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    for match in matches if isinstance(matches, list) else []:
        key = str(match.get("match_id") or (match.get("sporttery_meta") or {}).get("match_id") or "")
        if key and not key.startswith("sporttery-"):
            key = f"sporttery-{key}"
        if key:
            match = {**match, "match_id": key}
            mapped = source_map.get(key) or source_map.get(key.removeprefix("sporttery-"))
            if isinstance(mapped, dict):
                embedded = match.get("evidence_sources")
                merged = dict(embedded) if isinstance(embedded, dict) else {}
                merged.update(mapped)
                match["evidence_sources"] = merged
        if match_ids and key not in match_ids and key.removeprefix("sporttery-") not in match_ids:
            continue
        try:
            row = collect_one(match, terms=terms, hist=hist)
            path = output_dir / f"{key}.json"
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            audit = row.get("evidence_audit") or {}
            api_status = str((audit.get("api_sports_attempt") or {}).get("status") or "NOT_REQUESTED")
            source_health["api_sports"][api_status] = source_health["api_sports"].get(api_status, 0) + 1
            scrapling = (row.get("facts") or {}).get("scrapling")
            if isinstance(scrapling, dict):
                source_health["scrapling"]["attempted"] += 1
                if scrapling.get("status") == "UNAVAILABLE":
                    source_health["scrapling"]["UNAVAILABLE"] += 1
                else:
                    source_health["scrapling"]["ok"] += 1
            if audit.get("evidence_gap"):
                source_health["evidence_gap"] += 1
            rows.append({"match_id": key, "status": "ok", "evidence_gap": row["evidence_audit"]["evidence_gap"], "path": str(path)})
        except Exception as exc:
            rows.append({"match_id": key, "status": "error", "reason": str(exc)[:200]})
        statuses.append(rows[-1])
    return {"schema_version": "prematch-evidence-run-1.0", "input": str(input_path),
            "output_dir": str(output_dir), "count": len(statuses), "rows": rows,
            "source_health": source_health}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True, help="raw/input JSON with matches")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--match-id", action="append")
    ap.add_argument("--terms", type=int, default=10)
    ap.add_argument("--hist", type=int, default=5)
    ap.add_argument("--enable-api-sports-evidence", action="store_true",
                    help="启用 API-Sports 近期赛果/伤停/首发证据（研究源，消耗配额）")
    ap.add_argument("--scrapling-url-map", type=Path,
                    help="optional match_id -> Scrapling source mapping; preferred before optional API enrichment")
    args = ap.parse_args()
    if args.enable_api_sports_evidence:
        os.environ["ENABLE_API_SPORTS_EVIDENCE"] = "1"
    print(json.dumps(collect_file(args.input, args.output_dir, match_ids=set(args.match_id or []),
                                  terms=args.terms, hist=args.hist,
                                  scrapling_url_map=args.scrapling_url_map), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

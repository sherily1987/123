#!/usr/bin/env python3
"""Build auditable half-time evidence from already collected provider fixtures.

This module deliberately writes evidence rows rather than mutating official
90-minute settlement files. A full-time score cannot be used to infer a
half-time score, and an identity or score conflict remains unresolved.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _score_pair(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    home, away = _int(value.get("home")), _int(value.get("away"))
    return {"home": home, "away": away} if home is not None and away is not None else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _norm(value: Any) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _provider_names(value: Any, aliases: dict[str, Any]) -> list[str]:
    """Return only explicit provider-name aliases; never fabricate a fuzzy match."""
    mapped = aliases.get(str(value), value)
    if isinstance(mapped, (list, tuple)):
        return [str(item) for item in mapped if str(item).strip()]
    return [str(mapped or "")]


def normalize_fixture(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize API-Sports or APIFootball raw fixture without filling gaps."""
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("fixture"), dict):
        fixture = raw["fixture"]
        teams = raw.get("teams") or {}
        score = raw.get("score") or {}
        return {
            "provider": "api-sports.io",
            "provider_fixture_id": str(fixture.get("id") or ""),
            "kickoff": fixture.get("date"),
            "home": ((teams.get("home") or {}).get("name")),
            "away": ((teams.get("away") or {}).get("name")),
            "score_90": _score_pair(score.get("fulltime")) or _score_pair(raw.get("goals")),
            "score_ht": _score_pair(score.get("halftime")),
        }
    if "match_id" in raw:
        def pair(home_key: str, away_key: str) -> dict[str, int] | None:
            try:
                home, away = int(raw.get(home_key)), int(raw.get(away_key))
            except (TypeError, ValueError):
                return None
            return {"home": home, "away": away} if home >= 0 and away >= 0 else None
        date, time = raw.get("match_date"), raw.get("match_time") or "00:00"
        return {
            "provider": "apifootball.com",
            "provider_fixture_id": str(raw.get("match_id") or ""),
            "kickoff": f"{date}T{time}:00+08:00" if date else None,
            "home": raw.get("match_hometeam_name"), "away": raw.get("match_awayteam_name"),
            "score_90": pair("match_hometeam_ft_score", "match_awayteam_ft_score") or pair("match_hometeam_score", "match_awayteam_score"),
            "score_ht": pair("match_hometeam_halftime_score", "match_awayteam_halftime_score"),
        }
    return None


def load_fixture_payload(payload: Any) -> list[dict[str, Any]]:
    """Accept the API-Sports response envelope or an APIFootball event list."""
    raw_rows = payload.get("response") if isinstance(payload, dict) and isinstance(payload.get("response"), list) else payload
    if not isinstance(raw_rows, list):
        return []
    return [fixture for fixture in (normalize_fixture(row) for row in raw_rows)
            if fixture is not None]


def load_alias_files(paths: list[Path]) -> dict[str, list[str]]:
    """Merge explicit alias files without weakening identity matching.

    Different collectors maintain different, audited alias inventories (for
    example APIFootball-specific names and the broader international-odds
    inventory).  Requiring callers to pass both files keeps the source choice
    visible while avoiding the previous all-or-nothing behaviour.  A later
    file supplements an existing key; it never replaces an explicit alias.
    """
    merged: dict[str, list[str]] = {}
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        values = (raw.get("aliases", raw.get("team_aliases", raw))
                  if isinstance(raw, dict) else {})
        if not isinstance(values, dict):
            raise ValueError(f"aliases must be a JSON object: {path}")
        for source_name, provider_names in values.items():
            candidates = provider_names if isinstance(provider_names, (list, tuple)) else [provider_names]
            bucket = merged.setdefault(str(source_name), [])
            for candidate in candidates:
                text = str(candidate or "").strip()
                if text and text not in bucket:
                    bucket.append(text)
    return merged


def match_finished_fixture(record: dict[str, Any], result: dict[str, Any], fixture: dict[str, Any],
                           aliases: dict[str, str], tolerance_minutes: int = 30) -> dict[str, Any]:
    match_id = str(record.get("match_id") or "")
    match = record.get("match") or {}
    kickoff, provider_kickoff = _parse_time(match.get("kickoff")), _parse_time(fixture.get("kickoff"))
    home_names = _provider_names(match.get("home"), aliases)
    away_names = _provider_names(match.get("away"), aliases)
    if (not match_id or kickoff is None or provider_kickoff is None
            or _norm(fixture.get("home")) not in {_norm(name) for name in home_names}
            or _norm(fixture.get("away")) not in {_norm(name) for name in away_names}
            or abs((provider_kickoff - kickoff).total_seconds()) > tolerance_minutes * 60):
        return {"match_id": match_id, "status": "no_match"}
    if fixture.get("score_90") != result.get("score_90"):
        return {"match_id": match_id, "status": "fulltime_conflict"}
    if fixture.get("score_ht") is None:
        return {"match_id": match_id, "status": "missing_half_time_score"}
    return {
        "match_id": match_id, "status": "verified", "matched_by": "team_time_fulltime",
        "provider": fixture.get("provider"), "provider_fixture_id": fixture.get("provider_fixture_id"),
        "record_kickoff": match.get("kickoff"), "provider_kickoff": fixture.get("kickoff"),
        "score_ht": fixture["score_ht"], "score_90": fixture["score_90"],
    }


def build_half_time_evidence(records: list[tuple[dict[str, Any], dict[str, Any]]],
                             fixtures: list[dict[str, Any] | None], aliases: dict[str, str]) -> dict[str, Any]:
    """Return one evidence verdict per registered match, without touching settlement files."""
    normalized = [fixture for fixture in fixtures if isinstance(fixture, dict)]
    rows = []
    for record, result in records:
        verdicts = [match_finished_fixture(record, result, fixture, aliases) for fixture in normalized]
        verified = [row for row in verdicts if row["status"] == "verified"]
        if len(verified) == 1:
            rows.append(verified[0])
        elif len(verified) > 1:
            rows.append({"match_id": str(record.get("match_id") or ""), "status": "ambiguous_match",
                         "candidates": len(verified)})
        elif any(row["status"] == "fulltime_conflict" for row in verdicts):
            rows.append({"match_id": str(record.get("match_id") or ""), "status": "fulltime_conflict"})
        elif any(row["status"] == "missing_half_time_score" for row in verdicts):
            rows.append({"match_id": str(record.get("match_id") or ""), "status": "missing_half_time_score"})
        else:
            rows.append({"match_id": str(record.get("match_id") or ""), "status": "no_match"})
    return {"schema": "half-time-evidence-1.0", "research_only": True, "rows": rows}


def build_alias_candidates(records: list[tuple[dict[str, Any], dict[str, Any]]],
                           fixtures: list[dict[str, Any]],
                           tolerance_minutes: int = 30) -> list[dict[str, Any]]:
    """Suggest, but never apply, unique time+score identity candidates.

    This is a review aid for expanding explicit aliases.  A coincidental
    kickoff and score is not sufficient evidence for production matching, so
    callers must review and add accepted pairs to an audited alias file.
    """
    suggestions = []
    for record, result in records:
        match = record.get("match") or {}
        kickoff = _parse_time(match.get("kickoff"))
        score = result.get("score_90")
        if kickoff is None or not isinstance(score, dict):
            continue
        candidates = []
        for fixture in fixtures:
            provider_kickoff = _parse_time(fixture.get("kickoff"))
            if (provider_kickoff is None or fixture.get("score_90") != score
                    or abs((provider_kickoff - kickoff).total_seconds()) > tolerance_minutes * 60):
                continue
            candidates.append(fixture)
        if len(candidates) != 1:
            continue
        fixture = candidates[0]
        if _norm(match.get("home")) == _norm(fixture.get("home")) and _norm(match.get("away")) == _norm(fixture.get("away")):
            continue
        suggestions.append({
            "match_id": str(record.get("match_id") or ""),
            "kickoff": match.get("kickoff"),
            "sporttery_home": match.get("home"), "sporttery_away": match.get("away"),
            "provider": fixture.get("provider"),
            "provider_home": fixture.get("home"), "provider_away": fixture.get("away"),
            "provider_fixture_id": fixture.get("provider_fixture_id"),
            "score_90": score, "score_ht": fixture.get("score_ht"),
            "review_status": "PENDING_MANUAL_ALIAS_REVIEW",
        })
    return suggestions


def load_settled_records(store: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Read registered predictions with finished 90-minute scores; do not mutate them."""
    registry = store / "registry.jsonl"
    if not registry.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for line in registry.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        path = Path(str(entry.get("path") or ""))
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        match_id = str(record.get("match_id") or entry.get("match_id") or "")
        if match_id:
            latest[match_id] = record
    rows = []
    for match_id, record in latest.items():
        result_path = store / "results" / f"{match_id}.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if (result.get("status") == "finished" and result.get("settlement_scope") == "90min"
                and _score_pair(result.get("score_90")) is not None):
            rows.append((record, result))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="离线构建半场比分证据；不改写正式赛果")
    parser.add_argument("--fixtures", type=Path, required=True,
                        help="已抓取的 API-Sports response JSON 或 APIFootball 事件数组")
    parser.add_argument("--store", type=Path, required=True, help="football-quant-fusion/backtest 目录")
    parser.add_argument("--aliases", type=Path, nargs="+",
                        help="可选队名映射 JSON（可传多个，按顺序合并），格式 {aliases:{体彩名:供应商名}}")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path,
                        help="可选：写出唯一时间+比分队名映射候选；不会自动用于正式匹配")
    args = parser.parse_args()
    payload = json.loads(args.fixtures.read_text(encoding="utf-8"))
    aliases: dict[str, Any] = load_alias_files(args.aliases or [])
    report = build_half_time_evidence(load_settled_records(args.store), load_fixture_payload(payload), aliases)
    report["fixture_input"] = str(args.fixtures)
    report["settled_record_count"] = len(load_settled_records(args.store))
    if args.candidate_report:
        report["alias_candidates"] = build_alias_candidates(
            load_settled_records(args.store), load_fixture_payload(payload)
        )
        args.candidate_report.parent.mkdir(parents=True, exist_ok=True)
        args.candidate_report.write_text(json.dumps({
            "schema": "half-time-alias-candidates-1.0", "research_only": True,
            "review_required": True, "rows": report["alias_candidates"]
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(args.output), "rows": len(report["rows"]),
                      "verified": sum(row["status"] == "verified" for row in report["rows"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

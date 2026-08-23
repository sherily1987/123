#!/usr/bin/env python3
"""Collect optional third-party pre-match evidence through BB-browser.

BB-browser reuses the user's real browser session.  This adapter deliberately
requires a per-match FotMob URL/ID mapping; it never guesses a fixture from a
search snippet.  The result is research evidence only and cannot replace the
official Sporttery market or an official starting-XI confirmation. A non-empty
predicted lineup is retained as explicit ``PREDICTED`` evidence; it is usable
for pre-match research but is never labelled as confirmed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc

# Defaults are only hints for candidate classification.  A league-specific
# input may add its own official domains; no URL is promoted to production by
# this list.
DEFAULT_OFFICIAL_DOMAINS = (
    "uefa.com/", "premierleague.com/", "laliga.com/", "bundesliga.com/",
    "ligue1.com/", "seriea.com/", "eredivisie.eu/", "ligaportugal.pt/",
    "jleague.jp/", "mlssoccer.com/", "fifa.com/",
)


def _parse(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _run_browser(args: list[str]) -> str:
    # PowerShell resolves the npm .ps1/.cmd shim, while Python subprocess on
    # Windows needs the explicit .cmd executable.
    executable = "bb-browser.cmd" if os.name == "nt" else "bb-browser"
    proc = subprocess.run([executable, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=90)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "bb-browser failed").strip()[-500:])
    return proc.stdout


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("browser response is not JSON")
        value = json.loads(raw[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("browser response JSON must be an object")
    return value


def _extract_json_value(text: str) -> Any:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = min((idx for idx in (raw.find("["), raw.find("{")) if idx >= 0), default=-1)
        end = max(raw.rfind("]"), raw.rfind("}"))
        if start < 0 or end <= start:
            raise ValueError("browser response is not JSON")
        return json.loads(raw[start:end + 1])


def _tab_id(output: str) -> str:
    match = re.search(r"tab:\s*([A-Za-z0-9_-]+)", output or "")
    if not match:
        raise ValueError("bb-browser open did not return a tab id")
    return match.group(1)


def _team_form(rows: Any) -> list[dict[str, Any]]:
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        tooltip = row.get("tooltipText") or {}
        result.append({
            "date": (row.get("date") or {}).get("utcTime") or tooltip.get("utcTime"),
            "score": row.get("score"),
            "result": row.get("resultString"),
            "home": (row.get("home") or {}).get("name") or tooltip.get("homeTeam"),
            "away": (row.get("away") or {}).get("name") or tooltip.get("awayTeam"),
        })
    return result[:5]


def _unavailable(team: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for player in team.get("unavailable") or []:
        status = player.get("unavailability") or {}
        out.append({"player": player.get("name"), "type": status.get("type"),
                    "return": status.get("expectedReturn")})
    return out


def _absence_rows(team: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Split the provider's unavailable list without treating empty as clear."""
    out = []
    for player in team.get("unavailable") or []:
        info = player.get("unavailability") or {}
        type_name = str(info.get("type") or "").lower()
        is_suspension = "susp" in type_name or bool(player.get("suspensionFlag"))
        if (kind == "suspension") != is_suspension:
            continue
        out.append({"player": player.get("name"), "type": info.get("type") or
                    ("suspension" if is_suspension else "injury"),
                    "return": info.get("expectedReturn")})
    return out


def _match_xg(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract explicit xG values when the browser provider exposes them."""
    content = payload.get("content") or {}
    candidates = [content.get("stats"), (content.get("matchFacts") or {}).get("stats")]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        direct = candidate.get("xg") or candidate.get("expectedGoals")
        if isinstance(direct, dict) and ("home" in direct or "away" in direct):
            return {"home": direct.get("home"), "away": direct.get("away")}
        periods = candidate.get("periods") or []
        for period in periods if isinstance(periods, list) else []:
            for stat in (period.get("stats") or []) if isinstance(period, dict) else []:
                title = str(stat.get("title") or stat.get("name") or "").lower()
                if "xg" not in title and "expected goal" not in title:
                    continue
                values = stat.get("stats") or stat.get("values") or []
                result = {}
                for value in values if isinstance(values, list) else []:
                    if isinstance(value, dict) and value.get("key") in {"home", "away"}:
                        result[value["key"]] = value.get("value")
                if set(result) == {"home", "away"}:
                    return result
    return None


def discover_sources(match: dict[str, Any]) -> dict[str, Any]:
    """Discover candidate official/secondary pages from fixture identity.

    This intentionally stops at candidate discovery.  It does not trust a
    search snippet or silently choose a URL, so the same method works across
    leagues with different official sites and URL shapes.
    """
    kickoff = str(match.get("kickoff") or "")[:10]
    query = " ".join(filter(None, [str(match.get("competition") or ""),
                                    str(match.get("home") or ""),
                                    str(match.get("away") or ""), kickoff,
                                    "official match"])).strip()
    search_url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query})
    tab = None
    try:
        tab = _tab_id(_run_browser(["open", search_url]))
        time.sleep(1.5)
        expression = ('JSON.stringify(Array.from(document.links).map(function(a){return a.href})'
                      '.filter(function(h){return h.indexOf("http")===0 && '
                      'h.indexOf("google.com/")<0 && h.indexOf("googleusercontent.com/")<0}))')
        links = _extract_json_value(_run_browser(["eval", "--tab", tab, expression]))
        # JSON.stringify returns a JSON string, hence the second decode.
        if isinstance(links, str):
            links = json.loads(links)
        links = list(dict.fromkeys(str(link) for link in (links or []) if str(link).startswith("http")))
        custom_domains = tuple(str(domain).lower().strip().rstrip("/") + "/"
                              for domain in (match.get("official_domains") or [])
                              if str(domain).strip())
        official_domains = DEFAULT_OFFICIAL_DOMAINS + custom_domains
        official = [link for link in links if any(domain in link.lower() for domain in official_domains)]
        third_party = [link for link in links if link not in official and any(domain in link for domain in
                      ("fotmob.com/", "sofascore.com/"))]
        unclassified = [link for link in links if link not in official and link not in third_party]
        return {"status": "source_candidates_found", "query": query,
                "official_candidates": official, "third_party_candidates": third_party,
                "unclassified_candidates": unclassified}
    except Exception as exc:
        return {"status": "source_discovery_error", "query": query, "reason": str(exc)[:300]}
    finally:
        if tab:
            try:
                _run_browser(["close", "--tab", tab])
            except Exception:
                pass


def _entry(status: str, value: Any, *, source_url: str, collected_at: str,
           reason: str | None = None, source_id: str = "fotmob.bb_browser") -> dict[str, Any]:
    return {"status": status, "value": value, "source_id": source_id,
            "source_url": source_url, "refreshed_at": collected_at,
            "missing_reason": reason}


def _snapshot(match: dict[str, Any], payload: dict[str, Any], source_url: str,
              collected_at: str, *, source_id: str = "fotmob.bb_browser",
              provider: str = "fotmob_via_bb_browser") -> dict[str, Any]:
    general = payload.get("general") or {}
    facts = ((payload.get("content") or {}).get("matchFacts") or {})
    lineup = ((payload.get("content") or {}).get("lineup") or {})
    home_team = lineup.get("homeTeam") or {}
    away_team = lineup.get("awayTeam") or {}
    forms = facts.get("teamForm") or []
    home_form, away_form = (_team_form(forms[0]) if len(forms) > 0 else [],
                            _team_form(forms[1]) if len(forms) > 1 else [])
    home_absences, away_absences = _unavailable(home_team), _unavailable(away_team)
    home_suspensions, away_suspensions = (_absence_rows(home_team, "suspension"),
                                          _absence_rows(away_team, "suspension"))
    absence_field_present = "unavailable" in home_team or "unavailable" in away_team
    absence_rows_present = bool(home_absences or away_absences)
    suspension_rows_present = bool(home_suspensions or away_suspensions)
    xg = _match_xg(payload)
    lineup_source = str(lineup.get("source") or "")
    official_xi = lineup_source.lower() in {"official", "confirmed", "startingxi"}
    has_predicted_xi = bool(home_team.get("starters") or away_team.get("starters"))
    xi_status = "VALID" if official_xi else "PREDICTED" if has_predicted_xi else "PENDING_REFRESH"
    xi_reason = None if official_xi else "PREDICTED_XI_NOT_CONFIRMED" if has_predicted_xi else "LAST_STARTING_LINEUPS_NOT_OFFICIAL_XI"
    entries = {
        "team_stats": _entry("VALID" if xg else "UNAVAILABLE", {"xg": xg} if xg else None,
                              source_url=source_url, collected_at=collected_at, source_id=source_id,
                              reason=None if xg else "FOTMOB_MATCH_DETAIL_HAS_NO_TEAM_XG_STATS"),
        "recent_form": _entry("VALID" if len(home_form) >= 5 and len(away_form) >= 5 else "PARTIAL",
                              {"home": home_form, "away": away_form}, source_url=source_url,
                              collected_at=collected_at, source_id=source_id,
                              reason=None if len(home_form) >= 5 and len(away_form) >= 5 else "FORM_LT_5"),
        "injury": _entry("VALID" if absence_rows_present else "EMPTY_UNCONFIRMED" if absence_field_present else "UNAVAILABLE",
                          {"home": home_absences, "away": away_absences}, source_url=source_url,
                          collected_at=collected_at, source_id=source_id,
                          reason=None if absence_rows_present else "EMPTY_ABSENCE_FIELD_NOT_PROOF_OF_CLEAR" if absence_field_present else "LINEUP_ABSENCE_FIELD_MISSING"),
        "suspensions": _entry("VALID" if suspension_rows_present else
                               "EMPTY_UNCONFIRMED" if absence_field_present else "UNAVAILABLE",
                               {"home": home_suspensions, "away": away_suspensions},
                               source_url=source_url, collected_at=collected_at, source_id=source_id,
                               reason=None if suspension_rows_present else
                               "EMPTY_SUSPENSION_FIELD_NOT_PROOF_OF_CLEAR" if absence_field_present
                               else "LINEUP_ABSENCE_FIELD_MISSING"),
        "starting_xi": _entry(xi_status,
                              {"source": lineup_source, "home": home_team.get("starters") or [],
                               "away": away_team.get("starters") or []}, source_url=source_url,
                              collected_at=collected_at, source_id=source_id,
                              reason=xi_reason),
    }
    missing = [name for name, item in entries.items() if item["status"] not in
               {"VALID", "PREDICTED", "OK", "AVAILABLE", "FRESH", "AGING", "PROXY_XG", "EXPLICIT_XG"}]
    return {
        "schema_version": "bb-browser-evidence-snapshot-1.0",
        "provider": provider,
        "research_only": True,
        "match_id": match.get("match_id"),
        "identity": {"home": match.get("home") or (general.get("homeTeam") or {}).get("name"),
                     "away": match.get("away") or (general.get("awayTeam") or {}).get("name"),
                     "competition": match.get("competition") or general.get("leagueName"),
                     "kickoff": general.get("matchTimeUTCDate") or match.get("kickoff")},
        "collected_at": collected_at,
        "source_url": source_url,
        "fotmob_match_id": general.get("matchId"),
        "facts": {"team_form": {"home": home_form, "away": away_form},
                  "unavailable": {"home": home_absences, "away": away_absences},
                  "lineup": {"source": lineup_source, "home": home_team.get("formation"),
                             "away": away_team.get("formation")},
                  "aggregate": ((payload.get("header") or {}).get("status") or {}).get("aggregatedStr")},
        "evidence_audit": {
            "schema_version": "evidence-audit-1.1",
            "critical_fields": ["team_stats", "recent_form", "injury", "suspensions", "starting_xi"],
            "entries": entries, "missing_fields": missing, "evidence_gap": bool(missing),
            "evidence_status": "GAP" if missing else "OK",
            "evidence_gap_reasons": [f"{name.upper()}_{entries[name]['missing_reason'] or entries[name]['status']}" for name in missing],
            "source_policy": {"fotmob": "research_only", "sporttery": "production_market_only"},
        },
    }


def collect_one(match: dict[str, Any], mapping: dict[str, Any] | None,
                *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    kickoff = _parse(match.get("kickoff"))
    if kickoff and now >= kickoff:
        return {"status": "post_kickoff", "match_id": match.get("match_id"),
                "reason": "POST_KICKOFF_NOT_USABLE"}
    if not mapping:
        return {"status": "pending_browser_task", "match_id": match.get("match_id"),
                "browser_task": {"reason": "FOTMOB_MATCH_URL_REQUIRED",
                                 "query": f"{match.get('home')} vs {match.get('away')} {match.get('kickoff')}"}}
    url = mapping.get("url")
    fotmob_id = mapping.get("fotmob_match_id")
    if not url or not fotmob_id:
        return {"status": "pending_browser_task", "match_id": match.get("match_id"),
                "browser_task": {"reason": "FOTMOB_URL_AND_MATCH_ID_REQUIRED"}}
    tab = None
    collected_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        tab = _tab_id(_run_browser(["open", str(url)]))
        # Function syntax survives the Windows bb-browser.cmd argument parser;
        # arrow functions are truncated by the shim in subprocess mode.
        expression = f'fetch("/api/data/matchDetails?matchId={fotmob_id}").then(function(r){{return r.text()}})'
        payload = _extract_json(_run_browser(["eval", "--tab", tab, expression]))
        general = payload.get("general") or {}
        if general.get("started") or general.get("finished"):
            return {"status": "post_kickoff", "match_id": match.get("match_id"),
                    "reason": "BROWSER_SOURCE_SAYS_MATCH_STARTED"}
        return {"status": "ok", **_snapshot(
            match, payload, str(url), collected_at,
            source_id=str(mapping.get("source_id") or "fotmob.bb_browser"),
            provider=str(mapping.get("provider") or "fotmob_via_bb_browser"),
        )}
    finally:
        if tab:
            try:
                _run_browser(["close", "--tab", tab])
            except Exception:
                pass


def collect_file(input_path: Path, output_dir: Path, url_map_path: Path | None,
                 *, discover: bool = False) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    matches = payload.get("matches", []) if isinstance(payload, dict) else payload
    mappings = json.loads(url_map_path.read_text(encoding="utf-8-sig")) if url_map_path else {}
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for match in matches if isinstance(matches, list) else []:
        # sales_day_collect emits the stable Sporttery id inside
        # ``sporttery_meta``.  Normalize it here so BB-browser discovery and
        # sidecars remain joinable with jobs/registry instead of producing
        # rows with an empty match_id.
        raw_mid = match.get("match_id") or (match.get("sporttery_meta") or {}).get("match_id")
        mid = str(raw_mid or "")
        if mid and not mid.startswith("sporttery-"):
            mid = f"sporttery-{mid}"
        match = dict(match)
        match["match_id"] = mid
        mapping = mappings.get(mid) or mappings.get(mid.removeprefix("sporttery-"))
        if not mapping and discover:
            discovered = discover_sources(match)
            row = {"status": "pending_browser_task", "match_id": mid,
                   "browser_task": {"reason": "SOURCE_REVIEW_REQUIRED",
                                    "match": match, "discovery": discovered}}
            rows.append({k: row.get(k) for k in ("match_id", "status", "reason", "path", "browser_task") if k in row})
            continue
        try:
            row = collect_one(match, mapping)
        except Exception as exc:
            row = {"status": "error", "match_id": mid, "reason": str(exc)[:300]}
        if row.get("status") == "ok":
            path = output_dir / f"{mid}.json"
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            row["path"] = str(path)
        rows.append({k: row.get(k) for k in ("match_id", "status", "reason", "path", "browser_task") if k in row})
    tasks = [row for row in rows if row.get("status") == "pending_browser_task"]
    if tasks:
        (output_dir / "browser_tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"schema_version": "bb-browser-evidence-run-1.0", "count": len(rows),
            "ok": sum(row.get("status") == "ok" for row in rows), "pending": len(tasks),
            "rows": rows, "output_dir": str(output_dir)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--url-map", type=Path,
                    help="可选：JSON keyed by match_id: {url, fotmob_match_id}")
    ap.add_argument("--discover", action="store_true",
                    help="无映射时按比赛身份用BB-browser发现官方/补充来源候选")
    args = ap.parse_args()
    print(json.dumps(collect_file(args.input, args.output_dir, args.url_map,
                                  discover=args.discover), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

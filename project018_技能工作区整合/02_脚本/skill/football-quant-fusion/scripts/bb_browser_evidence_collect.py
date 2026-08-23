#!/usr/bin/env python3
"""Collect optional third-party pre-match evidence through BB-browser.

BB-browser reuses the user's real browser session. This adapter deliberately
requires a per-match source mapping; it never guesses a fixture from a search
snippet. FotMob uses its structured endpoint when available, while a mapped
``scrapling_url`` can use the generic dynamic parser for other league sources.
The result is research evidence only and cannot replace the official Sporttery
market or an official starting-XI confirmation. A non-empty predicted lineup
is retained as explicit ``PREDICTED`` evidence; it is usable for pre-match
research but is never labelled as confirmed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
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
    "ligue1.com/", "seriea.com/", "legaseriea.it/", "eredivisie.eu/", "ligaportugal.pt/",
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


def _is_search_engine_url(link: str) -> bool:
    """Exclude search-engine navigation links from auditable source candidates."""
    try:
        host = (urllib.parse.urlparse(link).hostname or "").lower().rstrip(".")
    except ValueError:
        return True
    return (host == "google.com" or host.endswith(".google.com") or
            host == "google.com.hk" or host.endswith(".google.com.hk") or
            host == "google.cn" or host.endswith(".google.cn") or
            host == "googleusercontent.com" or host.endswith(".googleusercontent.com"))


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


def _probe_official_page(match: dict[str, Any], url: str) -> dict[str, Any]:
    """Run the optional Scrapling probe and return auditable page facts."""
    script = Path(__file__).with_name("official_page_probe.py")
    if not script.is_file():
        return {"status": "source_fetch_error", "source_url": url,
                "reason": "OFFICIAL_PROBE_SCRIPT_MISSING"}
    fd, name = tempfile.mkstemp(prefix="official_probe_", suffix=".json")
    os.close(fd)
    output_path = Path(name)
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--url", str(url),
             "--home", str(match.get("home") or ""),
             "--away", str(match.get("away") or ""),
             "--kickoff-date", str(match.get("kickoff") or "")[:10],
             "--output", str(output_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
        )
        if output_path.is_file():
            return json.loads(output_path.read_text(encoding="utf-8"))
        return {"status": "source_fetch_error", "source_url": url,
                "reason": (proc.stderr or proc.stdout or "OFFICIAL_PROBE_NO_OUTPUT")[-300:]}
    except Exception as exc:
        return {"status": "source_fetch_error", "source_url": url,
                "reason": str(exc)[:300]}
    finally:
        output_path.unlink(missing_ok=True)


def _scrapling_fotmob_snapshot(match: dict[str, Any], mapping: dict[str, Any],
                               collected_at: str) -> dict[str, Any]:
    """Build a research snapshot when FotMob's structured endpoint is blocked."""
    script = Path(__file__).with_name("scrapling_fotmob_fallback.py")
    spec = importlib.util.spec_from_file_location("scrapling_fotmob_fallback", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("SCRAPLING_FALLBACK_MODULE_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fd, name = tempfile.mkstemp(prefix="scrapling_fotmob_", suffix=".md")
    os.close(fd)
    output_path = Path(name)
    try:
        url = str(mapping.get("url") or "")
        proc = subprocess.run(
            ["scrapling", "extract", "fetch", url, str(output_path),
             "--ai-targeted", "--network-idle", "--wait", "2000",
             "--timeout", "60000"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "SCRAPLING_FETCH_FAILED")[-300:])
        text = output_path.read_text(encoding="utf-8", errors="replace")
        return module.parse_markdown(text, match, url, collected_at)
    finally:
        output_path.unlink(missing_ok=True)


def _scrapling_generic_snapshot(match: dict[str, Any], mapping: dict[str, Any],
                                collected_at: str) -> dict[str, Any]:
    """Fetch a mapped non-FotMob page without changing its provenance."""
    script = Path(__file__).with_name("scrapling_generic_fallback.py")
    spec = importlib.util.spec_from_file_location("scrapling_generic_fallback", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("SCRAPLING_GENERIC_MODULE_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    url = str(mapping.get("scrapling_url") or "")
    if not url:
        raise ValueError("SCRAPLING_URL_REQUIRED")
    fd, name = tempfile.mkstemp(prefix="scrapling_generic_", suffix=".md")
    os.close(fd)
    output_path = Path(name)
    try:
        proc = subprocess.run(
            ["scrapling", "extract", "fetch", url, str(output_path),
             "--ai-targeted", "--network-idle", "--wait", "2000",
             "--timeout", "60000"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "SCRAPLING_FETCH_FAILED")[-300:])
        source_id = str(mapping.get("source_id") or urllib.parse.urlparse(url).netloc or "scrapling.generic")
        provider = str(mapping.get("provider") or source_id)
        source_tier = str(mapping.get("source_tier") or "C").upper()
        if source_tier not in {"A", "B", "C", "D"}:
            source_tier = "C"
        text = output_path.read_text(encoding="utf-8", errors="replace")
        return module.parse_markdown(text, match, url, collected_at,
                                     source_id=source_id, provider=provider,
                                     source_tier=source_tier)
    finally:
        output_path.unlink(missing_ok=True)


def _scrapling_snapshot(match: dict[str, Any], mapping: dict[str, Any],
                        collected_at: str) -> dict[str, Any]:
    """Dispatch to the source-specific or source-agnostic Scrapling parser."""
    if mapping.get("scrapling_url"):
        return _scrapling_generic_snapshot(match, mapping, collected_at)
    return _scrapling_fotmob_snapshot(match, mapping, collected_at)


def _scrapling_mappings(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand one mapping into ordered, auditable Scrapling source candidates.

    ``scrapling_sources`` is deliberately opt-in: each item may be a URL or a
    mapping with its own source metadata.  Inherited metadata keeps concise
    URL-only entries useful while allowing league-specific provenance.
    """
    candidates: list[dict[str, Any]] = []
    raw = mapping.get("scrapling_sources")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                item = {"scrapling_url": item.strip()}
            if not isinstance(item, dict) or not item.get("scrapling_url"):
                continue
            candidate = dict(mapping)
            candidate.pop("scrapling_sources", None)
            candidate.update(item)
            candidates.append(candidate)
    if mapping.get("scrapling_url"):
        primary = dict(mapping)
        primary.pop("scrapling_sources", None)
        # A legacy singular URL is the first candidate unless it was already
        # listed explicitly; preserving mapping order makes retries stable.
        if not any(c.get("scrapling_url") == primary.get("scrapling_url") for c in candidates):
            candidates.insert(0, primary)
    # A FotMob mapping has no ``scrapling_url``: its page ``url`` and match id
    # identify the Scrapling-specific parser used after the API fails.
    if not candidates and mapping.get("url") and mapping.get("fotmob_match_id"):
        candidates.append(dict(mapping))
    return candidates


def _scrapling_attempts(match: dict[str, Any], mapping: dict[str, Any],
                        collected_at: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Try Scrapling candidates in order and retain failures for audit."""
    attempts: list[dict[str, Any]] = []
    for candidate in _scrapling_mappings(mapping):
        url = str(candidate.get("scrapling_url") or candidate.get("url") or "")
        try:
            snapshot = _scrapling_snapshot(match, candidate, collected_at)
            attempts.append({"source_url": url, "status": "ok"})
            return snapshot, attempts
        except Exception as exc:
            attempts.append({"source_url": url, "status": "error", "reason": str(exc)[:300]})
    return None, attempts


def _merge_scrapling_snapshot(primary: dict[str, Any], fallback: dict[str, Any]) -> bool:
    """Fill only API-missing fields; never downgrade a valid API field."""
    primary_audit = primary.get("evidence_audit") or {}
    fallback_entries = (fallback.get("evidence_audit") or {}).get("entries") or {}
    entries = primary_audit.get("entries") or {}
    usable = {"VALID", "OK", "FRESH", "AGING", "EXPLICIT_XG", "PROXY_XG", "PREDICTED", "PARTIAL"}
    changed = False
    for name, item in fallback_entries.items():
        if not isinstance(item, dict):
            continue
        if str((entries.get(name) or {}).get("status") or "UNAVAILABLE") not in usable and str(item.get("status")) in usable:
            entries[name] = item
            changed = True
    if not changed:
        return False
    missing = [name for name, item in entries.items() if str((item or {}).get("status")) not in usable]
    primary_audit["entries"] = entries
    primary_audit["missing_fields"] = missing
    primary_audit["evidence_gap"] = bool(missing)
    primary_audit["evidence_status"] = "GAP" if missing else "OK"
    primary_audit["evidence_gap_reasons"] = [
        f"{name.upper()}_{entries[name].get('missing_reason') or entries[name].get('status')}"
        for name in missing
    ]
    primary["evidence_audit"] = primary_audit
    primary["provider"] = "fotmob_api+scrapling_dynamic"
    primary["scrapling_fallback_used"] = True
    return True


def _evidence_needs_source_discovery(row: dict[str, Any]) -> bool:
    """Return true when a successful fetch still leaves auditable gaps."""
    if str(row.get("status") or "") != "ok":
        return True
    audit = row.get("evidence_audit") or {}
    return bool(audit.get("evidence_gap") or audit.get("missing_fields"))


def _discovered_mapping(discovered: dict[str, Any]) -> dict[str, Any] | None:
    """Convert classified discovery output into ordered Scrapling candidates."""
    candidates = []
    for url in (discovered.get("official_candidates") or []):
        candidates.append({"scrapling_url": url, "source_id": "discovered.official",
                           "provider": "discovered_official", "source_tier": "A"})
    for url in (discovered.get("third_party_candidates") or []):
        candidates.append({"scrapling_url": url, "source_id": "discovered.third_party",
                           "provider": "discovered_third_party", "source_tier": "C"})
    if not candidates:
        return None
    return {"scrapling_sources": candidates, "source_discovery": discovered,
            "scrapling_fallback": True}


def _llm_md_value(value: Any) -> str:
    """Keep structured Scrapling facts readable and bounded in Markdown."""
    if value in (None, "", [], {}):
        return "facts_available=false"
    if isinstance(value, dict) and set(value) == {"raw_rows"}:
        value = value.get("raw_rows")
    try:
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        rendered = str(value)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    return "facts_available=true; " + rendered[:1800]


def render_llm_markdown(row: dict[str, Any], match: dict[str, Any]) -> str:
    """Render a browser sidecar as an auditable supplemental LLM evidence block.

    This is deliberately a supplement, not a replacement for the human/web
    primary evidence file.  Every promoted fact keeps field status, timestamp,
    source identity, URL and source tier in the same line for the LLM catalog.
    """
    audit = row.get("evidence_audit") or {}
    entries = audit.get("entries") or {}
    collected_at = row.get("collected_at") or audit.get("collected_at") or ""
    row_source_tier = str(row.get("source_tier") or "C").upper()
    if row_source_tier not in {"A", "B", "C", "D"}:
        row_source_tier = "C"
    sections = {
        "1. 伤停与阵容": ("injury", "suspensions", "starting_xi"),
        "2. 战意与动机": (),
        "3. 近况与状态": ("recent_form",),
        "4. 主客/旅行/天气": (),
        "5. 赔率": (),
        "6. 身份核验": (),
    }
    lines = [
        f"# 浏览器/Scrapling 补充证据: {match.get('home', '')} vs {match.get('away', '')}",
        f"> match_identity(sporttery_match_id={match.get('match_id', '')};home={match.get('home', '')};away={match.get('away', '')};api_match_id=)",
        f"> collected_at({collected_at}) | research_only=true | provider({row.get('provider', 'scrapling')})",
        "",
    ]
    for title, fields in sections.items():
        lines.append(f"## {title}")
        if not fields:
            lines.append("- 本补充源未提供该类事实，不能按无影响处理。")
            continue
        for field in fields:
            entry = entries.get(field) or {}
            status = str(entry.get("status") or "UNAVAILABLE").upper()
            value = _llm_md_value(entry.get("value"))
            source_url = entry.get("source_url") or row.get("source_url") or ""
            source_id = entry.get("source_id") or row.get("provider") or "scrapling"
            source_tier = str(entry.get("source_tier") or row_source_tier).upper()
            refreshed = entry.get("refreshed_at") or collected_at
            lines.append(
                f"- {field}: status={status}; {value} | source({source_url}) "
                f"| collected_at({refreshed}) | source_id({source_id}) | source_tier({source_tier})"
            )
    return "\n".join(lines) + "\n"


def _write_llm_markdown(output_dir: Path, row: dict[str, Any], match: dict[str, Any], index: int) -> Path:
    """Write a deterministic supplemental filename understood by predict.py."""
    raw_num = match.get("match_num") or index
    try:
        number = int(str(raw_num))
    except (TypeError, ValueError):
        number = index
    def safe(value: Any) -> str:
        text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(value or "")).strip("_")
        return text or "unknown"
    path = output_dir / f"evidence_{number:03d}_{safe(match.get('home'))}_{safe(match.get('away'))}_browser.md"
    path.write_text(render_llm_markdown(row, match), encoding="utf-8")
    return path


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
        links = list(dict.fromkeys(
            str(link) for link in (links or [])
            if str(link).startswith("http") and not _is_search_engine_url(str(link))
        ))
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
              provider: str = "fotmob_via_bb_browser",
              predicted_xi: dict[str, Any] | None = None,
              predicted_xi_source_url: str | None = None) -> dict[str, Any]:
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
    if isinstance(predicted_xi, dict) and (predicted_xi.get("home") or predicted_xi.get("away")):
        # A browser-captured media preview may provide an expected XI even
        # when FotMob's structured endpoint has no lineup yet.  Preserve the
        # explicit PREDICTED status and the media URL; never promote it to
        # confirmed/official.
        home_team = {**home_team, "starters": predicted_xi.get("home") or [],
                     "formation": predicted_xi.get("home_formation") or home_team.get("formation")}
        away_team = {**away_team, "starters": predicted_xi.get("away") or [],
                     "formation": predicted_xi.get("away_formation") or away_team.get("formation")}
        lineup_source = str(predicted_xi.get("source") or "predicted_media_preview")
        source_url = predicted_xi_source_url or source_url
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
    generic_url = mapping.get("scrapling_url") or next(
        (item.get("scrapling_url") if isinstance(item, dict) else item
         for item in (mapping.get("scrapling_sources") or [])
         if (isinstance(item, str) and item.strip()) or
            (isinstance(item, dict) and item.get("scrapling_url"))), None)
    if not url and not generic_url:
        return {"status": "pending_browser_task", "match_id": match.get("match_id"),
                "browser_task": {"reason": "FOTMOB_URL_AND_MATCH_ID_REQUIRED"}}
    if not fotmob_id and not generic_url:
        return {"status": "pending_browser_task", "match_id": match.get("match_id"),
                "browser_task": {"reason": "SCRAPLING_URL_REQUIRED_FOR_GENERIC_SOURCE"}}
    if not fotmob_id:
        collected_at = datetime.now(UTC).isoformat(timespec="seconds")
        snapshot, attempts = _scrapling_attempts(match, mapping, collected_at)
        if snapshot is not None:
            row = {"status": "ok", **snapshot}
            row["scrapling_attempts"] = attempts
            official_url = mapping.get("official_url")
            if official_url:
                row["official_page_probe"] = _probe_official_page(match, str(official_url))
            return row
        return {"status": "source_fetch_error", "match_id": match.get("match_id"),
                "reason": "ALL_SCRAPLING_SOURCES_FAILED", "evidence_gap": True,
                "scrapling_attempts": attempts, "scrapling_fallback_used": False}
    tab = None
    collected_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        tab = _tab_id(_run_browser(["open", str(url)]))
        # Function syntax survives the Windows bb-browser.cmd argument parser;
        # arrow functions are truncated by the shim in subprocess mode.
        # Use an absolute origin: BB-browser may leave the tab on a consent or
        # redirect page, and a relative fetch then has no valid base URL.  The
        # explicit FotMob origin also prevents accidentally querying a prior
        # tab's domain while preserving the same logged-in browser context.
        api_url = "https://www.fotmob.com/api/data/matchDetails?matchId=" + urllib.parse.quote(str(fotmob_id), safe="")
        expression = f'fetch("{api_url}").then(function(r){{return r.text()}})'
        payload = _extract_json(_run_browser(["eval", "--tab", tab, expression]))
        general = payload.get("general") or {}
        if general.get("started") or general.get("finished"):
            return {"status": "post_kickoff", "match_id": match.get("match_id"),
                    "reason": "BROWSER_SOURCE_SAYS_MATCH_STARTED"}
        row = {"status": "ok", **_snapshot(
            match, payload, str(url), collected_at,
            source_id=str(mapping.get("source_id") or "fotmob.bb_browser"),
            provider=str(mapping.get("provider") or "fotmob_via_bb_browser"),
            predicted_xi=mapping.get("predicted_xi"),
            predicted_xi_source_url=mapping.get("predicted_xi_source_url"),
        )}
        if mapping.get("scrapling_fallback") and (row.get("evidence_audit") or {}).get("missing_fields"):
            fallback, attempts = _scrapling_attempts(match, mapping, collected_at)
            row["scrapling_attempts"] = attempts
            if fallback is not None:
                row["scrapling_fallback_used"] = _merge_scrapling_snapshot(row, fallback)
            else:
                row["scrapling_fallback_used"] = False
        official_url = mapping.get("official_url")
        if official_url:
            row["official_page_probe"] = _probe_official_page(match, str(official_url))
        return row
    except Exception:
        # The dynamic Scrapling path is a bounded research-only fallback for
        # API blocks/rate limits.  If it is unavailable, retain the older
        # explicit predicted-XI fallback below.
        dynamic, attempts = _scrapling_attempts(match, mapping, collected_at)
        if dynamic is not None:
            dynamic["scrapling_attempts"] = attempts
            return {"status": "ok", **dynamic}
        # A source page can be reachable while its structured FotMob endpoint
        # is blocked/rate-limited.  If a browser review already captured an
        # explicit predicted XI in the mapping, retain that auditable fact
        # instead of discarding it; leave other fields as unavailable.
        predicted = mapping.get("predicted_xi") if isinstance(mapping, dict) else None
        if not isinstance(predicted, dict) or not (predicted.get("home") or predicted.get("away")):
            raise
        payload = {"general": {"started": False, "finished": False},
                   "content": {"matchFacts": {}, "lineup": {}}}
        row = {"status": "ok", **_snapshot(
            match, payload, str(url), collected_at,
            source_id=str(mapping.get("source_id") or "fotmob.bb_browser"),
            provider=str(mapping.get("provider") or "fotmob_via_bb_browser"),
            predicted_xi=predicted,
            predicted_xi_source_url=mapping.get("predicted_xi_source_url"),
        )}
        official_url = mapping.get("official_url")
        if official_url:
            row["official_page_probe"] = _probe_official_page(match, str(official_url))
        return row
    finally:
        if tab:
            try:
                _run_browser(["close", "--tab", tab])
            except Exception:
                pass


def collect_file(input_path: Path, output_dir: Path, url_map_path: Path | None,
                 *, discover: bool = False, scrape_discovered: bool = False) -> dict[str, Any]:
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
        # Allow a producer to carry its per-match source candidates with the
        # fixture itself.  This removes a fragile sidecar join while keeping
        # provenance explicit; arbitrary search results are still rejected.
        if not mapping:
            embedded = match.get("evidence_sources")
            if isinstance(embedded, dict):
                mapping = embedded
            elif any(match.get(name) for name in ("url", "fotmob_match_id",
                                                   "scrapling_url", "scrapling_sources")):
                mapping = {name: match.get(name) for name in (
                    "url", "fotmob_match_id", "scrapling_url", "scrapling_sources",
                    "source_id", "provider", "official_url", "official_domains",
                    "predicted_xi", "predicted_xi_source_url", "source_tier") if match.get(name) is not None}
        if isinstance(mapping, dict):
            mapping = dict(mapping)
            mapping.setdefault("scrapling_fallback", True)
        if not mapping and discover:
            discovered = discover_sources(match)
            # Discovery is deliberately limited to links classified as
            # official or known football-data providers.  When enabled, feed
            # those candidates into the same ordered Scrapling fallback used
            # by API failures; arbitrary search results remain review-only.
            if scrape_discovered and discovered.get("status") == "source_candidates_found":
                mapping = _discovered_mapping(discovered)
                if mapping:
                    row = collect_one(match, mapping)
                    if row.get("status") == "ok":
                        row["source_discovery"] = discovered
                        path = output_dir / f"{mid}.json"
                        path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
                        row["path"] = str(path)
                        row["markdown_path"] = str(_write_llm_markdown(output_dir, row, match, len(rows) + 1))
                        rows.append({k: row.get(k) for k in
                                     ("match_id", "status", "reason", "path", "markdown_path", "browser_task")
                                     if k in row})
                        continue
            row = {"status": "pending_browser_task", "match_id": mid,
                   "browser_task": {"reason": "SOURCE_REVIEW_REQUIRED",
                                    "match": match, "discovery": discovered,
                                    "scrapling_attempted": bool(scrape_discovered)}}
            rows.append({k: row.get(k) for k in ("match_id", "status", "reason", "path", "browser_task") if k in row})
            continue
        try:
            row = collect_one(match, mapping)
        except Exception as exc:
            row = {"status": "error", "match_id": mid, "reason": str(exc)[:300]}
        # A mapped API/FotMob source may be reachable yet omit injuries, form,
        # or lineups.  Treat that as a trigger for cross-source discovery too;
        # otherwise a partial success would incorrectly terminate the fallback
        # chain before the league's official/secondary pages are tried.
        if (discover and scrape_discovered and mapping and
                _evidence_needs_source_discovery(row)):
            discovered = discover_sources(match)
            discovered_mapping = (
                _discovered_mapping(discovered)
                if discovered.get("status") == "source_candidates_found" else None
            )
            if discovered_mapping:
                discovered_row = collect_one(match, discovered_mapping)
                if row.get("status") == "ok" and discovered_row.get("status") == "ok":
                    attempts = discovered_row.get("scrapling_attempts") or []
                    row["scrapling_attempts"] = (row.get("scrapling_attempts") or []) + attempts
                    _merge_scrapling_snapshot(row, discovered_row)
                    row["source_discovery"] = discovered
                elif discovered_row.get("status") == "ok":
                    row = discovered_row
                    row["source_discovery"] = discovered
        if row.get("status") == "ok":
            path = output_dir / f"{mid}.json"
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            row["path"] = str(path)
            row["markdown_path"] = str(_write_llm_markdown(output_dir, row, match, len(rows) + 1))
        rows.append({k: row.get(k) for k in
                     ("match_id", "status", "reason", "path", "markdown_path", "browser_task") if k in row})
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
                    help=("可选：JSON keyed by match_id；FotMob 使用 {url, fotmob_match_id}，"
                          "其他来源使用 {scrapling_url, source_id, provider}"))
    ap.add_argument("--discover", action="store_true",
                    help="无映射时按比赛身份用BB-browser发现官方/补充来源候选")
    ap.add_argument("--scrape-discovered", action="store_true",
                    help="发现候选后按官方→第三方顺序自动用Scrapling抓取；失败仍生成待复核任务")
    args = ap.parse_args()
    print(json.dumps(collect_file(args.input, args.output_dir, args.url_map,
                                  discover=args.discover,
                                  scrape_discovered=args.scrape_discovered), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

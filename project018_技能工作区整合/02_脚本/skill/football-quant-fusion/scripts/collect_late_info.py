#!/usr/bin/env python3
"""伤停 + 动态赛前首发采集。只写研究库，不改生产 input / 不登记。

伤停：体彩 getInjurySuspensionV1（有 sporttery match_id 即可）。
首发：API-Sports /fixtures/lineups，要求先经队名别名和开球时间映射到
api_sports_fixture_id；在固定的赛前初始窗口采集，并可持续轮询到开球，
不依赖单一 T-75 时刻。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime_paths import core_scripts_dir, forward_work_dir, late_info_store

CORE = core_scripts_dir()
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
import fetch_match_preview as preview  # noqa: E402
from sporttery_trained_aliases import SPORTTERY_TO_TRAINED  # noqa: E402

CST = timezone(timedelta(hours=8))
# The first refresh is deliberately a broad, fixed window.  It is not a
# claim that lineups are published at this offset; providers may publish
# earlier or later, so --watch can retry until kickoff.
INITIAL_REFRESH_MINUTES = 24 * 60
# Kept only so historical callers/tests can inspect the old diagnostic helper.
# Production collection never uses this value as a gate.
T75_MINUTES = 75
API_SPORTS_BASE = "https://v3.football.api-sports.io"
ALIAS_CONFIG = Path(__file__).resolve().parents[1] / "config" / "intl_odds_sources.json"
try:
    TEAM_ALIASES = json.loads(ALIAS_CONFIG.read_text(encoding="utf-8")).get("team_aliases") or {}
except (OSError, ValueError):
    TEAM_ALIASES = {}
CAP = {
    "Forward": (0.10, 0.00),
    "Midfielder": (0.06, 0.03),
    "Defender": (0.01, 0.09),
    "Goalkeeper": (0.00, 0.00),
}

# API-Sports occasionally publishes the same synthetic/future fixture one
# local calendar day earlier than Sporttery.  Date-shift matching is therefore
# permitted only with an explicit league and two-sided team alias match.
COMPETITION_ALIASES = {
    "意甲": {"Serie A"}, "英超": {"Premier League"}, "英冠": {"Championship"},
    "西甲": {"La Liga"}, "法甲": {"Ligue 1"}, "法乙": {"Ligue 2"},
    "葡超": {"Primeira Liga"}, "荷甲": {"Eredivisie"}, "德甲": {"Bundesliga"},
    "瑞超": {"Allsvenskan"}, "挪超": {"Eliteserien"}, "巴甲": {"Serie A"},
    "美职": {"Major League Soccer"}, "日职": {"J1 League"}, "韩职": {"K League 1"},
}


def now_utc():
    return datetime.now(timezone.utc)


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


def minutes_to_kickoff(kickoff, at=None) -> float | None:
    if not isinstance(kickoff, datetime):
        kickoff = parse_dt(kickoff)
    if kickoff is None:
        return None
    at = at or now_utc()
    return (kickoff - at).total_seconds() / 60.0


def in_t75_window(kickoff, at=None, window=T75_MINUTES) -> bool:
    """Backward-compatible diagnostic; never gates collection anymore."""
    mins = minutes_to_kickoff(kickoff, at)
    return mins is not None and 0 < mins <= window


def in_collection_window(kickoff, at=None, window=INITIAL_REFRESH_MINUTES) -> bool:
    """Return whether the fixed initial pre-match refresh window is active."""
    mins = minutes_to_kickoff(kickoff, at)
    return mins is not None and 0 < mins <= window


def fold_side(block: dict) -> dict:
    lst = (block or {}).get("injuriesAndSuspensionsList") or []
    atk = dfs = gk = 0.0
    players = []
    for p in lst:
        pos = p.get("playerPositionCode") or ""
        ap = float(p.get("appearanceCnt") or 0)
        st = float(p.get("startedMatchCnt") or 0)
        w = min(1.0, (st + (ap - st) * 0.5) / 10.0)
        a, d = CAP.get(pos, (0.05, 0.04))
        if pos == "Goalkeeper":
            gk += 0.10 * w
        atk += a * w
        dfs += d * w
        players.append({
            "name": p.get("personName"),
            "pos": p.get("playerPositionDesc"),
            "apps": int(ap),
            "starts": int(st),
            "type": "伤" if p.get("injuryFlag") else ("停" if p.get("suspensionFlag") else "?"),
            "weight": round(w, 2),
        })
    clip = lambda x: round(min(0.5, max(0.0, x)), 4)
    return {
        "team": (block or {}).get("teamShortName"),
        "count": len(lst),
        "status": "VALID" if lst else "EMPTY_UNCONFIRMED",
        "attack_absence": clip(atk),
        "defense_absence": clip(dfs),
        "gk_absence": clip(gk),
        "players": players,
    }


def fold_injuries(raw) -> dict:
    raw = raw or {}
    home = fold_side(raw.get("home") or {})
    away = fold_side(raw.get("away") or {})
    return {
        "home": home,
        "away": away,
        "attack_absence_home": home["attack_absence"],
        "attack_absence_away": away["attack_absence"],
        "defense_absence_home": home["defense_absence"],
        "defense_absence_away": away["defense_absence"],
        "gk_absence_home": home["gk_absence"],
        "gk_absence_away": away["gk_absence"],
    }


def load_matches(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("matches"), list):
        return data["matches"]
    if isinstance(data, list):
        return data
    return []


def match_id_of(rec: dict):
    mid = rec.get("match_id") or (rec.get("sporttery_meta") or {}).get("match_id")
    try:
        return int(str(mid).replace("sporttery-", ""))
    except (TypeError, ValueError):
        return None


def odds_at_of(rec: dict):
    meta = rec.get("field_meta") or {}
    odds_meta = meta.get("odds") or {}
    return parse_dt(
        odds_meta.get("observed_at")
        or odds_meta.get("source_updated_at")
        or rec.get("had_updated_at")
        or rec.get("collected_at")
    )


def kickoff_of(rec: dict):
    return parse_dt(rec.get("kickoff") or rec.get("kickoff_iso"))


def api_match_id_of(rec: dict):
    return (
        rec.get("apifootball_match_id")
        or rec.get("api_match_id")
        or (rec.get("external_ids") or {}).get("apifootball")
        or (rec.get("provider_refs") or {}).get("apifootball_match_id")
    )


def api_sports_fixture_id_of(rec: dict):
    return (
        rec.get("api_sports_fixture_id")
        or (rec.get("provider_refs") or {}).get("api_sports_fixture_id")
    )


def normalized_name(value) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def team_candidates(name) -> list[str]:
    """Return the Sporttery label and its verified provider aliases."""
    key = str(name or "")
    # ``intl_odds_sources.json`` is the full alias authority; the trained
    # aliases supplement leagues not represented there.
    return [key, *TEAM_ALIASES.get(key, []), *SPORTTERY_TO_TRAINED.get(key, [])]


def competition_candidates(name) -> set[str]:
    return {str(name or ""), *COMPETITION_ALIASES.get(str(name or ""), set())}


def resolve_api_sports_fixture_ids(matches: list[dict], fetch_by_utc_date) -> dict[int, dict]:
    """Attach a unique API-Sports fixture ID without altering formal market data.

    ``fetch_by_utc_date`` is deliberately injected so identity matching stays
    testable and the network boundary remains outside this pure resolver.
    """
    rows_by_date: dict[str, list[dict]] = {}
    resolved: dict[int, dict] = {}
    for rec in matches:
        mid = match_id_of(rec)
        kickoff = kickoff_of(rec)
        if mid is None or kickoff is None:
            continue
        existing = rec.get("api_sports_fixture_id") or (rec.get("provider_refs") or {}).get("api_sports_fixture_id")
        if existing:
            resolved[mid] = {"status": "resolved", "fixture_id": existing}
            continue
        day = kickoff.astimezone(timezone.utc).date().isoformat()
        if day not in rows_by_date:
            try:
                payload = fetch_by_utc_date(day)
                rows_by_date[day] = payload if isinstance(payload, list) else []
            except Exception:
                rows_by_date[day] = []
        home = {normalized_name(v) for v in team_candidates(rec.get("home")) if normalized_name(v)}
        away = {normalized_name(v) for v in team_candidates(rec.get("away")) if normalized_name(v)}
        candidates = []

        def inspect_rows(rows: list[dict]) -> None:
            for row in rows:
                fixture = row.get("fixture") or {}
                teams = row.get("teams") or {}
                try:
                    provider_kickoff = parse_dt(fixture.get("date"))
                except (TypeError, ValueError):
                    provider_kickoff = None
                provider_home_raw = (teams.get("home") or {}).get("name")
                provider_away_raw = (teams.get("away") or {}).get("name")
                provider_home = normalized_name(provider_home_raw)
                provider_away = normalized_name(provider_away_raw)
                fixture_id = fixture.get("id")
                if provider_kickoff is None or fixture_id is None or provider_home not in home or provider_away not in away:
                    continue
                delta = abs((provider_kickoff - kickoff).total_seconds())
                same_time = delta <= 5400
                shifted_day = abs(delta - 86400) <= 5400
                provider_league = ((row.get("league") or {}).get("name"))
                league_ok = normalized_name(provider_league) in {
                    normalized_name(value) for value in competition_candidates(rec.get("competition"))
                }
                if same_time or (shifted_day and league_ok):
                    candidate = (fixture_id, "exact_team_time" if same_time else "exact_team_league_date_shift")
                    if candidate not in candidates:
                        candidates.append(candidate)

        inspect_rows(rows_by_date[day])
        # The API's `date` filter can be interpreted in its provider timezone,
        # while the returned timestamp is rendered in another timezone.  If
        # the first calendar day yields no identity candidate, inspect the two
        # adjacent days; team, league and time gates still decide acceptance.
        if not candidates:
            requested = datetime.fromisoformat(day).date()
            for adjacent in (requested - timedelta(days=1), requested + timedelta(days=1)):
                adjacent_day = adjacent.isoformat()
                if adjacent_day not in rows_by_date:
                    try:
                        payload = fetch_by_utc_date(adjacent_day)
                        rows_by_date[adjacent_day] = payload if isinstance(payload, list) else []
                    except Exception:
                        rows_by_date[adjacent_day] = []
                inspect_rows(rows_by_date[adjacent_day])
        if len(candidates) == 1:
            fixture_id, method = candidates[0]
            rec["api_sports_fixture_id"] = fixture_id
            if method != "exact_team_time":
                rec["api_sports_fixture_match_method"] = method
                resolved[mid] = {"status": "resolved", "fixture_id": fixture_id, "method": method}
            else:
                resolved[mid] = {"status": "resolved", "fixture_id": fixture_id}
        else:
            resolved[mid] = {
                "status": "SOURCE_CONFLICT" if len(candidates) > 1 else "UNAVAILABLE",
                "reason": f"fixture_match_count={len(candidates)}",
            }
    return resolved


def fetch_api_sports_fixtures(utc_date: str) -> list[dict]:
    """Fetch one UTC calendar day from the configured API-Sports account."""
    key = (os.environ.get("API_FOOTBALL_KEY") or "").strip()
    if not key:
        return []
    import urllib.parse
    import urllib.request
    url = API_SPORTS_BASE + "/fixtures?" + urllib.parse.urlencode({
        "date": utc_date,
        "timezone": "UTC",
    })
    try:
        req = urllib.request.Request(url, headers={"x-apisports-key": key})
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.load(response)
    except Exception:
        return []
    rows = payload.get("response") if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else []


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_injury(mid: int) -> dict | None:
    return preview.fetch(f"getInjurySuspensionV1.qry?sportteryMatchId={mid}")


def fetch_api_sports_lineup(fixture_id) -> list[dict] | None:
    """Fetch API-Sports lineups by the provider fixture identity."""
    key = (os.environ.get("API_FOOTBALL_KEY") or "").strip()
    if not key or not fixture_id:
        return None
    import urllib.parse
    import urllib.request
    url = API_SPORTS_BASE + "/fixtures/lineups?" + urllib.parse.urlencode({"fixture": str(fixture_id)})
    try:
        req = urllib.request.Request(url, headers={"x-apisports-key": key})
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.load(response)
    except Exception:
        return None
    rows = payload.get("response") if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else None


def fold_api_sports_lineup(rec: dict, rows: list[dict] | None) -> dict | None:
    """Map API-Sports' team-named lineup rows to audited home/away sides."""
    if not isinstance(rows, list):
        return None
    sides = {
        "home": {normalized_name(v) for v in team_candidates(rec.get("home")) if normalized_name(v)},
        "away": {normalized_name(v) for v in team_candidates(rec.get("away")) if normalized_name(v)},
    }
    out = {side: {"starting_count": 0, "missing_count": 0, "starting": [], "missing": []}
           for side in ("home", "away")}
    for block in rows:
        provider_team = normalized_name((block.get("team") or {}).get("name"))
        side = next((key for key, aliases in sides.items() if provider_team in aliases), None)
        if side is None:
            continue
        starters = [
            (item.get("player") or {}).get("name")
            for item in (block.get("startXI") or []) if isinstance(item, dict)
        ]
        out[side]["starting"] = [name for name in starters if name]
        out[side]["starting_count"] = len(out[side]["starting"])
    if out["home"]["starting_count"] == 0 and out["away"]["starting_count"] == 0:
        return None
    return out


def base_row(rec, kind, snapshot, collected_at, odds_at, kickoff):
    mid = match_id_of(rec)
    late = bool(odds_at and collected_at and kickoff and odds_at < collected_at < kickoff)
    return {
        "schema": "late-info-1.0",
        "research_only": True,
        "production_unchanged": True,
        "kind": kind,
        "match_id": mid,
        "home": rec.get("home"),
        "away": rec.get("away"),
        "kickoff": kickoff.isoformat() if kickoff else None,
        "odds_at": odds_at.isoformat() if odds_at else None,
        "collected_at": collected_at.isoformat(),
        "snapshot": snapshot,
        "gate": {
            "late": late,
            "minutes_to_kickoff": None if kickoff is None else round(minutes_to_kickoff(kickoff, collected_at), 2),
            "in_collection_window": in_collection_window(kickoff, collected_at),
        },
    }


def collect_one(rec, snapshot, want_injury, want_lineup, events_path):
    collected_at = now_utc()
    kickoff = kickoff_of(rec)
    odds_at = odds_at_of(rec)
    mid = match_id_of(rec)
    out = []
    if want_injury and mid:
        row = base_row(rec, "injury", snapshot, collected_at, odds_at, kickoff)
        # Injury endpoints often return the post-match squad report as well;
        # never allow that response to enter a pre-match evidence sidecar.
        if kickoff and collected_at >= kickoff:
            row["status"] = "POST_KICKOFF"
        else:
            raw = fetch_injury(mid)
            if raw is None:
                row["status"] = "UNAVAILABLE"
            else:
                folded = fold_injuries(raw)
                row["status"] = "VALID" if (folded["home"]["count"] or folded["away"]["count"]) else "EMPTY_UNCONFIRMED"
                row["absence"] = folded
        append_jsonl(events_path, row)
        out.append(row)
    if want_lineup:
        row = base_row(rec, "lineup", snapshot, collected_at, odds_at, kickoff)
        if kickoff and collected_at >= kickoff:
            row["status"] = "POST_KICKOFF"
        elif not in_collection_window(kickoff, collected_at):
            row["status"] = "TOO_EARLY"
        else:
            fixture_id = api_sports_fixture_id_of(rec)
            if not fixture_id:
                row["status"] = "NO_API_ID"
            else:
                lineup = fold_api_sports_lineup(rec, fetch_api_sports_lineup(fixture_id))
                if lineup is None:
                    row["status"] = "UNAVAILABLE"
                else:
                    row["status"] = "VALID"
                    row["lineup"] = lineup
                    row["api_sports_fixture_id"] = fixture_id
        if row["status"] != "TOO_EARLY":
            append_jsonl(events_path, row)
            out.append(row)
    return out


def should_retry_lineup(rows: list[dict]) -> bool:
    """Keep a watched match pending until a provider has actual starters."""
    return not any(row.get("kind") == "lineup" and row.get("status") == "VALID" for row in rows)


def write_due(path: Path, matches: list[dict], snapshot: str) -> list[dict]:
    due = []
    for rec in matches:
        kickoff = kickoff_of(rec)
        if kickoff is None:
            continue
        due.append({
            "match_id": match_id_of(rec),
            "home": rec.get("home"),
            "away": rec.get("away"),
            "kickoff": kickoff.isoformat(),
            "initial_refresh_at_or_after": (kickoff - timedelta(minutes=INITIAL_REFRESH_MINUTES)).isoformat(),
            "odds_at": odds_at_of(rec).isoformat() if odds_at_of(rec) else None,
            "apifootball_match_id": api_match_id_of(rec),
            "api_sports_fixture_id": api_sports_fixture_id_of(rec),
            "lineup_provider": "api-sports.io",
            "snapshot": snapshot,
            "research_only": True,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "late-info-due-1.0",
        "research_only": True,
        "refresh_policy": "initial_plus_poll_until_kickoff",
        "initial_refresh_minutes": INITIAL_REFRESH_MINUTES,
        "matches": due,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return due


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-collect", type=Path, required=True)
    ap.add_argument("--snapshot", default="T-7h")
    ap.add_argument("--work-dir", type=Path)
    ap.add_argument("--events", type=Path)
    ap.add_argument("--watch", action="store_true", help="在初始赛前窗口内轮询首发直到开球")
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    src = args.from_collect.resolve()
    matches = load_matches(src)
    work = (args.work_dir or src.parent).resolve()
    events_path = (args.events or late_info_store() / "events.jsonl").resolve()
    # The mapping belongs to the research sidecar only.  Formal Sporttery
    # input remains immutable; the in-memory ID is consumed by this run and
    # written to the due manifest / late-info evidence.
    resolve_api_sports_fixture_ids(matches, fetch_api_sports_fixtures)
    due_path = work / "late_info_due.json"
    due = write_due(due_path, matches, args.snapshot)

    collected = []
    for rec in matches:
        collected.extend(collect_one(
            rec, args.snapshot, want_injury=True,
            want_lineup=in_collection_window(kickoff_of(rec)),
            events_path=events_path))
        time.sleep(0.4)

    if args.watch and not args.once:
        pending = [rec for rec in matches if kickoff_of(rec) and kickoff_of(rec) > now_utc()]
        while pending:
            time.sleep(max(5, args.poll_seconds))
            still = []
            for rec in pending:
                kickoff = kickoff_of(rec)
                if kickoff is None or now_utc() >= kickoff:
                    continue
                if in_collection_window(kickoff):
                    rows = collect_one(
                        rec, "prematch_poll", want_injury=True, want_lineup=True, events_path=events_path)
                    collected.extend(rows)
                    if should_retry_lineup(rows):
                        still.append(rec)
                else:
                    still.append(rec)
            pending = still

    summary = {
        "status": "ok",
        "research_only": True,
        "production_unchanged": True,
        "source": str(src),
        "events": str(events_path),
        "due": str(due_path),
        "matches": len(matches),
        "due_n": len(due),
        "wrote": len(collected),
        "injury_valid": sum(1 for r in collected if r.get("kind") == "injury" and r.get("status") == "VALID"),
        "injury_empty_unconfirmed": sum(1 for r in collected if r.get("kind") == "injury" and r.get("status") == "EMPTY_UNCONFIRMED"),
        "lineup_valid": sum(1 for r in collected if r.get("kind") == "lineup" and r.get("status") == "VALID"),
        "lineup_no_api_id": sum(1 for r in collected if r.get("status") == "NO_API_ID"),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

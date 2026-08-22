"""Auditable LLM evidence enrichment for Sporttery and API-Football v3."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


API_BASE = "https://v3.football.api-sports.io"


def _dt(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return parsed


def _fact(label, value, source, collected_at):
    return f"- {label}: {value} | source({source}) | collected_at({collected_at})"


def _pairs(values):
    if not isinstance(values, dict):
        return "UNAVAILABLE"
    return " / ".join(f"{key}={value}" for key, value in values.items()) or "UNAVAILABLE"


def render_sporttery_markets(raw_match, collected_at):
    """Render every official Sporttery market already present in the raw match."""
    source = raw_match.get("fixed_bonus_url") or "https://webapi.sporttery.cn/"
    had = raw_match.get("model_odds")
    hhad = raw_match.get("model_hhad") or {}
    lines = ["## 体彩官方衍生市场"]
    if isinstance(had, list) and len(had) >= 3:
        lines.append(_fact("HAD", f"主={had[0]} / 平={had[1]} / 客={had[2]}", source, collected_at))
    if hhad:
        lines.append(_fact("HHAD", f"让球={hhad.get('line')} / 赔率={hhad.get('odds')}", source, collected_at))
    lines.append(_fact("CRS 比分赔率", _pairs(raw_match.get("crs")), source, collected_at))
    lines.append(_fact("TTG 总进球赔率", _pairs(raw_match.get("ttg")), source, collected_at))
    lines.append(_fact("HAFU 半全场赔率", _pairs(raw_match.get("hafu")), source, collected_at))
    return "\n".join(lines)


def render_recent_form(payload, collected_at):
    source = f"{API_BASE}/fixtures"
    lines = ["## API-Football 最近5场"]
    for side, label in (("home", "主队近况"), ("away", "客队近况")):
        rows = list((payload or {}).get(side) or [])[:5]
        if not rows:
            lines.append(_fact(label, "UNAVAILABLE", source, collected_at))
            continue
        for row in rows:
            value = (f"{row.get('date')} | {row.get('league')} | {row.get('home')} "
                     f"{row.get('score_90')} {row.get('away')} | status={row.get('status')}")
            lines.append(_fact(label, value, source, collected_at))
    return "\n".join(lines)


def refresh_due(kickoff, now, before_minutes=75):
    delta = _dt(kickoff) - _dt(now)
    return timedelta(0) < delta <= timedelta(minutes=before_minutes)


def write_canonical_snapshot(path, text, collected_at):
    """Archive the previous canonical and atomically publish the new one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    archived = None
    if path.exists():
        old = path.read_bytes()
        stamp = _dt(collected_at).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        digest = hashlib.sha256(old).hexdigest()[:12]
        archive_dir = path.parent / "snapshots"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived_path = archive_dir / f"{path.stem}_{stamp}_{digest}{path.suffix}"
        archived_path.write_bytes(old)
        archived = str(archived_path)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
    return {"path": str(path), "archived": archived,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _normal(value):
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _normal_names(value):
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    return {_normal(item) for item in values if _normal(item)}


def _normalize_fixture(row):
    status = ((row.get("fixture") or {}).get("status") or {}).get("short")
    score = (row.get("score") or {}).get("fulltime") or {}
    if score.get("home") is None or score.get("away") is None:
        score = row.get("goals") or {}
    return {
        "date": (row.get("fixture") or {}).get("date"),
        "league": (row.get("league") or {}).get("name"),
        "home": ((row.get("teams") or {}).get("home") or {}).get("name"),
        "away": ((row.get("teams") or {}).get("away") or {}).get("name"),
        "score_90": f"{score.get('home')}-{score.get('away')}",
        "status": status,
    }


class ApiSportsClient:
    def __init__(self, transport=None, api_key=None, timeout=30):
        self.transport = transport
        self.api_key = api_key
        self.timeout = timeout

    def _key(self):
        key = self.api_key or os.environ.get("API_FOOTBALL_KEY", "").strip()
        if not key and os.name == "nt":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as reg:
                    key = str(winreg.QueryValueEx(reg, "API_FOOTBALL_KEY")[0]).strip()
            except (FileNotFoundError, OSError):
                pass
        return key

    def _request(self, path, params):
        if self.transport:
            return self.transport(path, params)
        key = self._key()
        if not key:
            raise RuntimeError("API_FOOTBALL_KEY unavailable")
        url = API_BASE + path + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"x-apisports-key": key})
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return json.load(response)

    def collect_match(self, home, away, kickoff):
        kick = _dt(kickoff)
        home_names, away_names = _normal_names(home), _normal_names(away)
        try:
            fixtures = self._request("/fixtures", {
                "date": kick.astimezone(timezone.utc).date().isoformat(), "timezone": "UTC",
            }).get("response", [])
        except Exception as exc:
            return {"status": "UNAVAILABLE", "reason": f"fixture_fetch:{type(exc).__name__}"}
        matches = []
        for row in fixtures:
            teams = row.get("teams") or {}
            if (_normal((teams.get("home") or {}).get("name")) not in home_names
                    or _normal((teams.get("away") or {}).get("name")) not in away_names):
                continue
            try:
                event_time = _dt((row.get("fixture") or {}).get("date"))
            except (TypeError, ValueError):
                continue
            if abs((event_time.astimezone(timezone.utc) - kick.astimezone(timezone.utc)).total_seconds()) <= 5400:
                matches.append(row)
        if len(matches) != 1:
            return {"status": "SOURCE_CONFLICT" if len(matches) > 1 else "UNAVAILABLE",
                    "reason": f"fixture_match_count={len(matches)}"}
        match = matches[0]
        fixture = match.get("fixture") or {}
        teams = match.get("teams") or {}
        fixture_id = fixture.get("id")
        home_id = (teams.get("home") or {}).get("id")
        away_id = (teams.get("away") or {}).get("id")
        recent = {}
        for side, team_id in (("home", home_id), ("away", away_id)):
            try:
                rows = self._request("/fixtures", {
                    "team": team_id, "last": 5, "timezone": "UTC",
                }).get("response", [])
                recent[side] = [_normalize_fixture(row) for row in rows[:5]]
            except Exception:
                recent[side] = []
        try:
            injuries = self._request("/injuries", {"fixture": fixture_id}).get("response", [])
        except Exception:
            injuries = []
        try:
            lineups = self._request("/fixtures/lineups", {"fixture": fixture_id}).get("response", [])
        except Exception:
            lineups = []
        return {
            "status": "ok", "fixture_id": fixture_id,
            "team_ids": {"home": home_id, "away": away_id},
            "recent": recent,
            "injuries": injuries,
            "injuries_status": "ok" if injuries else "UNAVAILABLE",
            "lineups": lineups,
            "lineups_status": "ok" if lineups else "UNAVAILABLE",
        }


def render_api_sports_evidence(payload, collected_at):
    status = (payload or {}).get("status", "UNAVAILABLE")
    lines = ["## API-Football 临场富集"]
    if status != "ok":
        lines.append(_fact("API-Sports 状态", f"{status}: {(payload or {}).get('reason', '')}",
                           f"{API_BASE}/fixtures", collected_at))
        return "\n".join(lines)
    lines.append(render_recent_form(payload.get("recent") or {}, collected_at))
    fid = payload.get("fixture_id")
    lines.append(_fact("伤停状态", payload.get("injuries_status", "UNAVAILABLE"),
                       f"{API_BASE}/injuries?fixture={fid}", collected_at))
    lines.append(_fact("首发状态", payload.get("lineups_status", "UNAVAILABLE"),
                       f"{API_BASE}/fixtures/lineups?fixture={fid}", collected_at))
    if payload.get("injuries"):
        for row in payload["injuries"]:
            player = (row.get("player") or {}).get("name")
            reason = (row.get("player") or {}).get("reason")
            team = (row.get("team") or {}).get("name")
            lines.append(_fact("伤停", f"{team} | {player} | {reason}",
                               f"{API_BASE}/injuries?fixture={fid}", collected_at))
    if payload.get("lineups"):
        for row in payload["lineups"]:
            team = (row.get("team") or {}).get("name")
            starters = [p.get("player", {}).get("name") for p in row.get("startXI") or []]
            lines.append(_fact("首发", f"{team} | {', '.join(x for x in starters if x)}",
                               f"{API_BASE}/fixtures/lineups?fixture={fid}", collected_at))
    return "\n".join(lines)

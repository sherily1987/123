"""Auditable LLM evidence enrichment for Sporttery and API-Football v3."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


API_BASE = "https://v3.football.api-sports.io"


def _dt(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # Sporttery's mobile feed sometimes emits ``YYYY/M/D H:MM:SS``.
            normalized = text.replace("/", "-")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                parsed = None
                for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M%z",
                            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                    try:
                        parsed = datetime.strptime(normalized, fmt)
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    raise
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


def render_recent_form(payload, collected_at, meta=None):
    source = f"{API_BASE}/fixtures"
    lines = ["## API-Football 最近5场"]
    for side, label in (("home", "主队近况"), ("away", "客队近况")):
        rows = list((payload or {}).get(side) or [])[:5]
        friendly_excluded = int(((meta or {}).get(side) or {}).get("friendly_excluded") or 0)
        if friendly_excluded:
            lines.append(_fact(f"{label}口径", f"正式比赛优先；排除友谊赛{friendly_excluded}场",
                               source, collected_at))
        if not rows:
            lines.append(_fact(label, "UNAVAILABLE", source, collected_at))
            continue
        for row in rows:
            value = (f"{row.get('date')} | {row.get('league')} | {row.get('home')} "
                     f"{row.get('score_90')} {row.get('away')} | status={row.get('status')}")
            lines.append(_fact(label, value, source, collected_at))
    return "\n".join(lines)


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


def _is_friendly_fixture(row):
    league = row.get("league") or {}
    text = " ".join(str(league.get(key) or "") for key in ("name", "type")).casefold()
    return "friendly" in text or "friendlies" in text or "友谊" in text


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
        "is_friendly": _is_friendly_fixture(row),
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

    @staticmethod
    def _dedupe_injuries(rows):
        unique, seen = [], set()
        for row in rows or []:
            player = row.get("player") or {}
            team = row.get("team") or {}
            key = (team.get("id"), player.get("id") or player.get("name"),
                   player.get("type"), player.get("reason"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    def collect_match(self, home, away, kickoff, *, aliases=None):
        kick = _dt(kickoff)
        aliases = aliases or {}
        home_values = list(home) if isinstance(home, (list, tuple, set)) else [home]
        away_values = list(away) if isinstance(away, (list, tuple, set)) else [away]
        home_values += [alias for value in home_values for alias in (aliases.get(str(value)) or [])]
        away_values += [alias for value in away_values for alias in (aliases.get(str(value)) or [])]
        home_names, away_names = _normal_names(home_values), _normal_names(away_values)
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
        recent, recent_meta = {}, {}
        for side, team_id in (("home", home_id), ("away", away_id)):
            try:
                rows = self._request("/fixtures", {
                    "team": team_id, "last": 20, "timezone": "UTC",
                }).get("response", [])
                normalized = [_normalize_fixture(row) for row in rows]
                recent[side] = [row for row in normalized if not row["is_friendly"]][:5]
                recent_meta[side] = {
                    "friendly_excluded": sum(1 for row in normalized if row["is_friendly"]),
                }
            except Exception:
                recent[side] = []
                recent_meta[side] = {"friendly_excluded": 0}
        try:
            injuries = self._request("/injuries", {"fixture": fixture_id}).get("response", [])
        except Exception:
            injuries = []
        injuries = self._dedupe_injuries(injuries)
        try:
            lineups = self._request("/fixtures/lineups", {"fixture": fixture_id}).get("response", [])
        except Exception:
            lineups = []
        # API-Sports can return one team only (or a team row with an empty
        # startXI) while the fixture is still being populated.  Treat that as
        # partial evidence rather than upgrading it to a complete lineup.
        lineup_sides_with_xi = sum(
            1 for row in lineups
            if isinstance(row, dict) and len(row.get("startXI") or []) > 0
        )
        if not lineups:
            lineups_status = "UNAVAILABLE"
        elif lineup_sides_with_xi < 2:
            lineups_status = "PARTIAL"
        else:
            lineups_status = "ok"
        return {
            "status": "ok", "fixture_id": fixture_id,
            "team_ids": {"home": home_id, "away": away_id},
            "recent": recent,
            "recent_meta": recent_meta,
            "injuries": injuries,
            "injuries_status": "ok" if injuries else "UNAVAILABLE",
            "lineups": lineups,
            "lineups_status": lineups_status,
        }


def render_api_sports_evidence(payload, collected_at):
    status = (payload or {}).get("status", "UNAVAILABLE")
    lines = ["## API-Football 临场富集"]
    if status != "ok":
        lines.append(_fact("API-Sports 状态", f"{status}: {(payload or {}).get('reason', '')}",
                           f"{API_BASE}/fixtures", collected_at))
        return "\n".join(lines)
    lines.append(render_recent_form(payload.get("recent") or {}, collected_at,
                                    payload.get("recent_meta") or {}))
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

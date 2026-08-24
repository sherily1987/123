#!/usr/bin/env python3
"""Backfill missing Big-5 post-match shot statistics from API-Sports.

The original event identity is preserved; the API-Sports fixture id is stored
as provenance. No values are imputed when the provider has no usable split.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
from difflib import SequenceMatcher
from pathlib import Path

API = "https://v3.football.api-sports.io"
PROXY = urllib.request.ProxyHandler({"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"})
OPENER = urllib.request.build_opener(PROXY)
ALIASES = {
    "wolverhamptonwanderers": "wolves", "westhamunited": "westham",
    "brightonhovealbion": "brighton", "tottenhamhotspur": "tottenham",
    "leicestercity": "leicester", "nottinghamforest": "nottinghamforest",
    "manchesterunited": "manchesterunited", "manchestercity": "manchestercity",
    "parissaintgermain": "psg", "saintetienne": "stetienne",
}
LEAGUES = {
    "premier_league": (39, "英超"),
    "bundesliga": (78, "德甲"),
    "ligue_1": (61, "法甲"),
    "serie_a": (135, "意甲"),
    "la_liga": (140, "西甲"),
    "finland_veikkausliiga": (244, "芬超"),
    "slovakia_1_liga": (332, "斯洛伐克甲"),
    "greece_super_league_1": (197, "希腊超"),
    "cyprus_1_division": (318, "塞浦路斯甲"),
    "bulgaria_first_league": (172, "保加利亚甲"),
    "serbia_super_liga": (286, "塞尔维亚甲"),
    "ukraine_premier_league": (333, "乌超"),
}


def key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    for suffix in ("footballclub", "fc"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return ALIASES.get(s, s)


def api(path: str, params: dict) -> list[dict]:
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": os.environ["API_FOOTBALL_KEY"]})
    last = None
    for attempt in range(4):
        try:
            with OPENER.open(req, timeout=60) as response:
                payload = json.loads(response.read().decode())
            return payload.get("response") or []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise last  # pragma: no cover


def stats_row(event: dict, fixture: dict, blocks: list[dict]) -> dict | None:
    by_team = {}
    for block in blocks:
        by_team[block["team"]["id"]] = {
            str(x.get("type")): x.get("value") for x in block.get("statistics") or []
        }
    h_id, a_id = fixture["teams"]["home"]["id"], fixture["teams"]["away"]["id"]
    h, a = by_team.get(h_id, {}), by_team.get(a_id, {})
    aliases = {"Total Shots": "shots_total", "Shots on Goal": "shots_on_goal",
               "Shots insidebox": "shots_inside_box", "Shots outsidebox": "shots_outside_box",
               "Shots off Goal": "shots_off_goal", "Blocked Shots": "shots_blocked",
               "Corner Kicks": "corners", "Ball Possession": "possession_pct"}
    def num(v):
        try:
            return float(str(v).rstrip("%")) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    out = {"provider": "api-sports.io", "source_type": "match_statistics",
           "match_id": event["match_id"], "source_api_fixture_id": fixture["fixture"]["id"],
           "league_id": event.get("league_id"), "kickoff": event["kickoff"],
           "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "data_class": "POST_MATCH"}
    for raw, dst in aliases.items():
        out[dst] = [num(h.get(raw)), num(a.get(raw))]
    inside, outside, total, on = (out["shots_inside_box"], out["shots_outside_box"],
                                  out["shots_total"], out["shots_on_goal"])
    out["split_available"] = all(v is not None for v in inside + outside)
    out["consistent"] = out["split_available"] and all(abs(i + o - t) < 1e-6 for i, o, t in zip(inside, outside, total))
    out["xg_usable"] = out["split_available"] and out["consistent"]
    return out if out["xg_usable"] else None


def match_event(event: dict, candidates: list[dict]) -> tuple[dict | None, float]:
    best, score = None, 0.0
    for fixture in candidates:
        h = fixture["teams"]["home"]["name"]; a = fixture["teams"]["away"]["name"]
        s = (SequenceMatcher(None, key(event["home"]), key(h)).ratio() +
             SequenceMatcher(None, key(event["away"]), key(a)).ratio()) / 2
        if s > score:
            best, score = fixture, s
    return best, score


def run(project: Path, slugs: list[str]) -> dict:
    norm = project / "04_素材" / "标准化"
    summary = {}
    for slug in slugs:
        league_id, display = LEAGUES[slug]
        events = [json.loads(x) for x in (norm / f"{slug}_events_provider_market.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        stats_path = norm / f"{slug}_match_stats.jsonl"
        stats = [json.loads(x) for x in stats_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        existing = {r["match_id"] for r in stats}
        missing = [e for e in events if e["match_id"] not in existing]
        fixtures = []
        for season in range(2021, 2026):
            fixtures.extend(api("/fixtures", {"league": league_id, "season": season, "timezone": "Asia/Shanghai"}))
        by_date = {}
        for f in fixtures:
            if (f.get("fixture", {}).get("status", {}).get("short")) not in {"FT", "AET", "PEN"}:
                continue
            d = (f.get("fixture", {}).get("date") or "")[:10]
            by_date.setdefault(d, []).append(f)
        added, unmatched, unusable = [], [], 0
        for event in missing:
            candidates = by_date.get(event["kickoff"][:10], [])
            fixture, score = match_event(event, candidates)
            if fixture is None or score < 0.70:
                unmatched.append(event["match_id"])
                continue
            blocks = api("/fixtures/statistics", {"fixture": fixture["fixture"]["id"]})
            row = stats_row(event, fixture, blocks)
            if row is None:
                unusable += 1
                continue
            added.append(row)
        merged = {r["match_id"]: r for r in stats}
        merged.update({r["match_id"]: r for r in added})
        stats_path.write_text("".join(json.dumps(merged[k], ensure_ascii=False) + "\n" for k in sorted(merged)), encoding="utf-8")
        summary[slug] = {"league": display, "before": len(stats), "missing_before": len(missing),
                         "added": len(added), "unmatched": len(unmatched), "provider_unusable": unusable,
                         "after": len(merged)}
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--slugs", nargs="*", default=list(LEAGUES))
    args = ap.parse_args()
    print(json.dumps(run(args.project, args.slugs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

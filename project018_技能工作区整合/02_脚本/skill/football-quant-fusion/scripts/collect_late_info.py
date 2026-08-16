#!/usr/bin/env python3
"""盘后伤停 + T-75 首发采集。只写研究库，不改生产 input / 不登记。

伤停：体彩 getInjurySuspensionV1（有 sporttery match_id 即可）。
首发：apifootball get_lineups，且必须已有 apifootball_match_id，不开球前 75 分钟内不拉。
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

CST = timezone(timedelta(hours=8))
T75_MINUTES = 75
CAP = {
    "Forward": (0.10, 0.00),
    "Midfielder": (0.06, 0.03),
    "Defender": (0.01, 0.09),
    "Goalkeeper": (0.00, 0.00),
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
    if kickoff is None:
        return None
    at = at or now_utc()
    return (kickoff - at).total_seconds() / 60.0


def in_t75_window(kickoff, at=None, window=T75_MINUTES) -> bool:
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
        "status": "VALID" if lst else "UNAVAILABLE",
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


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_injury(mid: int) -> dict | None:
    return preview.fetch(f"getInjurySuspensionV1.qry?sportteryMatchId={mid}")


def fetch_lineup(api_mid) -> dict | None:
    key = (os.environ.get("API_FOOTBALL_KEY") or os.environ.get("MCP_APIFOOTBALL_API_KEY") or "").strip()
    if not key or not api_mid:
        return None
    import urllib.parse
    import urllib.request
    qs = urllib.parse.urlencode({"action": "get_lineups", "APIkey": key, "match_id": str(api_mid)})
    url = "https://apiv3.apifootball.com/?" + qs
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if isinstance(data, dict) and data.get("error") is not None:
        return None
    obj = data.get(str(api_mid)) if isinstance(data, dict) else None
    if obj is None and isinstance(data, dict):
        obj = data.get(api_mid) or data
    lineup = (obj or {}).get("lineup") if isinstance(obj, dict) else {}
    if not isinstance(lineup, dict):
        return None
    out = {}
    for side in ("home", "away"):
        block = lineup.get(side) or {}
        starters = block.get("starting_lineups") or []
        missing = block.get("missing_players") or []
        out[side] = {
            "starting_count": len(starters),
            "missing_count": len(missing),
            "starting": [p.get("player") or p.get("lineup_player") for p in starters if isinstance(p, dict)],
            "missing": [p.get("player") or p.get("lineup_player") for p in missing if isinstance(p, dict)],
        }
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
            "in_t75": in_t75_window(kickoff, collected_at),
        },
    }


def collect_one(rec, snapshot, want_injury, want_lineup, events_path):
    collected_at = now_utc()
    kickoff = kickoff_of(rec)
    odds_at = odds_at_of(rec)
    mid = match_id_of(rec)
    out = []
    if want_injury and mid:
        raw = fetch_injury(mid)
        row = base_row(rec, "injury", snapshot, collected_at, odds_at, kickoff)
        if raw is None:
            row["status"] = "UNAVAILABLE"
        else:
            folded = fold_injuries(raw)
            row["status"] = "VALID" if (folded["home"]["count"] or folded["away"]["count"]) else "UNAVAILABLE"
            row["absence"] = folded
        append_jsonl(events_path, row)
        out.append(row)
    if want_lineup:
        row = base_row(rec, "lineup", snapshot, collected_at, odds_at, kickoff)
        if kickoff and collected_at >= kickoff:
            row["status"] = "POST_KICKOFF"
        elif not in_t75_window(kickoff, collected_at):
            row["status"] = "TOO_EARLY"
        else:
            api_mid = api_match_id_of(rec)
            if not api_mid:
                row["status"] = "NO_API_ID"
            else:
                lineup = fetch_lineup(api_mid)
                if lineup is None:
                    row["status"] = "UNAVAILABLE"
                else:
                    row["status"] = "VALID"
                    row["lineup"] = lineup
                    row["apifootball_match_id"] = api_mid
        if row["status"] != "TOO_EARLY":
            append_jsonl(events_path, row)
            out.append(row)
    return out


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
            "t75_at": (kickoff - timedelta(minutes=T75_MINUTES)).isoformat(),
            "odds_at": odds_at_of(rec).isoformat() if odds_at_of(rec) else None,
            "apifootball_match_id": api_match_id_of(rec),
            "snapshot": snapshot,
            "research_only": True,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "late-info-due-1.0",
        "research_only": True,
        "t75_minutes": T75_MINUTES,
        "matches": due,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return due


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-collect", type=Path, required=True)
    ap.add_argument("--snapshot", default="T-7h")
    ap.add_argument("--work-dir", type=Path)
    ap.add_argument("--events", type=Path)
    ap.add_argument("--watch", action="store_true", help="等到 T-75 再采首发/伤停；每日流水线不要带这个")
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    src = args.from_collect.resolve()
    matches = load_matches(src)
    work = (args.work_dir or src.parent).resolve()
    events_path = (args.events or late_info_store() / "events.jsonl").resolve()
    due_path = work / "late_info_due.json"
    due = write_due(due_path, matches, args.snapshot)

    collected = []
    for rec in matches:
        collected.extend(collect_one(
            rec, args.snapshot, want_injury=True,
            want_lineup=in_t75_window(kickoff_of(rec)),
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
                if in_t75_window(kickoff):
                    collected.extend(collect_one(
                        rec, "T-75", want_injury=True, want_lineup=True, events_path=events_path))
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
        "lineup_valid": sum(1 for r in collected if r.get("kind") == "lineup" and r.get("status") == "VALID"),
        "lineup_no_api_id": sum(1 for r in collected if r.get("status") == "NO_API_ID"),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

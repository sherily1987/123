"""Build explicit provider-only market inputs without Sporttery semantics."""
from __future__ import annotations

def build_input(event, odds_rows, mode="apifootball_primary"):
    if mode != "apifootball_primary":
        raise ValueError("only apifootball_primary is supported by this builder")
    if any(r.get("source_type") == "PROVIDER_BENCHMARK" for r in odds_rows):
        raise ValueError("PROVIDER_BENCHMARK cannot be used as market input")
    row=next((r for r in odds_rows if r.get("match_id") == event.get("match_id") and r.get("source_type") == "bookmaker_odds"),None)
    if not row or len(row.get("odds_1x2") or []) != 3 or any(x is None or x <= 1 for x in row["odds_1x2"]):
        raise ValueError("INVALID bookmaker 1X2 odds")
    return {"match_id":event.get("match_id"),"home":event.get("home"),"away":event.get("away"),"odds":row["odds_1x2"],"odds_source":"apifootball.com","bookmaker":row.get("bookmaker"),"observed_at":row.get("observed_at"),"source_mode":"apifootball_primary","provider_only":True}

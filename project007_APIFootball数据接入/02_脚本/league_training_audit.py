#!/usr/bin/env python3
"""Classify normalized leagues for independent training without leakage."""
from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path

POST_MATCH = {"statistics", "lineup", "player_statistics", "goalscorer", "cards", "substitutions"}

def validate_prematch_record(record):
    bad = sorted(k for k in POST_MATCH if k in record)
    if bad: raise ValueError("POST_MATCH fields: " + ", ".join(bad))

def classify(rows, kind):
    if kind != "domestic_league": return {"tier":"excluded","reasons":["competition_not_domestic_league"]}
    ordered=sorted(rows,key=lambda r:r.get("kickoff", "")); n=len(ordered); seasons={r.get("season") for r in ordered if r.get("season")}; ids=[x for r in ordered for x in (r.get("home_id"),r.get("away_id"))]; coverage=sum(x is not None for x in ids)/len(ids) if ids else 0; teams={x for x in ids if x is not None}; test_n=n-int(n*.8)
    reasons=[]
    if n<900: reasons.append("completed_n_lt_900")
    if len(seasons)<3: reasons.append("season_count_lt_3")
    if test_n<150: reasons.append("test_n_lt_150")
    if coverage<.95: reasons.append("team_id_coverage_lt_95pct")
    if len(teams)<12: reasons.append("team_count_lt_12")
    tier="independent" if not reasons else ("calibration" if n>=300 else "pooled")
    return {"tier":tier,"reasons":reasons,"completed_n":n,"season_count":len(seasons),"team_id_coverage":round(coverage,4),"team_count":len(teams),"train_n":int(n*.6),"validation_n":int(n*.8)-int(n*.6),"test_n":test_n}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True); ap.add_argument("--scope",required=True); ap.add_argument("--output",required=True); a=ap.parse_args()
    scope=json.loads(Path(a.scope).read_text(encoding="utf-8")); groups=defaultdict(list)
    for line in Path(a.input).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r=json.loads(line); validate_prematch_record(r); groups[str(r.get("league_id"))].append(r)
    out={"schema_version":"league-training-audit-1.0","leagues":{k:classify(v,(scope.get(k) or {}).get("kind","excluded")) for k,v in groups.items()}}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(out,ensure_ascii=False))
if __name__=="__main__": main()

#!/usr/bin/env python3
"""Convert API-Sports event-result backfills into the training standard schema.

Only rows explicitly marked Finished with a score are emitted.  No odds are
invented; the provider-market filename is retained only for compatibility with
the existing no-market backtest discovery path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def normalize(input_path: Path, output_dir: Path, slug: str, league_id: int, league_name: str) -> dict:
    rows = []
    excluded = 0
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if raw.get("status") != "Finished" or not raw.get("actual"):
            excluded += 1
            continue
        row = dict(raw)
        row.update({
            "league_id": league_id,
            "league_name": league_name,
            "settlement_basis": "90min_fulltime_score",
            "raw_status": "Finished",
        })
        rows.append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    for name in (f"{slug}_events.jsonl", f"{slug}_events_provider_market.jsonl"):
        (output_dir / name).write_text(payload, encoding="utf-8")
    return {"slug": slug, "rows": len(rows), "excluded": excluded}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--league-id", type=int, required=True)
    ap.add_argument("--league-name", required=True)
    args = ap.parse_args()
    print(json.dumps(normalize(args.input, args.output_dir, args.slug,
                               args.league_id, args.league_name), ensure_ascii=False))


if __name__ == "__main__":
    main()

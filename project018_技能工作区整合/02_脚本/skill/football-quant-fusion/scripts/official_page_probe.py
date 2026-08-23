#!/usr/bin/env python3
"""Fetch a discovered official match page as timestamped research evidence.

The probe verifies identity and schedule text only.  It deliberately treats a
generic ``Lineups`` section as pending: a page can expose the section before
the confirmed XI is published.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

# A small alias layer for common official English labels.  Unknown teams fall
# back to exact text matching and remain UNMATCHED instead of being guessed.
TEAM_ALIASES = {
    "奥萨苏纳": ("奥萨苏纳", "CA Osasuna", "Osasuna"),
    "莱万特": ("莱万特", "Levante UD", "Levante"),
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _labels(team: str) -> tuple[str, ...]:
    return TEAM_ALIASES.get(str(team), (str(team),))


def _date_variants(kickoff_date: str) -> tuple[str, ...]:
    raw = str(kickoff_date or "")[:10]
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not match:
        return (raw,)
    year, month, day = match.groups()
    return (raw, f"{day}.{month}.{year}", f"{day}/{month}/{year}")


def extract_facts(text: str, *, home: str, away: str, kickoff_date: str) -> dict[str, Any]:
    """Extract conservative identity, schedule and lineup publication facts."""
    body = _compact(text)
    identity = all(any(_compact(label) in body for label in _labels(team))
                   for team in (home, away))
    schedule = any(_compact(value) in body for value in _date_variants(kickoff_date))
    lower = body.lower()
    confirmed = any(marker in lower for marker in
                    ("confirmed lineups", "confirmed starting xi", "starting lineup confirmed",
                     "starting xi confirmed"))
    has_lineup_section = "lineup" in lower or "starting xi" in lower
    lineup_status = "CONFIRMED" if confirmed else "LINEUP_PENDING" if has_lineup_section else "UNAVAILABLE"
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()
    return {
        "identity_status": "MATCHED" if identity else "UNMATCHED",
        "schedule_status": "MATCHED" if schedule else "UNMATCHED",
        "lineup_status": lineup_status,
        "content_hash": f"sha256:{digest}",
    }


def _run_scrapling(url: str, output_path: Path, *, timeout_ms: int = 60000) -> None:
    proc = subprocess.run(
        ["scrapling", "extract", "fetch", url, str(output_path),
         "--ai-targeted", "--network-idle", "--timeout", str(timeout_ms)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=max(90, timeout_ms // 1000 + 30),
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "scrapling failed").strip()[-300:])


def probe_url(url: str, *, home: str, away: str, kickoff_date: str,
              timeout_ms: int = 60000) -> dict[str, Any]:
    captured_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        with tempfile.NamedTemporaryFile(prefix="official_probe_", suffix=".md", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            _run_scrapling(url, output_path, timeout_ms=timeout_ms)
            text = output_path.read_text(encoding="utf-8", errors="replace")
        finally:
            output_path.unlink(missing_ok=True)
        facts = extract_facts(text, home=home, away=away, kickoff_date=kickoff_date)
        return {"status": "ok", "source_url": url, "captured_at": captured_at, **facts}
    except Exception as exc:
        return {"status": "source_fetch_error", "source_url": url,
                "captured_at": captured_at, "reason": str(exc)[:300]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--kickoff-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe_url(args.url, home=args.home, away=args.away,
                       kickoff_date=args.kickoff_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(__import__("json").dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(__import__("json").dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())

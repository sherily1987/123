"""Add UEFA-verified third-qualifying-round context to Sporttery model input."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


UEFA_URL = (
    "https://www.uefa.com/uefachampionsleague/news/"
    "02a6-20e5a8be4e63-ae971c582f8c-1000--champions-league-qualifying-fixtures-dates-how-it-works/"
)
AS_OF = "2026-08-10T00:00:00+02:00"

# Scores are ordered as current match home team's first-leg goals, then away team's.
CONTEXT = {
    "周二002": ("阿拉木图凯拉特", "索菲亚列夫斯基", [0, 1]),
    "周二003": ("博德闪耀", "圣吉罗斯联合", [3, 3]),
    "周二004": ("萨巴赫", "奥胡斯", [1, 2]),
    "周二005": ("奈梅亨", "奥林匹亚科斯", [0, 0]),
    "周二006": ("采列", "阿拉拉特亚美尼亚", [1, 2]),
    "周二007": ("布拉迪斯拉发斯洛万", "米亚尔比", [2, 1]),
    "周二008": ("格拉茨风暴", "费内巴切", [0, 2]),
    "周二009": ("里昂", "布拉格斯巴达", [1, 2]),
}


def enrich(document: dict) -> dict:
    result = deepcopy(document)
    for match in result.get("matches", []):
        context = CONTEXT.get(match.get("sporttery_meta", {}).get("match_num"))
        if not context:
            continue
        home, away, first_leg = context
        # A verified aggregate score is match context, not a calibrated team-strength prior.
        # Keep market_only until paired Elo/lambda evidence is available.
        match.update(home=home, away=away, mode="market_only", first_leg=first_leg, auto_motive=True)
        meta = match.setdefault("field_meta", {})
        meta["first_leg"] = {
            "reliability": 100,
            "freshness": 100,
            "source": "UEFA Champions League qualifying fixtures and results",
            "source_url": UEFA_URL,
            "observed_at": AS_OF,
            "status": "VALID",
        }
        match.setdefault("assumptions", []).append(
            "UEFA official first-leg score verified; automatic second-leg motive adjustment enabled. "
            "No calibrated independent strength prior is available, so 1X2 remains market_only."
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    Path(args.output).write_text(json.dumps(enrich(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

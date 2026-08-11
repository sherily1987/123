from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path


MODULE = Path(__file__).with_name("train_five_leagues.py")
SPEC = importlib.util.spec_from_file_location("five_training", MODULE)
training = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(training)


def test_time_cutoffs_keep_same_kickoff_day_together():
    rows = []
    for day, count in (("2021-08-01", 4), ("2021-08-02", 3), ("2021-08-03", 3), ("2021-08-04", 3)):
        rows.extend({"kickoff": f"{day}T20:00:00"} for _ in range(count))

    first, second = training.time_cutoffs(rows)

    assert first == datetime.fromisoformat("2021-08-03").date().toordinal()
    assert second == datetime.fromisoformat("2021-08-04").date().toordinal()

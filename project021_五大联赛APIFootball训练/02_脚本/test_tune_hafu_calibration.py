from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).with_name("tune_hafu_calibration.py")
SPEC = importlib.util.spec_from_file_location("tune_hafu_calibration", MODULE)
tune = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(tune)


def test_hafu_label_and_temperature_metrics_are_properly_normalized():
    assert tune.hafu_label(1, 0, 2, 0) == "HH"
    assert tune.hafu_label(0, 1, 1, 1) == "AD"
    probs = tune.temperature_scale([0.5, 0.1, 0.05, 0.1, 0.1, 0.05, 0.04, 0.03, 0.03], 1.2)

    assert round(sum(probs), 12) == 1.0
    metrics = tune.metrics([{"actual_idx": 0, "raw_probs": probs}])
    assert metrics["n"] == 1
    assert metrics["accuracy_pct"] == 100.0
    assert metrics["log_loss"] > 0

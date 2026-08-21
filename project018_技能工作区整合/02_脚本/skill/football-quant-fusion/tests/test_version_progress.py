from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion")
SCRIPTS = SKILL_ROOT / "scripts"
CORE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3\scripts")
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(CORE))

import version_progress
import fusion_cli

CURRENT_SIG = "a" * 64
OTHER_SIG = "b" * 64


def build_store(root: Path, predictions, results):
    """写出一个最小可读的 backtest store。"""
    store = root / "backtest"
    (store / "predictions").mkdir(parents=True)
    registry = []
    for rec in predictions:
        # Windows 文件名不允许冒号，prediction_id 里的时间戳要落盘先转义
        safe = rec["prediction_id"].replace(":", "-")
        path = store / "predictions" / f"{safe}.json"
        path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        registry.append({"prediction_id": rec["prediction_id"], "match_id": rec["match_id"],
                         "created_at": rec["created_at"], "path": str(path)})
    (store / "registry.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in registry), encoding="utf-8")
    (store / "results_registry.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in results), encoding="utf-8")
    return store


def prediction(match_id, created_at, model_version, signature, snapshot="prematch"):
    return {
        "prediction_id": f"{match_id}__{created_at}__{snapshot}",
        "match_id": match_id,
        "snapshot_type": snapshot,
        "created_at": created_at,
        "model": {"model_version": model_version, "probability_signature": signature},
    }


class VersionProgressTests(unittest.TestCase):
    def _report(self, predictions, results, model_version="m2", signature=CURRENT_SIG,
                aliases=()):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp), predictions, results)
            with patch.object(version_progress, "build_identity", return_value={
                    "model_version": model_version, "probability_signature": signature}), \
                 patch.object(version_progress, "load_version_aliases",
                              return_value=list(aliases)):
                return version_progress.build_report(store)

    def test_separates_settled_from_pending_for_current_version(self):
        report = self._report(
            [prediction("m-1", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG),
             prediction("m-2", "2026-08-11T00:00:00Z", "m2", CURRENT_SIG),
             prediction("m-3", "2026-08-16T00:00:00Z", "m2", CURRENT_SIG)],
            [{"match_id": "m-1"}])
        current = report["current"]
        self.assertEqual(current["settled"], 1)
        self.assertEqual(current["pending"], 2)
        self.assertEqual(current["projected_after_pending"], 3)
        self.assertEqual(current["to_recalibration"], 99)
        self.assertEqual(current["to_threshold_review"], 199)
        self.assertFalse(current["ready_for_recalibration"])

    def test_cancelled_matches_are_excluded_from_both_counts(self):
        report = self._report(
            [prediction("m-1", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG),
             prediction("m-2", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG)],
            [{"match_id": "m-1"}, {"match_id": "m-2", "status": "cancelled"}])
        current = report["current"]
        self.assertEqual(current["settled"], 1)
        self.assertEqual(current["pending"], 0)
        self.assertEqual(report["by_model_version"]["m2"]["cancelled"], 1)

    def test_other_versions_do_not_leak_into_current_counts(self):
        report = self._report(
            [prediction("m-1", "2026-08-10T00:00:00Z", "m1", OTHER_SIG),
             prediction("m-2", "2026-08-10T00:00:00Z", None, "")],
            [{"match_id": "m-1"}, {"match_id": "m-2"}])
        self.assertEqual(report["current"]["settled"], 0)
        self.assertEqual(report["current"]["pending"], 0)
        self.assertEqual(report["by_model_version"]["m1"]["settled"], 1)
        self.assertEqual(report["by_model_version"]["unattributable"]["settled"], 1)

    def test_same_version_with_changed_signature_is_reported_as_drift(self):
        report = self._report(
            [prediction("m-1", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG),
             prediction("m-2", "2026-08-10T00:00:00Z", "m2", OTHER_SIG)],
            [{"match_id": "m-1"}, {"match_id": "m-2"}])
        self.assertEqual(len(report["signature_drift"]), 1)
        self.assertEqual(report["signature_drift"][0]["match_id"], "m-2")

    def test_only_one_snapshot_per_match_is_counted(self):
        report = self._report(
            [prediction("m-1", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG, snapshot="prematch"),
             prediction("m-1", "2026-08-10T06:00:00Z", "m2", CURRENT_SIG, snapshot="closing")],
            [{"match_id": "m-1"}])
        self.assertEqual(report["current"]["settled"], 1)

    def test_verified_alias_versions_count_toward_current(self):
        alias = {"model_version": "m1", "probability_signature": OTHER_SIG}
        predictions = [prediction("m-1", "2026-08-10T00:00:00Z", "m1", OTHER_SIG),
                       prediction("m-2", "2026-08-16T00:00:00Z", "m1", OTHER_SIG)]
        results = [{"match_id": "m-1"}]

        without = self._report(predictions, results)
        self.assertEqual((without["current"]["settled"], without["current"]["pending"]), (0, 0))

        with_alias = self._report(predictions, results, aliases=[alias])
        self.assertEqual((with_alias["current"]["settled"], with_alias["current"]["pending"]), (1, 1))
        self.assertEqual(with_alias["counted_as_current_aliases"], ["m1"])
        # 分版本明细仍按原始 model_version 展示，不把 m1 改写成 m2
        self.assertEqual(with_alias["by_model_version"]["m1"]["settled"], 1)

    def test_verified_same_version_alias_is_not_signature_drift(self):
        """重放确认数值等价的旧 m2 签名应计入 current，不能再告警为未 bump。"""
        alias = {"model_version": "m2", "probability_signature": OTHER_SIG}
        report = self._report(
            [prediction("m-current", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG),
             prediction("m-alias", "2026-08-11T00:00:00Z", "m2", OTHER_SIG)],
            [{"match_id": "m-current"}, {"match_id": "m-alias"}],
            aliases=[alias],
        )

        self.assertEqual(report["current"]["settled"], 2)
        self.assertEqual(report["signature_drift"], [])

    def test_cli_help_lists_version_progress(self):
        self.assertIn("version-progress", fusion_cli.HELP)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
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


def prediction(match_id, created_at, model_version, signature, snapshot="prematch",
               prediction_as_of=None, route="market_only"):
    row = {
        "prediction_id": f"{match_id}__{created_at}__{snapshot}",
        "match_id": match_id,
        "snapshot_type": snapshot,
        "created_at": created_at,
        "model": {"model_version": model_version, "probability_signature": signature},
        "input": {"mode": route},
    }
    if prediction_as_of is not None:
        row["prediction_as_of"] = prediction_as_of
    return row


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

    def test_unapproved_drift_is_grouped_by_complete_signature_and_registered_route(self):
        """An attestation candidate remains isolated until a later approval task loads an alias."""
        report = self._report(
            [prediction("m-current", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG),
             prediction("m-market", "2026-08-10T00:00:00Z", "m2", OTHER_SIG,
                        route="market_only"),
             prediction("m-hybrid", "2026-08-10T00:00:00Z", "m2", OTHER_SIG,
                        route="hybrid")],
            [{"match_id": "m-current"}, {"match_id": "m-market"}, {"match_id": "m-hybrid"}],
        )

        self.assertEqual(report["current"]["settled"], 1)
        self.assertEqual(report["raw_current_n"], 1)
        self.assertEqual(report["approved_alias_n"], 0)
        self.assertEqual(report["drift_groups"], report["signature_drift_groups"])
        self.assertEqual(report["unreplayable_groups"], [])
        self.assertEqual(report["changed_groups"], [])
        self.assertEqual(report["pending_review_groups"], [])
        self.assertEqual(report["signature_drift_groups"], [
            {"model_version": "m2", "probability_signature": OTHER_SIG,
             "route": "hybrid", "record_count": 1, "status": "UNREPLAYED"},
            {"model_version": "m2", "probability_signature": OTHER_SIG,
             "route": "market_only", "record_count": 1, "status": "UNREPLAYED"},
        ])

    def test_only_one_snapshot_per_match_is_counted(self):
        report = self._report(
            [prediction("m-1", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG, snapshot="prematch"),
             prediction("m-1", "2026-08-10T06:00:00Z", "m2", CURRENT_SIG, snapshot="closing")],
            [{"match_id": "m-1"}])
        self.assertEqual(report["current"]["settled"], 1)
        self.assertEqual(report["superseded_snapshot_count"], 1)
        self.assertEqual(report["reissued_current_snapshot_count"], 1)

    def test_current_version_uses_prediction_as_of_not_delayed_registry_write(self):
        """Delayed persistence must not hide the later deployed version."""
        report = self._report(
            [prediction("m-1", "2026-08-21T16:00:00Z", "m3", OTHER_SIG,
                        snapshot="prematch", prediction_as_of="2026-08-21T13:00:00Z"),
             prediction("m-1", "2026-08-21T15:00:00Z", "m4", CURRENT_SIG,
                        snapshot="T-7h", prediction_as_of="2026-08-21T14:00:00Z")],
            [], model_version="m4")
        self.assertEqual(report["current"]["pending"], 1)
        self.assertEqual(report["by_model_version"]["m4"]["pending"], 1)

    def test_verified_alias_versions_count_toward_current(self):
        alias = {"status": "EQUIVALENT_ALIAS", "model_version": "m1",
                 "probability_signature": OTHER_SIG, "route": "market_only",
                 "alias_to_model_version": "m2",
                 "alias_to_probability_signature": CURRENT_SIG}
        predictions = [prediction("m-1", "2026-08-10T00:00:00Z", "m1", OTHER_SIG),
                       prediction("m-2", "2026-08-16T00:00:00Z", "m1", OTHER_SIG)]
        results = [{"match_id": "m-1"}]

        without = self._report(predictions, results)
        self.assertEqual((without["current"]["settled"], without["current"]["pending"]), (0, 0))

        with_alias = self._report(predictions, results, aliases=[alias])
        self.assertEqual((with_alias["current"]["settled"], with_alias["current"]["pending"]), (1, 1))
        self.assertEqual(with_alias["counted_as_current_aliases"], ["m1"])
        self.assertEqual(with_alias["raw_current_n"], 0)
        self.assertEqual(with_alias["approved_alias_n"], 1)
        # 分版本明细仍按原始 model_version 展示，不把 m1 改写成 m2
        self.assertEqual(with_alias["by_model_version"]["m1"]["settled"], 1)

    def test_verified_same_version_alias_is_not_signature_drift(self):
        """重放确认数值等价的旧 m2 签名应计入 current，不能再告警为未 bump。"""
        alias = {"status": "EQUIVALENT_ALIAS", "model_version": "m2",
                 "probability_signature": OTHER_SIG, "route": "market_only",
                 "alias_to_model_version": "m2",
                 "alias_to_probability_signature": CURRENT_SIG}
        report = self._report(
            [prediction("m-current", "2026-08-10T00:00:00Z", "m2", CURRENT_SIG),
             prediction("m-alias", "2026-08-11T00:00:00Z", "m2", OTHER_SIG)],
            [{"match_id": "m-current"}, {"match_id": "m-alias"}],
            aliases=[alias],
        )

        self.assertEqual(report["current"]["settled"], 2)
        self.assertEqual(report["signature_drift"], [])

    def test_numeric_signature_cannot_be_coerced_into_an_approved_alias(self):
        numeric_signature = int("1" * 64)
        alias = {"status": "EQUIVALENT_ALIAS", "model_version": "m2",
                 "probability_signature": "1" * 64, "route": "market_only",
                 "alias_to_model_version": "m2",
                 "alias_to_probability_signature": CURRENT_SIG}
        report = self._report(
            [prediction("m-corrupt", "2026-08-10T00:00:00Z", "m2", numeric_signature)],
            [{"match_id": "m-corrupt"}], aliases=[alias],
        )

        self.assertEqual(report["current"]["settled"], 0)
        self.assertEqual(report["approved_alias_n"], 0)

    def test_numeric_registered_route_cannot_be_coerced_into_an_approved_alias(self):
        alias = {"status": "EQUIVALENT_ALIAS", "model_version": "m2",
                 "probability_signature": OTHER_SIG, "route": "1",
                 "alias_to_model_version": "m2",
                 "alias_to_probability_signature": CURRENT_SIG}
        report = self._report(
            [prediction("m-corrupt", "2026-08-10T00:00:00Z", "m2", OTHER_SIG,
                        route=1)],
            [{"match_id": "m-corrupt"}], aliases=[alias],
        )

        self.assertEqual(report["current"]["settled"], 0)
        self.assertEqual(report["approved_alias_n"], 0)

    def test_alias_targeting_an_older_version_does_not_count_for_new_version(self):
        alias = {"status": "EQUIVALENT_ALIAS", "model_version": "m1",
                 "probability_signature": OTHER_SIG, "route": "market_only",
                 "alias_to_model_version": "m2",
                 "alias_to_probability_signature": CURRENT_SIG}
        report = self._report(
            [prediction("m-old", "2026-08-10T00:00:00Z", "m1", OTHER_SIG)],
            [{"match_id": "m-old"}], model_version="m4", aliases=[alias],
        )
        self.assertEqual(report["current"]["settled"], 0)
        self.assertEqual(report["counted_as_current_aliases"], [])

    def test_grouped_attestation_states_are_split_without_admitting_them(self):
        predictions = [
            prediction("m-pending", "2026-08-10T00:00:00Z", "m2", OTHER_SIG,
                       route="market_only"),
            prediction("m-changed", "2026-08-11T00:00:00Z", "m2", "c" * 64,
                       route="hybrid"),
            prediction("m-unreplayable", "2026-08-12T00:00:00Z", "m2", "d" * 64,
                       route="model_first"),
        ]
        states = {
            ("m2", OTHER_SIG, "market_only"): "PENDING_REVIEW",
            ("m2", "c" * 64, "hybrid"): "CHANGED_REQUIRES_VERSION_BUMP",
            ("m2", "d" * 64, "model_first"): "UNREPLAYABLE",
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp), predictions, [])
            with patch.object(version_progress, "build_identity", return_value={
                    "model_version": "m2", "probability_signature": CURRENT_SIG}), \
                 patch.object(version_progress, "load_version_aliases", return_value=[]), \
                 patch.object(version_progress, "load_drift_group_statuses", return_value=states):
                report = version_progress.build_report(store)

        self.assertEqual(report["current"]["settled"], 0)
        self.assertEqual([group["status"] for group in report["pending_review_groups"]],
                         ["PENDING_REVIEW"])
        self.assertEqual([group["status"] for group in report["changed_groups"]],
                         ["CHANGED_REQUIRES_VERSION_BUMP"])
        self.assertEqual([group["status"] for group in report["unreplayable_groups"]],
                         ["UNREPLAYABLE"])

    def test_cli_help_lists_version_progress(self):
        self.assertIn("version-progress", fusion_cli.HELP)

    def test_audits_current_rows_missing_from_main_to_backtest_handoff(self):
        """主登记库的当前版本记录只提示差异，不改变回测分母。"""
        with tempfile.TemporaryDirectory() as tmp:
            backtest = build_store(
                Path(tmp) / "backtest-root",
                [prediction("m-current", "2026-08-20T00:00:00Z", "m2", CURRENT_SIG)],
                [],
            )
            main = build_store(
                Path(tmp) / "main-root",
                [prediction("m-current", "2026-08-20T00:00:00Z", "m2", CURRENT_SIG),
                 prediction("m-main-only", "2026-08-21T00:00:00Z", "m2", CURRENT_SIG)],
                [],
            )
            with patch.object(version_progress, "build_identity", return_value={
                    "model_version": "m2", "probability_signature": CURRENT_SIG}), \
                 patch.object(version_progress, "load_version_aliases", return_value=[]), \
                 patch.object(version_progress, "data_root", return_value=main):
                report = version_progress.build_report(backtest)

        audit = report["main_registry_audit"]
        self.assertEqual(audit["current_rows"], 2)
        self.assertEqual(audit["current_not_in_backtest"], 1)
        self.assertEqual(report["current"]["pending"], 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import json
import hashlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SKILL_ROOT = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion")
SCRIPTS = SKILL_ROOT / "scripts"
CORE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3\scripts")
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(CORE))

import fusion_predict_core as fusion
import fusion_backtest as backtest
import market_fit
import sales_day_collect
import fusion_cli


class BuildIdentityTests(unittest.TestCase):
    def test_prediction_contains_stable_code_and_config_hashes(self):
        identity = fusion.build_identity()
        manifest = json.loads((SKILL_ROOT / "config" / "version_manifest.json").read_text(encoding="utf-8-sig"))
        for key in ("engine_bundle_sha256", "prediction_code_sha256", "config_sha256",
                    "probability_signature", "decision_policy_signature",
                    "evidence_pipeline_signature"):
            self.assertRegex(identity[key], r"^[0-9a-f]{64}$")
        self.assertEqual(identity["fusion_schema_version"], manifest["fusion_schema_version"])
        self.assertEqual(manifest["record_schema_version"], "fusion-1.1")
        self.assertEqual(manifest["backtest_schema_version"], "fusion-backtest-2.0")
        self.assertEqual(manifest["sample_audit_schema_version"], "sample-audit-2.0")
        self.assertEqual(manifest["model_version"], "m4")
        self.assertIn("scripts/production_router.py", manifest["probability_files"])
        self.assertNotIn("config/recommendation_policy.json", manifest["probability_files"])
        self.assertIn("config/recommendation_policy.json", manifest["decision_policy_files"])

        core, version = fusion.load_core()
        result = fusion.predict_one(core, version, {
            "home": "Home",
            "away": "Away",
            "stage": "Test",
            "kickoff": "2026-08-10T20:00:00+08:00",
            "mode": "market_only",
            "odds": [2.5, 3.2, 2.8],
            "field_meta": {
                "odds": {
                    "freshness": 100,
                    "collected_at": "2026-08-08T00:00:00+08:00",
                    "source_updated_at": "2026-08-07T23:59:00+08:00",
                }
            },
            "prediction_as_of": "2026-08-08T00:00:00+08:00",
        })
        self.assertEqual(result["fusion_status"], "ok")
        self.assertEqual(result["build_identity"], identity)
        self.assertEqual(result["version_manifest"]["fusion_version"], identity["fusion_version"])
        self.assertEqual(result["version_manifest"]["core_version"], identity["core_version"])

    def test_registration_preserves_build_identity(self):
        identity = fusion.build_identity()
        with tempfile.TemporaryDirectory(prefix="fusion-p0-record-") as td:
            root = Path(td)
            input_path = root / "input.json"
            output_path = root / "output.json"
            store = root / "store"
            input_path.write_text(json.dumps({
                "home": "Home", "away": "Away", "stage": "Test",
                "kickoff": "2099-08-10T20:00:00+08:00",
                "prediction_as_of": "2099-08-09T20:00:00+08:00",
                "sporttery_meta": {"match_id": "p0-test"},
            }), encoding="utf-8")
            output_path.write_text(json.dumps({
                "fusion_status": "ok",
                "core_engine_version": identity["core_version"],
                "build_identity": identity,
                "core_output": {"engine_version": identity["core_version"]},
            }), encoding="utf-8")
            proc = subprocess.run([
                sys.executable, str(SCRIPTS / "fusion_record.py"),
                "--input", str(input_path), "--output", str(output_path),
                "--store", str(store), "--snapshot", "prematch",
            ], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            registry = [json.loads(line) for line in (store / "registry.jsonl").read_text(encoding="utf-8").splitlines()]
            record = json.loads(Path(registry[0]["path"]).read_text(encoding="utf-8"))
            model = record["model"]
            self.assertEqual(model["engine_bundle_sha256"], identity["engine_bundle_sha256"])
            self.assertEqual(model["prediction_code_sha256"], identity["prediction_code_sha256"])
            self.assertEqual(model["config_sha256"], identity["config_sha256"])
            self.assertEqual(model["fusion_version"], identity["fusion_version"])
            self.assertEqual(model["core_version"], identity["core_version"])

    def test_formal_registration_rejects_research_only_output(self):
        identity = fusion.build_identity()
        with tempfile.TemporaryDirectory(prefix="fusion-research-record-") as td:
            root = Path(td)
            input_path, output_path, store = root / "input.json", root / "output.json", root / "store"
            input_path.write_text(json.dumps({
                "home": "Home", "away": "Away", "stage": "Test",
                "kickoff": "2099-08-10T20:00:00+08:00",
                "prediction_as_of": "2099-08-09T20:00:00+08:00",
                "sporttery_meta": {"match_id": "research-test"},
            }), encoding="utf-8")
            output_path.write_text(json.dumps({
                "fusion_status": "ok", "research_only": True,
                "build_identity": identity, "core_engine_version": identity["core_version"],
                "core_output": {"engine_version": identity["core_version"]},
            }), encoding="utf-8")
            proc = subprocess.run([
                sys.executable, str(SCRIPTS / "fusion_record.py"),
                "--input", str(input_path), "--output", str(output_path),
                "--store", str(store), "--snapshot", "prematch",
            ], text=True, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("research_only", proc.stderr or proc.stdout)

    def test_prematch_registration_freezes_time_route_mode_hashes_and_raw_payload_hashes(self):
        identity = fusion.build_identity()
        with tempfile.TemporaryDirectory(prefix="fusion-freeze-record-") as td:
            root = Path(td)
            inp = {
                "home": "Home", "away": "Away", "stage": "Test",
                "kickoff": "2099-08-10T20:00:00+08:00",
                "prediction_as_of": "2099-08-09T20:00:00+08:00",
                "mode": "market_only", "route": "market_baseline",
                "sporttery_meta": {"match_id": "freeze-test"},
            }
            out = {
                "fusion_status": "ok", "build_identity": identity,
                "core_engine_version": identity["core_version"],
                "core_output": {"engine_version": identity["core_version"]},
                "route": "market_baseline",
            }
            input_path, output_path, store = root / "input.json", root / "output.json", root / "store"
            input_path.write_text(json.dumps(inp), encoding="utf-8")
            output_path.write_text(json.dumps(out), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(SCRIPTS / "fusion_record.py"), "--input", str(input_path),
                                   "--output", str(output_path), "--store", str(store), "--snapshot", "prematch"],
                                  text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            entry = json.loads((store / "registry.jsonl").read_text(encoding="utf-8").splitlines()[0])
            record = json.loads(Path(entry["path"]).read_text(encoding="utf-8"))
            self.assertEqual(record["prediction_as_of"], inp["prediction_as_of"])
            self.assertEqual(record["route"], "market_baseline")
            self.assertEqual(record["mode"], "market_only")
            self.assertEqual(record["model"]["engine_bundle_sha256"], identity["engine_bundle_sha256"])
            self.assertEqual(record["model"]["prediction_code_sha256"], identity["prediction_code_sha256"])
            self.assertEqual(record["model"]["config_sha256"], identity["config_sha256"])
            self.assertEqual(record["hashes"]["input_raw_sha256"], hashlib.sha256(input_path.read_bytes()).hexdigest())
            self.assertEqual(record["hashes"]["output_raw_sha256"], hashlib.sha256(output_path.read_bytes()).hexdigest())
            self.assertRegex(record["hashes"]["input_raw_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(record["hashes"]["output_raw_sha256"], r"^[0-9a-f]{64}$")

    def test_prematch_registration_rejects_missing_or_unknown_complete_hashes(self):
        for omitted_or_unknown in (None, "unknown"):
            with self.subTest(engine_bundle_sha256=omitted_or_unknown), tempfile.TemporaryDirectory(prefix="fusion-reject-record-") as td:
                root = Path(td)
                input_path, output_path = root / "input.json", root / "output.json"
                input_path.write_text(json.dumps({"home": "Home", "away": "Away", "stage": "Test",
                                                   "kickoff": "2099-08-10T20:00:00+08:00",
                                                   "prediction_as_of": "2099-08-09T20:00:00+08:00"}), encoding="utf-8")
                identity = {
                    "core_version": "3.4.4", "fusion_version": "1.4.0",
                    "prediction_code_sha256": "a" * 64, "config_sha256": "b" * 64,
                }
                if omitted_or_unknown is not None:
                    identity["engine_bundle_sha256"] = omitted_or_unknown
                output_path.write_text(json.dumps({"fusion_status": "ok", "build_identity": identity}), encoding="utf-8")
                proc = subprocess.run([sys.executable, str(SCRIPTS / "fusion_record.py"), "--input", str(input_path),
                                       "--output", str(output_path), "--store", str(root / "store"), "--snapshot", "prematch"],
                                      text=True, capture_output=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("complete build hashes required", proc.stderr)

    def test_prematch_cannot_replace_but_distinct_experiment_snapshot_can_register(self):
        identity = fusion.build_identity()
        with tempfile.TemporaryDirectory(prefix="fusion-snapshot-record-") as td:
            root = Path(td)
            input_path, output_path, store = root / "input.json", root / "output.json", root / "store"
            input_path.write_text(json.dumps({"home": "Home", "away": "Away", "stage": "Test",
                                               "kickoff": "2099-08-10T20:00:00+08:00",
                                               "prediction_as_of": "2099-08-09T20:00:00+08:00",
                                               "mode": "market_only"}), encoding="utf-8")
            output_path.write_text(json.dumps({"fusion_status": "ok", "build_identity": identity,
                                                "core_output": {"engine_version": identity["core_version"]}}), encoding="utf-8")
            base = [sys.executable, str(SCRIPTS / "fusion_record.py"), "--input", str(input_path), "--output", str(output_path), "--store", str(store)]
            self.assertEqual(subprocess.run(base + ["--snapshot", "prematch"], text=True, capture_output=True).returncode, 0)
            blocked = subprocess.run(base + ["--snapshot", "prematch", "--replace-snapshot"], text=True, capture_output=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("prematch snapshots are immutable", blocked.stderr)
            self.assertEqual(subprocess.run(base + ["--snapshot", "api-hybrid"], text=True, capture_output=True).returncode, 0)
            entries = [json.loads(line) for line in (store / "registry.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(entries), 2)
            experiment = json.loads(Path(entries[1]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(experiment["prediction_as_of"], "2099-08-09T20:00:00+08:00")

    def test_same_prematch_allows_distinct_probability_version_after_release(self):
        """A new released probability cohort must be registrable for the same match."""
        m4_identity = fusion.build_identity()
        m3_identity = dict(m4_identity, model_version="m3", probability_signature="a" * 64)
        with tempfile.TemporaryDirectory(prefix="fusion-cross-version-record-") as td:
            root = Path(td)
            inp = {"home": "Home", "away": "Away", "stage": "Test",
                   "kickoff": "2099-08-10T20:00:00+08:00",
                   "prediction_as_of": "2099-08-09T20:00:00+08:00",
                   "sporttery_meta": {"match_id": "cross-version-test"}}
            input_path, output_path, store = root / "input.json", root / "output.json", root / "store"
            input_path.write_text(json.dumps(inp), encoding="utf-8")
            command = [sys.executable, str(SCRIPTS / "fusion_record.py"),
                       "--input", str(input_path), "--output", str(output_path),
                       "--store", str(store), "--snapshot", "prematch"]

            output_path.write_text(json.dumps({"fusion_status": "ok", "build_identity": m3_identity}), encoding="utf-8")
            first = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(json.loads(first.stdout)["status"], "recorded")

            output_path.write_text(json.dumps({"fusion_status": "ok", "build_identity": m4_identity}), encoding="utf-8")
            second = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr or second.stdout)
            self.assertEqual(json.loads(second.stdout)["status"], "recorded")
            entries = [json.loads(line) for line in (store / "registry.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(entries), 2)

    def test_prematch_requires_explicit_timezone_aware_as_of_strictly_before_kickoff(self):
        identity = fusion.build_identity()
        cases = {
            "missing": None,
            "naive": "2099-08-09T20:00:00",
            "equal": "2099-08-10T20:00:00+08:00",
            "after": "2099-08-10T20:00:01+08:00",
        }
        for name, prediction_as_of in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="fusion-asof-") as td:
                root = Path(td)
                inp = {"home": "Home", "away": "Away", "stage": "Test",
                       "kickoff": "2099-08-10T20:00:00+08:00"}
                if prediction_as_of is not None:
                    inp["prediction_as_of"] = prediction_as_of
                (root / "input.json").write_text(json.dumps(inp), encoding="utf-8")
                (root / "output.json").write_text(json.dumps({"fusion_status": "ok", "build_identity": identity}), encoding="utf-8")
                proc = subprocess.run([sys.executable, str(SCRIPTS / "fusion_record.py"),
                                       "--input", str(root / "input.json"), "--output", str(root / "output.json"),
                                       "--store", str(root / "store"), "--snapshot", "prematch"], text=True, capture_output=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("prediction_as_of", proc.stderr)

    def test_named_t_minus_snapshot_rejects_post_kickoff_prediction_time(self):
        """A T-minus label cannot bypass the formal pre-kickoff time boundary."""
        identity = fusion.build_identity()
        with tempfile.TemporaryDirectory(prefix="fusion-tminus-asof-") as td:
            root = Path(td)
            inp = {
                "home": "Home", "away": "Away", "stage": "Test",
                "kickoff": "2099-08-10T20:00:00+08:00",
                "prediction_as_of": "2099-08-10T20:00:01+08:00",
            }
            (root / "input.json").write_text(json.dumps(inp), encoding="utf-8")
            (root / "output.json").write_text(
                json.dumps({"fusion_status": "ok", "build_identity": identity}), encoding="utf-8")

            proc = subprocess.run([
                sys.executable, str(SCRIPTS / "fusion_record.py"),
                "--input", str(root / "input.json"), "--output", str(root / "output.json"),
                "--store", str(root / "store"), "--snapshot", "T-7h",
            ], text=True, capture_output=True)

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("prediction_as_of", proc.stderr)

    def test_llm_audit_hashes_are_required_and_frozen_in_prematch_cohort(self):
        identity = fusion.build_identity()
        with tempfile.TemporaryDirectory(prefix="fusion-llm-cohort-") as td:
            root = Path(td)
            base = {"home": "Home", "away": "Away", "stage": "Test",
                    "kickoff": "2099-08-10T20:00:00+08:00",
                    "prediction_as_of": "2099-08-09T20:00:00+08:00",
                    "route": "llm_production", "mode": "llm_ensemble"}
            output = {"fusion_status": "ok", "build_identity": identity}
            for missing in ("llm_model_pool_sha256", "evidence_file_sha256"):
                inp = dict(base)
                inp["llm_model_pool_sha256"] = "d" * 64
                inp["evidence_file_sha256"] = "e" * 64
                del inp[missing]
                (root / "input.json").write_text(json.dumps(inp), encoding="utf-8")
                (root / "output.json").write_text(json.dumps(output), encoding="utf-8")
                proc = subprocess.run([sys.executable, str(SCRIPTS / "fusion_record.py"),
                                       "--input", str(root / "input.json"), "--output", str(root / "output.json"),
                                       "--store", str(root / "store"), "--snapshot", "prematch"], text=True, capture_output=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("LLM audit hashes required", proc.stderr)

            inp = dict(base, llm_model_pool_sha256="d" * 64, evidence_file_sha256="e" * 64)
            (root / "input.json").write_text(json.dumps(inp), encoding="utf-8")
            (root / "output.json").write_text(json.dumps(output), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(SCRIPTS / "fusion_record.py"),
                                   "--input", str(root / "input.json"), "--output", str(root / "output.json"),
                                   "--store", str(root / "store"), "--snapshot", "prematch"], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            entry = json.loads((root / "store" / "registry.jsonl").read_text(encoding="utf-8").splitlines()[0])
            record = json.loads(Path(entry["path"]).read_text(encoding="utf-8"))
            self.assertEqual(record["llm_model_pool_sha256"], "d" * 64)
            self.assertEqual(record["evidence_file_sha256"], "e" * 64)
            self.assertEqual(record["cohort_key"], hashlib.sha256(
                "|".join([identity["model_version"], identity["probability_signature"],
                          "llm_production", "llm_ensemble", "d" * 64]).encode()
            ).hexdigest())


class BacktestSamplingTests(unittest.TestCase):
    def test_scored_row_retains_prediction_as_of_for_primary_snapshot_selection(self):
        """Registry evaluation must select by original prediction time, not persistence time."""
        with tempfile.TemporaryDirectory(prefix="fusion-score-asof-") as td:
            root = Path(td)
            (root / "results").mkdir()
            (root / "results" / "m1.json").write_text(
                json.dumps({"score_90": {"home": 1, "away": 0}}), encoding="utf-8")
            record = {
                "match_id": "m1", "prediction_id": "m1-p", "snapshot_type": "prematch",
                "created_at": "2026-08-21T16:00:00Z",
                "prediction_as_of": "2026-08-21T14:00:00Z",
                "match": {"kickoff": "2026-08-22T00:00:00Z"},
                "model": {"model_version": "m4", "probability_signature": "a" * 64},
                "input": {"odds": [2.0, 3.0, 4.0]},
                "output": {"final_1x2_pct": [50.0, 30.0, 20.0]},
            }

            row, error = backtest.score_record(record, root)

        self.assertIsNone(error)
        self.assertEqual(row["prediction_as_of"], "2026-08-21T14:00:00Z")

    def test_dedupe_keeps_same_snapshot_when_probability_versions_differ(self):
        """A post-release m4 prediction is a distinct evaluable record from m3."""
        rows = [
            {"match_id": "m1", "snapshot_type": "prematch", "created_at": "2026-08-21T13:00:00Z",
             "prediction_id": "m1-m3", "model": {"model_version": "m3", "probability_signature": "a" * 64}},
            {"match_id": "m1", "snapshot_type": "prematch", "created_at": "2026-08-21T14:00:00Z",
             "prediction_id": "m1-m4", "model": {"model_version": "m4", "probability_signature": "b" * 64}},
        ]

        deduped, dropped = backtest.dedupe_snapshot_rows(rows)

        self.assertEqual({row["prediction_id"] for row in deduped}, {"m1-m3", "m1-m4"})
        self.assertEqual(dropped, [])

    def test_latest_before_kickoff_uses_actual_prediction_time_across_versions(self):
        """Later valid m4 snapshot must not be hidden by an older generic prematch label."""
        rows = [
            {"match_id": "m1", "snapshot_type": "prematch",
             "created_at": "2026-08-21T13:28:40Z",
             "prediction_as_of": "2026-08-21T13:28:33Z",
             "prediction_id": "m1-m3", "model_version": "m3"},
            {"match_id": "m1", "snapshot_type": "T-7h",
             "created_at": "2026-08-21T16:11:10Z",
             "prediction_as_of": "2026-08-21T16:10:49Z",
             "prediction_id": "m1-m4", "model_version": "m4"},
        ]

        primary = backtest.select_primary_rows(rows, "latest_before_kickoff")

        self.assertEqual([row["prediction_id"] for row in primary], ["m1-m4"])

    def test_primary_evaluation_keeps_one_snapshot_per_match(self):
        rows = [
            {"match_id": "m1", "snapshot_type": "opening", "created_at": "2026-08-01T00:00:00Z", "prediction_id": "m1-o1"},
            {"match_id": "m1", "snapshot_type": "opening", "created_at": "2026-08-01T00:01:00Z", "prediction_id": "m1-o2"},
            {"match_id": "m1", "snapshot_type": "prematch", "created_at": "2026-08-01T02:00:00Z", "prediction_id": "m1-p"},
            {"match_id": "m2", "snapshot_type": "t-24h", "created_at": "2026-08-01T00:00:00Z", "prediction_id": "m2-24"},
            {"match_id": "m2", "snapshot_type": "t-6h", "created_at": "2026-08-01T01:00:00Z", "prediction_id": "m2-6"},
        ]
        deduped, dropped = backtest.dedupe_snapshot_rows(rows)
        self.assertEqual(len(deduped), 4)
        self.assertEqual(dropped[0]["superseded"], "m1-o1")

        primary = backtest.select_primary_rows(deduped, "latest_before_kickoff")
        self.assertEqual(len(primary), 2)
        self.assertEqual({r["prediction_id"] for r in primary}, {"m1-p", "m2-6"})

    def test_latest_before_kickoff_uses_observed_at_and_rejects_post_kickoff(self):
        """Backfilled records must use pre-kickoff market observation, never write time."""
        rows = [
            {
                "match_id": "m1", "snapshot_type": "prematch",
                "created_at": "2026-08-23T20:00:00Z",
                "prediction_as_of": "",
                "observed_at": "2026-08-23T08:00:00Z",
                "kickoff": "2026-08-23T10:00:00Z", "prediction_id": "m1-pre",
            },
            {
                "match_id": "m1", "snapshot_type": "closing",
                "created_at": "2026-08-23T20:01:00Z",
                "prediction_as_of": "",
                "observed_at": "2026-08-23T11:00:00Z",
                "kickoff": "2026-08-23T10:00:00Z", "prediction_id": "m1-post",
            },
        ]

        primary = backtest.select_primary_rows(rows, "latest_before_kickoff")

        assert [row["prediction_id"] for row in primary] == ["m1-pre"]

    def test_score_record_retains_odds_observed_at_for_legacy_rows(self):
        """Legacy rows without prediction_as_of still expose auditable pre-match time."""
        with tempfile.TemporaryDirectory(prefix="fusion-score-observed-legacy-") as td:
            root = Path(td)
            (root / "results").mkdir()
            (root / "results" / "m1.json").write_text(
                json.dumps({"score_90": {"home": 1, "away": 0}}), encoding="utf-8"
            )
            record = {
                "match_id": "m1", "prediction_id": "m1-p", "snapshot_type": "prematch",
                "created_at": "2026-08-23T20:00:00Z",
                "match": {"kickoff": "2026-08-23T10:00:00Z"},
                "model": {"model_version": "m4", "probability_signature": "a" * 64},
                "input": {
                    "odds": [2.0, 3.0, 4.0],
                    "field_meta": {"odds": {"observed_at": "2026-08-23T08:00:00Z"}},
                },
                "output": {"final_1x2_pct": [50.0, 30.0, 20.0]},
            }

            row, error = backtest.score_record(record, root)

        assert error is None
        assert row["observed_at"] == "2026-08-23T08:00:00Z"

    def test_version_cohort_requires_matching_hashes_for_current(self):
        current = {
            "model_version": "m1",
            "probability_signature": "a" * 64,
            "fusion_version": "1.4.0", "core_version": "3.4.4",
            "engine_bundle_sha256": "a" * 64,
            "prediction_code_sha256": "b" * 64,
            "config_sha256": "c" * 64,
        }
        exact = {"version": "fusion-1.4.0-core-3.4.4",
                 "model": {"model_version": "m1", "probability_signature": "a" * 64}}
        unhashed = {"version": "fusion-1.4.0-core-3.4.4", "model": {}}
        unknown = {"version": "unknown", "model": {}}
        self.assertEqual(backtest.version_cohort(exact, current), "current")
        self.assertEqual(backtest.version_cohort(unhashed, current), "legacy")
        self.assertEqual(backtest.version_cohort(unknown, current), "unknown")

    def test_paired_market_comparison_bootstraps_same_match_deltas(self):
        rows = []
        actuals = [0, 1, 2, 0, 1, 2]
        for i, actual in enumerate(actuals):
            model = [0.05, 0.05, 0.05]
            model[actual] = 0.90
            rows.append({
                "match_id": f"m{i}", "actual_idx": actual,
                "probs": model, "market_probs": [1 / 3, 1 / 3, 1 / 3],
            })
        report = backtest.paired_market_comparison(rows, iterations=500, seed=20260808)
        self.assertEqual(report["n"], 6)
        self.assertLess(report["brier_delta_model_minus_market"], 0)
        self.assertLess(report["brier_delta_95ci"][1], 0)
        self.assertLess(report["log_loss_delta_95ci"][1], 0)

    def test_walk_forward_keeps_time_order_and_match_groups(self):
        rows = []
        for day in range(1, 10):
            rows.append({
                "match_id": f"m{day}", "kickoff": f"2026-08-{day:02d}T20:00:00+08:00",
                "actual_idx": day % 3, "probs": [0.34, 0.33, 0.33],
                "market_probs": [0.33, 0.34, 0.33],
                "top_scores": None, "actual_score": None, "ou25": None,
                "btts": None, "clv_pp": None,
            })
        report = backtest.walk_forward_report(rows, folds=3, bootstrap_iterations=50)
        self.assertEqual(len(report["folds"]), 3)
        for fold in report["folds"]:
            self.assertLess(fold["train_end"], fold["test_start"])
            self.assertTrue(set(fold["train_match_ids"]).isdisjoint(fold["test_match_ids"]))

    def test_backtest_cli_reports_match_unit_cohorts_and_paired_market(self):
        identity = fusion.build_identity()
        with tempfile.TemporaryDirectory(prefix="fusion-p0-backtest-") as td:
            root = Path(td)
            (root / "predictions").mkdir()
            (root / "results").mkdir()
            registry = []
            fixtures = [
                ("m1", "opening", "2026-08-01T01:00:00Z", [45, 30, 25]),
                ("m1", "prematch", "2026-08-01T02:00:00Z", [50, 28, 22]),
                ("m2", "prematch", "2026-08-02T02:00:00Z", [30, 32, 38]),
            ]
            for mid, snapshot, created, probs in fixtures:
                pid = f"{mid}-{snapshot}"
                path = root / "predictions" / f"{pid}.json"
                record = {
                    "prediction_id": pid, "match_id": mid, "snapshot_type": snapshot,
                    "created_at": created, "model": {**identity, "version": "fusion-1.4.0-core-3.4.4"},
                    "match": {"competition": "Test", "kickoff": f"2026-08-0{1 if mid == 'm1' else 2}T20:00:00+08:00"},
                    "input": {"odds": [2.2, 3.2, 3.4]},
                    "output": {"final_1x2_pct": probs, "market_prob_pct": [44, 30, 26]},
                }
                path.write_text(json.dumps(record), encoding="utf-8")
                registry.append({"prediction_id": pid, "match_id": mid, "path": str(path), "created_at": created})
            (root / "registry.jsonl").write_text(
                "".join(json.dumps(x) + "\n" for x in registry), encoding="utf-8")
            (root / "results" / "m1.json").write_text(json.dumps({"score_90": {"home": 1, "away": 0}}), encoding="utf-8")
            (root / "results" / "m2.json").write_text(json.dumps({"score_90": {"home": 0, "away": 1}}), encoding="utf-8")
            report_path = root / "report.json"
            proc = subprocess.run([
                sys.executable, str(SCRIPTS / "fusion_backtest.py"),
                "--store", str(root), "--output", str(report_path),
                "--snapshot-policy", "latest_before_kickoff",
                "--walk-forward-folds", "1", "--bootstrap-iterations", "50",
            ], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["record_sample_size"], 3)
            self.assertEqual(report["sample_size"], 2)
            self.assertEqual(report["unique_match_n"], 2)
            self.assertEqual(report["by_version_cohort"]["current"]["n"], 2)
            self.assertEqual(report["snapshot_research"]["by_snapshot"]["prematch"]["n"], 2)
            self.assertEqual(report["paired_market"]["n"], 2)
            self.assertEqual(report["walk_forward"]["fold_count"], 1)

            audit_path = root / "audit.json"
            audit_proc = subprocess.run([
                sys.executable, str(SCRIPTS / "sample_audit.py"),
                "--store", str(root), "--output", str(audit_path),
                "--snapshot-policy", "latest_before_kickoff",
            ], text=True, capture_output=True)
            self.assertEqual(audit_proc.returncode, 0, audit_proc.stderr or audit_proc.stdout)
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["registered_snapshots"], 3)
            self.assertEqual(audit["registered_unique_matches"], 2)
            self.assertEqual(audit["primary_evaluation_matches"], 2)
            self.assertEqual(audit["by_version_cohort"]["current"], 2)

            walk_path = root / "walk.json"
            walk_proc = subprocess.run([
                sys.executable, str(SCRIPTS / "evaluate_walk_forward.py"),
                "--store", str(root), "--output", str(walk_path),
                "--folds", "1", "--bootstrap-iterations", "50",
            ], text=True, capture_output=True)
            self.assertEqual(walk_proc.returncode, 0, walk_proc.stderr or walk_proc.stdout)
            walk = json.loads(walk_path.read_text(encoding="utf-8"))
            self.assertEqual(walk["schema_version"], "fusion-walk-forward-1.0")
            self.assertEqual(walk["walk_forward"]["fold_count"], 1)


class TimeSemanticsTests(unittest.TestCase):
    def test_freshness_uses_collection_age_not_kickoff_or_source_update_age(self):
        report = market_fit.market_freshness({
            "kickoff": "2026-08-20T20:00:00+08:00",
            "prediction_as_of": "2026-08-08T00:05:00+08:00",
            "field_meta": {"odds": {
                "collected_at": "2026-08-08T00:00:00+08:00",
                "source_updated_at": "2026-01-01T00:00:00+08:00",
                "observed_at": "2026-01-01T00:00:00+08:00",
            }},
        })
        self.assertEqual(report["had"]["status"], "FRESH")
        self.assertEqual(report["had"]["basis"], "collection_age")
        self.assertAlmostEqual(report["had"]["age_hours"], 5 / 60, places=3)

        unknown = market_fit.market_freshness({
            "kickoff": "2026-08-20T20:00:00+08:00",
            "field_meta": {"odds": {"observed_at": "2026-08-08T00:00:00+08:00"}},
        })
        self.assertEqual(unknown["had"]["status"], "UNKNOWN")
        self.assertEqual(unknown["had"]["basis"], "missing_collection_anchor")

    def test_collector_emits_separate_collection_and_source_times(self):
        fetched_at = "2026-08-08T00:05:00+08:00"
        meta = sales_day_collect.build_field_meta({
            "had_updated_at": "2026-08-07T23:00:00+08:00",
            "hhad_updated_at": "2026-08-07T22:00:00+08:00",
        }, fetched_at)
        self.assertEqual(meta["odds"]["collected_at"], fetched_at)
        self.assertEqual(meta["odds"]["source_updated_at"], "2026-08-07T23:00:00+08:00")
        self.assertEqual(meta["odds"]["prediction_as_of"], fetched_at)
        self.assertEqual(meta["odds"]["observed_at"], fetched_at)


class OddsMovementPathTests(unittest.TestCase):
    def test_record_odds_capture_uses_canonical_data_root(self):
        completed = subprocess.CompletedProcess([], 0, stdout='{"added": 1}', stderr='')
        with patch.object(fusion_cli.subprocess, "run", return_value=completed) as run:
            fusion_cli.maybe_odds_add("raw.json")
        command = run.call_args.args[0]
        self.assertIn("--store", command)
        store = Path(command[command.index("--store") + 1]).resolve()
        self.assertEqual(store, fusion_cli.odds_store().resolve())

    def test_record_help_does_not_require_input_files(self):
        proc = subprocess.run([sys.executable, str(SCRIPTS / "fusion_cli.py"), "record", "--help"],
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("record --input", proc.stdout)

    def test_llm_evidence_delegates_to_configured_predictor_root(self):
        with tempfile.TemporaryDirectory(prefix="fusion-llm-root-") as td:
            root = Path(td)
            script = root / "mcp_evidence.py"
            script.write_text("# test", encoding="utf-8")
            with patch.dict(fusion_cli.os.environ, {"FOOTBALL_LLM_ROOT": str(root)}), \
                 patch.object(fusion_cli, "run_external_script") as delegated:
                fusion_cli.run_llm_evidence(["--help"])
            delegated.assert_called_once_with(script, ["--help"])


if __name__ == "__main__":
    unittest.main()

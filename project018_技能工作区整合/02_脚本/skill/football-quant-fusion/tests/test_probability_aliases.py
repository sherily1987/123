from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "probability_aliases", SCRIPTS / "probability_aliases.py"
)
aliases = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(aliases)


OLD_SIG = "a" * 64
CURRENT_SIG = "b" * 64
REQUIRED_FIELDS = [
    "final_1x2_pct",
    "model_1x2_pct",
    "score_matrix",
    "top_scores",
    "ou_2_5",
    "ou_3_5",
    "btts",
    "hafu_model",
    "ttg_score_consistency",
]


def _write_lock(path: Path, *, signature: str = CURRENT_SIG) -> None:
    path.write_text(json.dumps({
        "model_version": "m4",
        "probability_signature": signature,
    }), encoding="utf-8")


def _write_attestation(
    path: Path,
    *,
    status: str = "PENDING_REVIEW",
    route: str = "market_only",
    fields: list[str] | None = None,
    result_statuses: tuple[str, ...] = ("identical", "identical"),
    old_signature: str = OLD_SIG,
    target_signature: str = CURRENT_SIG,
    old_model_version: object = "m4",
    target_model_version: object = "m4",
    tolerance: object = 1e-10,
) -> None:
    results = [
        {
            "match_id": f"match-{index}",
            "status": result_status,
            "route": route,
            "prediction_as_of": "2026-08-25T01:00:00+00:00",
            "input_sha256": hashlib.sha256(f"input-{index}".encode()).hexdigest(),
            "diffs": {},
            "registered_identity": {
                "match_id": f"match-{index}", "home": "Home", "away": "Away",
                "competition": "League", "kickoff": "2026-08-25T03:00:00+00:00",
                "prediction_as_of": "2026-08-25T01:00:00+00:00",
                "model_version": old_model_version,
                "probability_signature": old_signature, "route": route,
            },
            "input_identity": {
                "match_id": f"match-{index}", "home": "Home", "away": "Away",
                "competition": "League", "kickoff": "2026-08-25T03:00:00+00:00",
                "prediction_as_of": "2026-08-25T01:00:00+00:00", "route": route,
            },
            "time_audit": {
                "usable": True, "reason": None,
                "registered_prediction_as_of": "2026-08-25T01:00:00+00:00",
                "input_prediction_as_of": "2026-08-25T01:00:00+00:00",
                "registered_kickoff": "2026-08-25T03:00:00+00:00",
                "input_kickoff": "2026-08-25T03:00:00+00:00",
                "prediction_before_kickoff": True,
                "evidence_after_prediction_as_of": False,
            },
        }
        for index, result_status in enumerate(result_statuses, start=1)
    ]
    core = {
        "schema_version": "signature-drift-attestation-1.0",
        "old_identity": {
            "model_version": old_model_version,
            "probability_signature": old_signature,
        },
        "route": route,
        "current_identity": {
            "model_version": target_model_version,
            "probability_signature": target_signature,
        },
        "compare_fields": fields if fields is not None else REQUIRED_FIELDS,
        "float_tolerance": tolerance,
        "record_count": len(results),
        "results": results,
        "status": status,
        "alias_eligible": False,
    }
    payload = dict(core)
    payload["report_hash_input"] = core
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload["generated_at"] = "2026-08-26T01:00:00+00:00"
    payload["attestation_path"] = str(path)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _approve(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    report = tmp_path / "proof.json"
    alias_file = tmp_path / "aliases.json"
    lock_file = tmp_path / "release_lock.json"
    _write_attestation(report)
    _write_lock(lock_file)
    approved = aliases.approve_attestation(report, alias_file, lock_file)
    return approved, report, alias_file, lock_file


def test_approval_function_rejects_unreviewable_proof_without_touching_alias_file(tmp_path):
    report = tmp_path / "unreplayable.json"
    alias_file = tmp_path / "probability_aliases.json"
    lock_file = tmp_path / "release_lock.json"
    _write_lock(lock_file)
    _write_attestation(report, status="UNREPLAYABLE", result_statuses=("UNREPLAYABLE",))
    alias_file.write_text(
        '{"schema_version":"probability-aliases-1.0","aliases":[]}\n',
        encoding="utf-8",
    )
    before = alias_file.read_bytes()

    with pytest.raises(aliases.ProbabilityAliasError, match="PENDING_REVIEW"):
        aliases.approve_attestation(report, alias_file, lock_file)
    assert alias_file.read_bytes() == before


@pytest.mark.parametrize("forbidden_option", ["--aliases", "--release-lock"])
def test_production_approval_cli_does_not_expose_governance_output_paths(
        tmp_path, forbidden_option):
    report = tmp_path / "proof.json"
    _write_attestation(report)

    with pytest.raises(SystemExit) as exc_info:
        aliases.main([
            "--attestation", str(report), forbidden_option, str(tmp_path / "override.json"),
        ])

    assert exc_info.value.code == 2


def test_production_approval_cli_uses_only_managed_config_paths(monkeypatch, tmp_path):
    report = tmp_path / "proof.json"
    _write_attestation(report)
    captured = {}

    def fake_approve(report_path, alias_path, lock_path):
        captured.update(report=report_path, aliases=alias_path, release_lock=lock_path)
        return {"status": "EQUIVALENT_ALIAS"}

    monkeypatch.setattr(aliases, "approve_attestation", fake_approve)

    assert aliases.main(["--attestation", str(report)]) == 0
    assert captured == {
        "report": report,
        "aliases": aliases.MANAGED_ALIAS_PATH,
        "release_lock": aliases.MANAGED_RELEASE_LOCK_PATH,
    }
    assert aliases.MANAGED_ALIAS_PATH == SKILL_ROOT / "config" / "probability_aliases.json"
    assert aliases.MANAGED_RELEASE_LOCK_PATH == SKILL_ROOT / "config" / "release_lock.json"


def test_approval_writes_exact_route_scoped_alias_from_proof(tmp_path):
    approved, report, alias_file, lock_file = _approve(tmp_path)

    assert approved == {
        "status": "EQUIVALENT_ALIAS",
        "model_version": "m4",
        "probability_signature": OLD_SIG,
        "route": "market_only",
        "alias_to_model_version": "m4",
        "alias_to_probability_signature": CURRENT_SIG,
        "attestation_path": str(report.resolve()),
        "attestation_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    }
    assert aliases.load_approved_aliases(alias_file, lock_file) == [approved]


def test_alias_rejected_after_attestation_is_modified(tmp_path):
    _, report, alias_file, lock_file = _approve(tmp_path)

    report.write_text(report.read_text(encoding="utf-8") + " ", encoding="utf-8")

    assert aliases.load_approved_aliases(alias_file, lock_file) == []


def test_alias_rejected_after_current_release_lock_changes(tmp_path):
    _, _, alias_file, lock_file = _approve(tmp_path)

    _write_lock(lock_file, signature="c" * 64)

    assert aliases.load_approved_aliases(alias_file, lock_file) == []


def test_load_revalidates_tolerance_even_if_proof_and_outer_hash_are_recomputed(tmp_path):
    _, report, alias_file, lock_file = _approve(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["float_tolerance"] = True
    hash_input = {key: value for key, value in payload.items() if key not in {
        "generated_at", "report_sha256", "report_hash_input", "attestation_path",
    }}
    payload["report_hash_input"] = hash_input
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(hash_input, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    alias_document = json.loads(alias_file.read_text(encoding="utf-8"))
    alias_document["aliases"][0]["attestation_sha256"] = hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
    alias_file.write_text(
        json.dumps(alias_document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    assert aliases.load_approved_aliases(alias_file, lock_file) == []


def test_market_only_alias_does_not_admit_hybrid_row(tmp_path):
    approved, _, _, _ = _approve(tmp_path)

    assert aliases.matches({
        "model": {"model_version": "m4", "probability_signature": OLD_SIG},
        "input": {"mode": "market_only"},
    }, approved)
    assert not aliases.matches({
        "model": {"model_version": "m4", "probability_signature": OLD_SIG},
        "input": {"mode": "hybrid"},
    }, approved)


def test_alias_match_does_not_coerce_corrupt_identity_or_route_types():
    approved = {
        "model_version": "m4",
        "probability_signature": "1" * 64,
        "route": "1",
    }

    assert not aliases.matches({
        "model": {"model_version": "m4", "probability_signature": int("1" * 64)},
        "input": {"mode": "1"},
    }, approved)
    assert not aliases.matches({
        "model": {"model_version": "m4", "probability_signature": "1" * 64},
        "input": {"mode": 1},
    }, approved)


@pytest.mark.parametrize(
    "proof_change,error_text",
    [
        ({"status": "CHANGED_REQUIRES_VERSION_BUMP"}, "PENDING_REVIEW"),
        ({"result_statuses": ("identical", "UNREPLAYABLE")}, "全组"),
        ({"fields": REQUIRED_FIELDS[:-1]}, "比较字段"),
        ({"route": ""}, "路由"),
        ({"old_signature": "short"}, "旧概率签名"),
        ({"target_signature": "short"}, "目标概率签名"),
        ({"old_model_version": 4}, "旧模型身份"),
        ({"target_model_version": 4}, "目标模型身份"),
    ],
)
def test_approval_rejects_incomplete_or_non_equivalent_group(
    tmp_path, proof_change, error_text
):
    report = tmp_path / "proof.json"
    alias_file = tmp_path / "aliases.json"
    lock_file = tmp_path / "release_lock.json"
    _write_attestation(report, **proof_change)
    _write_lock(lock_file)

    with pytest.raises(aliases.ProbabilityAliasError, match=error_text):
        aliases.approve_attestation(report, alias_file, lock_file)

    assert not alias_file.exists()


def test_approval_rejects_target_not_equal_to_release_lock(tmp_path):
    report = tmp_path / "proof.json"
    alias_file = tmp_path / "aliases.json"
    lock_file = tmp_path / "release_lock.json"
    _write_attestation(report)
    _write_lock(lock_file, signature="c" * 64)

    with pytest.raises(aliases.ProbabilityAliasError, match="发布锁"):
        aliases.approve_attestation(report, alias_file, lock_file)


def test_approval_is_idempotent_for_the_same_attestation(tmp_path):
    approved, report, alias_file, lock_file = _approve(tmp_path)

    assert aliases.approve_attestation(report, alias_file, lock_file) == approved
    assert json.loads(alias_file.read_text(encoding="utf-8"))["aliases"] == [approved]

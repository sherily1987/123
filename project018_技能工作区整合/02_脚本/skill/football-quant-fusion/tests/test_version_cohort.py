"""版本归因回归测试（2026-08-14）。

背景：原 version_cohort 只看 model.version 字符串，凡是 "unknown" 一律判 unknown，
导致 1445 条带完整 engine_sha256 的历史样本被当成不可归因（生产回测里占 81%），
掩盖了「当前引擎构建确实零样本」这个真实结论。
"""
import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("fusion_backtest", SCRIPTS / "fusion_backtest.py")
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)

SHA_A = "9fe6e8e8a988e6dfcf0c3ca52a90682330e37e3fe679921da16b1e6e4c3b3c69"
SHA_B = "b30608d06d7f88fb47608893cb25b194eab4085c0d2efe682b862d50afa4ac9b"
IDENTITY = {
    "fusion_version": "1.4.0",
    "core_version": "3.4.4",
    "engine_bundle_sha256": SHA_B,
    "prediction_code_sha256": SHA_A,
    "config_sha256": SHA_B,
}


def _row(model, core_engine_version=None, version=None):
    return {"model": model, "core_engine_version": core_engine_version, "version": version}


def test_exact_hash_match_is_current():
    row = _row(dict(IDENTITY), version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, IDENTITY) == "current"


def test_hash_mismatch_is_legacy_not_current():
    model = dict(IDENTITY)
    model["config_sha256"] = SHA_A
    assert fb.version_cohort(_row(model, version="fusion-1.4.0-core-3.4.4"), IDENTITY) == "legacy"


def test_vunknown_with_engine_sha_is_legacy_not_unknown():
    """核心回归：version=="unknown" 但有 engine_sha256 的历史样本必须可归因。"""
    row = _row({"version": "unknown", "engine_sha256": SHA_A}, core_engine_version="3.4.4",
               version="unknown")
    assert fb.version_cohort(row, IDENTITY) == "legacy"
    assert fb.engine_build_key(row) == "engine-9fe6e8e8a988+core-3.4.4"


def test_offline_row_without_any_hash_stays_unknown():
    assert fb.version_cohort(_row({}, version="offline"), IDENTITY) == "unknown"
    assert fb.engine_build_key(_row({})) == ""


def test_engine_build_key_prefers_frozen_bundle_hash():
    row = _row({"engine_bundle_sha256": SHA_B, "engine_sha256": SHA_A}, core_engine_version="3.4.4")
    assert fb.engine_build_key(row) == "bundle-b30608d06d7f"


def test_different_engine_sha_yields_different_build_key():
    a = _row({"version": "unknown", "engine_sha256": SHA_A}, core_engine_version="3.4.4")
    b = _row({"version": "unknown", "engine_sha256": SHA_B}, core_engine_version="3.4.4")
    assert fb.engine_build_key(a) != fb.engine_build_key(b)


def test_truncated_hash_is_not_accepted_as_identity():
    row = _row({"version": "unknown", "engine_sha256": SHA_A[:20]}, core_engine_version="3.4.4")
    assert fb.engine_build_key(row) == ""
    assert fb.version_cohort(row, IDENTITY) == "unknown"

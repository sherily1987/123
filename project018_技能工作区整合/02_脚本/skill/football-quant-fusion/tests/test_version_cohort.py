"""版本归因回归测试（2026-08-15 版本管理方案更新）。

背景：2026-08-15 起 cohort 主键从「5 字段全量字节哈希」改为
「model_version + probability_signature」，让框架代码/日志/注释改动不再重置样本。
本测试保留 08-14 的 legacy/unknown 回归用例，并新增新逻辑的 current 判定用例。
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
    "model_version": "m1",
    "probability_signature": SHA_A,
    "fusion_version": "1.4.0",
    "core_version": "3.4.4",
    "engine_bundle_sha256": SHA_B,
    "prediction_code_sha256": SHA_A,
    "config_sha256": SHA_B,
}


def _row(model, core_engine_version=None, version=None):
    return {"model": model, "core_engine_version": core_engine_version, "version": version}


# ---- 新逻辑：model_version + probability_signature 判定 current ----

def test_model_version_and_signature_match_is_current():
    row = _row({"model_version": "m1", "probability_signature": SHA_A},
               version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, IDENTITY) == "current"


def test_probability_signature_mismatch_is_legacy():
    """概率文件已改但 model_version 未 bump → 不能算 current，归 legacy。"""
    row = _row({"model_version": "m1", "probability_signature": SHA_B},
               version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, IDENTITY) == "legacy"


def test_model_version_mismatch_is_legacy():
    row = _row({"model_version": "m2", "probability_signature": SHA_A},
               version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, IDENTITY) == "legacy"


def test_framework_code_change_does_not_reset_current():
    """框架代码（engine_bundle/prediction_code）变化不影响 current 判定。"""
    row = _row({"model_version": "m1", "probability_signature": SHA_A,
                "engine_bundle_sha256": SHA_A, "prediction_code_sha256": SHA_B},
               version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, IDENTITY) == "current"


def test_old_record_without_model_version_is_legacy_not_current():
    """旧记录无 model_version/probability_signature → 回退引擎构建指纹归 legacy。"""
    row = _row({"engine_sha256": SHA_A}, core_engine_version="3.4.4", version="unknown")
    assert fb.version_cohort(row, IDENTITY) == "legacy"


# ---- legacy/unknown 回归（沿用 08-14 逻辑，不因版本管理改动而变） ----

def test_vunknown_with_engine_sha_is_legacy_not_unknown():
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


# ---- 2026-08-16：经重放验证等价的旧版本别名 ----

ALIAS_SHA = "5b608c3debf8d1de2659d552e5569f84e684e7e86105255e5de76f03a7d5b633"
CURRENT_IDENTITY = {"model_version": "m2", "probability_signature": SHA_B}
ALIAS_ENTRY = {"model_version": "m1", "probability_signature": ALIAS_SHA}


def test_verified_equivalent_alias_counts_as_current(monkeypatch):
    """m1→m2 的 bump 数值中性时，m1 样本不该被迫从零重攒。"""
    monkeypatch.setattr(fb, "load_version_aliases", lambda: [ALIAS_ENTRY])
    row = _row({"model_version": "m1", "probability_signature": ALIAS_SHA},
               version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, CURRENT_IDENTITY) == "current"


def test_alias_requires_exact_signature_pair(monkeypatch):
    """同为 m1 但签名不是登记的那个 → 不享受别名，仍归 legacy。"""
    monkeypatch.setattr(fb, "load_version_aliases", lambda: [ALIAS_ENTRY])
    row = _row({"model_version": "m1", "probability_signature": SHA_A},
               version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, CURRENT_IDENTITY) == "legacy"


def test_no_alias_configured_keeps_old_version_legacy(monkeypatch):
    monkeypatch.setattr(fb, "load_version_aliases", lambda: [])
    row = _row({"model_version": "m1", "probability_signature": ALIAS_SHA},
               version="fusion-1.4.0-core-3.4.4")
    assert fb.version_cohort(row, CURRENT_IDENTITY) == "legacy"


def test_manifest_aliases_reject_malformed_entries():
    """真实 manifest 里的别名必须成对且签名合法，否则不予采信。"""
    for alias in fb.load_version_aliases():
        assert alias["model_version"]
        assert len(alias["probability_signature"]) == 64

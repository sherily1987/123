import importlib.util
from pathlib import Path


def _load_module():
    module_path = Path(__file__).parents[1] / "scripts" / "runtime_paths.py"
    spec = importlib.util.spec_from_file_location("runtime_paths", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_data_root_defaults_to_project018_shared_data(monkeypatch):
    monkeypatch.delenv("FUSION_DATA_ROOT", raising=False)
    paths = _load_module()

    assert paths.data_root() == paths.project_root() / "04_素材" / "shared-data" / "football-quant-fusion"


def test_environment_overrides_are_used(monkeypatch, tmp_path):
    monkeypatch.setenv("FUSION_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("FUSION_CORE_DIR", str(tmp_path / "core"))
    paths = _load_module()

    assert paths.data_root() == tmp_path / "data"
    assert paths.core_scripts_dir() == tmp_path / "core"


def test_derived_data_paths_use_canonical_root(monkeypatch, tmp_path):
    monkeypatch.setenv("FUSION_DATA_ROOT", str(tmp_path / "canonical"))
    paths = _load_module()
    assert paths.backtest_store() == tmp_path / "canonical" / "backtest"
    assert paths.odds_store() == tmp_path / "canonical" / "odds" / "production_movement.jsonl"
    assert paths.forward_work_dir() == tmp_path / "canonical" / "forward"


def test_legacy_suite_write_is_blocked(monkeypatch):
    paths = _load_module()
    legacy = Path("C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/x")
    try:
        paths.assert_writable_target(legacy)
    except ValueError as exc:
        assert "legacy" in str(exc).lower()
    else:
        raise AssertionError("legacy suite path should be blocked")


def test_validate_cli_paths_rejects_legacy_store_override():
    paths = _load_module()
    legacy = r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared-data"
    try:
        paths.validate_cli_paths(["--store", legacy])
    except ValueError as exc:
        assert "legacy fusion suite is read-only" in str(exc)
    else:
        raise AssertionError("legacy CLI store override should be blocked")


def test_core_copy_status_reports_matching_critical_files(tmp_path, monkeypatch):
    paths = _load_module()
    repo = tmp_path / "repo"
    external = tmp_path / "external"
    repo.mkdir()
    external.mkdir()
    for name in ("predict.py", "team_strength.py"):
        (repo / name).write_text(name, encoding="utf-8")
        (external / name).write_text(name, encoding="utf-8")
    monkeypatch.setenv("FUSION_CORE_DIR", str(repo))
    monkeypatch.setenv("FUSION_LEGACY_CORE_DIR", str(external))
    report = paths.core_copy_status()
    assert report["status"] == "MATCH"
    assert report["mismatches"] == []

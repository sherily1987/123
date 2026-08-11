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

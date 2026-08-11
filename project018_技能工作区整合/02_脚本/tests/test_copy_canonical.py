import importlib.util
from pathlib import Path


def _load_module():
    module_path = Path(__file__).parents[1] / "tools" / "copy_canonical.py"
    spec = importlib.util.spec_from_file_location("copy_canonical", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_copy_canonical_copies_new_file_and_rejects_different_existing_bytes(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")
    (source / "same.txt").write_text("same", encoding="utf-8")
    (source / "conflict.txt").write_text("source", encoding="utf-8")
    (destination / "same.txt").write_text("same", encoding="utf-8")
    (destination / "conflict.txt").write_text("destination", encoding="utf-8")

    result = _load_module().copy_canonical(source, destination)

    assert result["copied"] == 1
    assert result["skipped"] == 1
    assert result["conflicted"] == 1
    assert (destination / "new.txt").read_text(encoding="utf-8") == "new"
    assert (destination / "conflict.txt").read_text(encoding="utf-8") == "destination"

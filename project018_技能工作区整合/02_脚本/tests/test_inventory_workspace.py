import importlib.util
from pathlib import Path


def _load_module():
    module_path = Path(__file__).parents[1] / "tools" / "inventory_workspace.py"
    spec = importlib.util.spec_from_file_location("inventory_workspace", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_inventory_groups_equal_hashes_and_keeps_source_paths(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "same.txt").write_text("same", encoding="utf-8")
    (second / "copied.txt").write_text("same", encoding="utf-8")
    (second / "different.txt").write_text("different", encoding="utf-8")

    report = _load_module().inventory({"first": first, "second": second})

    assert report["sources"]["first"] == str(first)
    assert report["sources"]["second"] == str(second)
    assert len(report["files"]) == 3
    assert report["duplicate_groups"] == [{
        "sha256": report["files"][0]["sha256"],
        "size": 4,
        "files": [
            {"source": "first", "path": "same.txt"},
            {"source": "second", "path": "copied.txt"},
        ],
    }]
    assert report["unreadable"] == []

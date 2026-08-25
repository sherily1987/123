from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_web_runtime_files(tmp_path, monkeypatch):
    """No test may mutate the live Web database or formal launcher state."""
    import db
    import launch

    runtime = tmp_path / "web-runtime"
    monkeypatch.setattr(db, "DB_PATH", runtime / "app.db")
    monkeypatch.setattr(launch, "RUNTIME_STATE", runtime / "workbench.json")

from pathlib import Path
import sys

from fastapi.testclient import TestClient

import app as web


def test_ui_contract_and_legacy_entry_are_available():
    client = TestClient(web.app)
    contract = client.get("/api/ui-contract")
    legacy = client.get("/legacy.html")
    assert contract.status_code == 200
    payload = contract.json()
    assert payload == {
        "version": "b3",
        "pages": ["overview", "strategy", "backtest", "leagues", "evidence", "tasks", "versions", "export"],
        "task_actions": ["collect", "predict", "llm", "settle", "backtest"],
        "read_only_version_governance": True,
        "build_identity": payload["build_identity"],
        "process_id": payload["process_id"],
    }
    assert payload["build_identity"].startswith("b3:")
    assert isinstance(payload["process_id"], int)
    assert legacy.status_code == 200
    assert "只读" in legacy.text


def test_scanner_page_is_not_exposed_in_primary_navigation():
    text = TestClient(web.app).get("/").text
    assert 'data-route="scanner"' not in text
    assert "预测扫描" not in text


def test_legacy_entry_has_no_task_mutation_controls_or_post_code():
    """The rollback page remains useful for GET browsing but cannot start tasks."""
    text = TestClient(web.app).get("/legacy.html").text
    for control_id in ("btnCollect", "btnPredict", "btnSettle", "btnBacktest", "btnLlm"):
        assert f'id="{control_id}"' not in text
    assert 'method: "POST"' not in text
    assert "method:'POST'" not in text
    assert "runAction(" not in text


def test_legacy_entry_is_static_read_only_and_does_not_interpolate_external_data():
    text = TestClient(web.app).get("/legacy.html").text
    assert "innerHTML" not in text
    assert "onclick=" not in text
    malicious = '<img src=x onerror="alert(1)">'
    response = TestClient(web.app).get("/legacy.html", params={"match": malicious})
    assert malicious not in response.text
    assert "onerror" not in response.text


def test_read_only_strategy_preview_and_current_sale_day_never_persist(monkeypatch):
    calls = []

    def fake_strategy(day, persist=False):
        calls.append((day, persist))
        return {"selected_day": day, "persisted": persist}

    monkeypatch.setattr(web.dsv, "daily_strategy", fake_strategy)
    monkeypatch.setattr(web.dsv, "current_sale_day", lambda: "2026-08-27")
    client = TestClient(web.app)

    preview = client.get("/api/daily-strategy/preview", params={"day": "2026-08-26"})
    current = client.get("/api/current-sale-day")

    assert preview.status_code == 200
    assert preview.json() == {"selected_day": "2026-08-26", "persisted": False}
    assert current.status_code == 200
    assert current.json() == {"sales_day": "2026-08-27"}
    assert calls == [("2026-08-26", False)]


def test_export_report_is_read_only_and_does_not_create_a_runtime_file(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "HERE", tmp_path)
    monkeypatch.setattr(web.sv, "board", lambda: {
        "as_of": "2026-08-26T12:00:00+08:00", "store": "test-store",
        "summary": {"on_sale": 1, "has_odds": 1, "predicted": 1, "missing_pred": 0},
        "by_league": [],
    })

    response = TestClient(web.app).get("/api/export/report")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "体彩看板" in response.text
    assert not (tmp_path / "data" / "board_report.md").exists()


def test_legacy_browser_is_functional_but_uses_only_safe_read_endpoints():
    static = Path(__file__).parent / "static"
    html = (static / "legacy.html").read_text(encoding="utf-8")
    script = (static / "js" / "legacy.js").read_text(encoding="utf-8")

    assert 'src="/js/legacy.js"' in html
    for endpoint in ("/api/current-sale-day", "/api/matches", "/api/daily-strategy/preview", "/api/history", "/api/match/", "/api/export/report"):
        assert endpoint in html + script
    assert "method: \"POST\"" not in script
    assert "innerHTML" not in script
    assert "onclick=" not in html
    assert "textContent" in script
    assert "addEventListener" in script
def test_app_main_delegates_to_managed_launcher(monkeypatch):
    calls = []
    monkeypatch.setattr(web.subprocess, "call", lambda command, cwd: calls.append((command, cwd)) or 0)

    result = web.main(["--status"])

    assert result == 0
    assert calls == [
        ([sys.executable, str(web.HERE / "launch.py"), "--status"], str(web.HERE)),
    ]

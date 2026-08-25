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
    assert "/api/" not in text
    assert "fetch(" not in text
    assert "innerHTML" not in text
    assert "onclick=" not in text
    malicious = '<img src=x onerror="alert(1)">'
    response = TestClient(web.app).get("/legacy.html", params={"match": malicious})
    assert malicious not in response.text
    assert "onerror" not in response.text

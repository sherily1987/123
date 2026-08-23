import importlib.util
from pathlib import Path
from urllib.error import URLError


MODULE = Path(__file__).parents[1] / "scripts" / "api_football_adapter.py"
spec = importlib.util.spec_from_file_location("api_football_adapter_retry", MODULE)
adapter = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(adapter)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"response": [{"ok": true}]}'


def test_get_retries_transient_network_error(monkeypatch):
    calls = {"n": 0}

    def flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise URLError("temporary TLS failure")
        return _Response()

    monkeypatch.setattr(adapter.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(adapter.time, "sleep", lambda *_args: None)
    assert adapter.get("/fixtures", {}) == {"response": [{"ok": True}]}
    assert calls["n"] == 3


def test_get_does_not_retry_non_transient_http_error(monkeypatch):
    from urllib.error import HTTPError

    calls = {"n": 0}

    def fail(*_args, **_kwargs):
        calls["n"] += 1
        raise HTTPError("https://example.invalid", 401, "unauthorized", {}, None)

    monkeypatch.setattr(adapter.urllib.request, "urlopen", fail)
    monkeypatch.setattr(adapter.time, "sleep", lambda *_args: None)
    try:
        adapter.get("/fixtures", {})
    except HTTPError as exc:
        assert exc.code == 401
    else:  # pragma: no cover
        raise AssertionError("expected HTTPError")
    assert calls["n"] == 1

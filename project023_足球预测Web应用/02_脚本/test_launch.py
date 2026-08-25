from __future__ import annotations

import json
import sys
import socket
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import launch
import workbench_runtime


class _Response:
    def __init__(self, body: str, status: int = 200):
        self._body = body.encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_quant_runtime_always_resolves_to_primary_workspace():
    """A B3 checkout may own the UI, but must not own the production model."""
    expected = Path(r"F:\HM足球比赛预测")

    assert workbench_runtime.PRIMARY_WORKSPACE_ROOT == expected
    assert workbench_runtime.FUSION_SCRIPTS == (
        expected / "project018_技能工作区整合" / "02_脚本" /
        "skill" / "football-quant-fusion" / "scripts"
    )


def test_main_skips_occupied_b3_incompatible_server_and_starts_next_free_port(monkeypatch):
    """Deleting the UI-contract identity check must reopen the wrong service on 8766."""
    opened = []
    run_ports = []

    def fake_urlopen(url, timeout=0):
        assert timeout > 0
        if url == "http://127.0.0.1:8766/api/health":
            return _Response('{"ok": true}')
        if url == "http://127.0.0.1:8766/api/ui-contract":
            raise URLError("old service has no B3 contract")
        raise AssertionError(f"unexpected probe: {url}")

    class FakeSocket:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, address):
            if address[1] == 8766:
                raise OSError("occupied by old service")
            assert address == ("127.0.0.1", 8767)

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(launch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(socket, "socket", FakeSocket)
    monkeypatch.setattr(launch.threading, "Thread", FakeThread)
    monkeypatch.setattr(launch.webbrowser, "open", opened.append)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(
        run=lambda _app, *, host, port, log_level: run_ports.append((host, port, log_level)),
    ))

    launch.main()

    assert opened == []
    assert run_ports == [("127.0.0.1", 8767, "info")]


def test_existing_workbench_rejects_foreign_b3_build_identity(monkeypatch):
    """A generic B3 marker must not make another checkout reusable."""
    responses = {
        "/api/health": '{"ok": true}',
        "/api/ui-contract": json.dumps({
            "version": "b3",
            "build_identity": "b3:foreign-worktree",
            "process_id": 4321,
        }),
        "/": '<div class="app-shell"></div><script type="module" src="/js/app.js"></script>',
    }

    def fake_urlopen(url, timeout=0):
        path = url.removeprefix("http://127.0.0.1:8766")
        return _Response(responses[path])

    monkeypatch.setattr(launch.urllib.request, "urlopen", fake_urlopen)

    assert launch._existing_workbench("http://127.0.0.1:8766") is False


def test_runtime_state_is_atomic_and_safe_stop_refuses_identity_mismatch(tmp_path, monkeypatch):
    """The recorded PID is never terminated until PID, port, and build all agree."""
    state_path = tmp_path / "runtime" / "workbench.json"
    writer = getattr(launch, "write_runtime_state", None)
    stopper = getattr(launch, "stop_recorded_workbench", None)
    assert callable(writer), "launch.py must atomically persist runtime ownership"
    assert callable(stopper), "launch.py must expose identity-checked safe stop"

    writer({
        "pid": 2468,
        "host": "127.0.0.1",
        "port": 8766,
        "url": "http://127.0.0.1:8766",
        "identity": launch.BUILD_IDENTITY,
    }, path=state_path)
    assert json.loads(state_path.read_text(encoding="utf-8"))["port"] == 8766
    assert list(state_path.parent.glob("*.tmp")) == []

    killed = []
    monkeypatch.setattr(launch, "RUNTIME_STATE", state_path)
    monkeypatch.setattr(launch, "_terminate_process", killed.append, raising=False)
    monkeypatch.setattr(launch, "_read", lambda url, timeout=0.8: (
        200,
        json.dumps({
            "version": "b3",
            "build_identity": "b3:foreign-worktree",
            "process_id": 2468,
        }),
    ))

    result = stopper()

    assert result["stopped"] is False
    assert result["reason"] == "identity_mismatch"
    assert killed == []
    assert state_path.exists()


def test_reuse_requires_live_process_id_to_match_atomic_runtime_state(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime" / "workbench.json"
    launch.write_runtime_state({
        "pid": 2468,
        "host": "127.0.0.1",
        "port": 8766,
        "url": "http://127.0.0.1:8766",
        "identity": launch.BUILD_IDENTITY,
    }, path=state_path)
    monkeypatch.setattr(launch, "RUNTIME_STATE", state_path)
    monkeypatch.setattr(launch, "_read", lambda url, timeout=0.8: (
        200,
        json.dumps({
            "version": "b3",
            "build_identity": launch.BUILD_IDENTITY,
            "process_id": 9999,
        }),
    ))

    assert launch._runtime_matches("http://127.0.0.1:8766", 8766) is False


def test_select_launch_target_reuses_recorded_dynamic_port_before_searching(tmp_path, monkeypatch):
    state_path = tmp_path / "workbench.json"
    launch.write_runtime_state({
        "pid": 2468, "host": "127.0.0.1", "port": 8767,
        "url": "http://127.0.0.1:8767", "identity": launch.BUILD_IDENTITY,
    }, path=state_path)
    monkeypatch.setattr(launch, "RUNTIME_STATE", state_path)
    monkeypatch.setattr(launch, "_runtime_matches", lambda url, port: port == 8767)
    monkeypatch.setattr(launch, "_existing_workbench", lambda url: url.endswith(":8767"))
    monkeypatch.setattr(launch, "_port_is_free", lambda host, port: port == 8766)

    assert launch.select_launch_target() == ("http://127.0.0.1:8767", 8767, True)

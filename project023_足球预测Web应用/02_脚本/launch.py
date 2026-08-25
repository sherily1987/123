#!/usr/bin/env python3
"""手动启动工作台：起来后再开浏览器；关掉本窗口即停止。"""
from __future__ import annotations

import json
import os
import signal
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

from workbench_runtime import BUILD_IDENTITY

HOST = "127.0.0.1"
PORT = 8766
URL = f"http://{HOST}:{PORT}"
PORT_ATTEMPTS = 20
RUNTIME_STATE = Path(__file__).resolve().parent / "data" / "runtime" / "workbench.json"


def _read(url: str, *, timeout: float = 0.8) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8")


def _existing_workbench(url: str = URL) -> bool:
    """Return true only for the B3 API contract and B3 application shell."""
    try:
        health_status, health_text = _read(f"{url}/api/health")
        contract_status, contract_text = _read(f"{url}/api/ui-contract")
        if health_status != 200 or contract_status != 200:
            return False
        health = json.loads(health_text)
        contract = json.loads(contract_text)
        if (health.get("ok") is not True
                or contract.get("version") != "b3"
                or contract.get("build_identity") != BUILD_IDENTITY
                or not isinstance(contract.get("process_id"), int)):
            return False
        shell_status, shell = _read(f"{url}/")
        return (
            shell_status == 200
            and 'class="app-shell"' in shell
            and 'src="/js/app.js"' in shell
        )
    except Exception:
        return False


def write_runtime_state(payload: dict, *, path: Path | None = None) -> Path:
    """Atomically record the exact process that owns this workbench build."""
    required = {"pid", "host", "port", "url", "identity"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError("runtime state missing ownership fields")
    path = RUNTIME_STATE if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp", delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        return path
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_runtime_state(path: Path | None = None) -> dict | None:
    path = RUNTIME_STATE if path is None else Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _runtime_matches(url: str, port: int) -> bool:
    state = read_runtime_state()
    if not state:
        return False
    recorded = (
        state.get("identity") == BUILD_IDENTITY
        and state.get("host") == HOST
        and state.get("port") == port
        and state.get("url") == url
        and isinstance(state.get("pid"), int)
        and state["pid"] > 0
    )
    if not recorded:
        return False
    try:
        status, body = _read(f"{url}/api/ui-contract")
        contract = json.loads(body)
    except Exception:
        return False
    return (
        status == 200
        and contract.get("build_identity") == BUILD_IDENTITY
        and contract.get("process_id") == state["pid"]
    )


def _remove_runtime_state_if_owned(pid: int, path: Path | None = None) -> None:
    path = RUNTIME_STATE if path is None else Path(path)
    state = read_runtime_state(path)
    if state and state.get("identity") == BUILD_IDENTITY and state.get("pid") == pid:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _terminate_process(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def stop_recorded_workbench() -> dict:
    """Stop only the process verified by runtime state and the live contract."""
    state = read_runtime_state()
    if not state:
        return {"stopped": False, "reason": "missing_state"}
    pid = state.get("pid")
    port = state.get("port")
    if (state.get("identity") != BUILD_IDENTITY or state.get("host") != HOST
            or not isinstance(pid, int) or pid <= 0
            or not isinstance(port, int) or not 1 <= port <= 65535):
        return {"stopped": False, "reason": "identity_mismatch"}
    url = f"http://{HOST}:{port}"
    if state.get("url") != url:
        return {"stopped": False, "reason": "identity_mismatch"}
    try:
        status, body = _read(f"{url}/api/ui-contract")
        contract = json.loads(body)
    except Exception:
        return {"stopped": False, "reason": "endpoint_unavailable"}
    if status != 200 or contract.get("build_identity") != BUILD_IDENTITY:
        return {"stopped": False, "reason": "identity_mismatch"}
    if contract.get("process_id") != pid:
        return {"stopped": False, "reason": "process_mismatch"}
    try:
        _terminate_process(pid)
    except (OSError, ProcessLookupError) as exc:
        return {"stopped": False, "reason": "terminate_failed", "message": str(exc)}
    _remove_runtime_state_if_owned(pid)
    return {"stopped": True, "reason": "stopped", "pid": pid, "port": port, "url": url}


def _port_is_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return True
    except OSError:
        return False


def select_launch_target(host: str = HOST, start_port: int = PORT) -> tuple[str, int, bool]:
    """Choose a matching B3 service or the first free local port."""
    state = read_runtime_state()
    if (state and state.get("host") == host and state.get("identity") == BUILD_IDENTITY
            and isinstance(state.get("port"), int)):
        recorded_port = state["port"]
        recorded_url = f"http://{host}:{recorded_port}"
        if (state.get("url") == recorded_url and _existing_workbench(recorded_url)
                and _runtime_matches(recorded_url, recorded_port)):
            return recorded_url, recorded_port, True
    for port in range(start_port, start_port + PORT_ATTEMPTS):
        url = f"http://{host}:{port}"
        if _port_is_free(host, port):
            return url, port, False
        if _existing_workbench(url) and _runtime_matches(url, port):
            return url, port, True
    raise RuntimeError(
        f"{host}:{start_port}-{start_port + PORT_ATTEMPTS - 1} 均被其他服务占用，未找到 B3 工作台或空闲端口。"
    )


def wait_and_open(url: str) -> None:
    for _ in range(40):
        if _existing_workbench(url):
            webbrowser.open(url)
            print(f"已打开 {url}  关掉本窗口即停止。", flush=True)
            return
        time.sleep(0.25)
    print("服务 10 秒内没有起来，请看上面的报错。", flush=True)


def main(argv: list[str] | None = None) -> None:
    argv = list(argv or [])
    if argv == ["--stop"]:
        result = stop_recorded_workbench()
        if result["stopped"]:
            print(f"已安全停止 PID {result['pid']}（{result['url']}）。", flush=True)
            return
        raise RuntimeError(f"拒绝停止：{result['reason']}。请关闭原启动窗口。")
    if argv == ["--status"]:
        state = read_runtime_state()
        print(json.dumps(state or {"status": "not_running"}, ensure_ascii=False), flush=True)
        return
    if argv:
        raise ValueError(f"不支持的参数: {' '.join(argv)}")
    url, port, reuse = select_launch_target()
    if reuse:
        print(f"工作台已在运行：{url}，已确认 B3 身份后复用。", flush=True)
        webbrowser.open(url)
        return
    print(f"工作台启动中… {url}", flush=True)
    pid = os.getpid()
    write_runtime_state({
        "pid": pid,
        "host": HOST,
        "port": port,
        "url": url,
        "identity": BUILD_IDENTITY,
        "started_at": datetime.now().astimezone().isoformat(),
    })
    threading.Thread(target=wait_and_open, args=(url,), daemon=True).start()
    import uvicorn
    import app as web
    try:
        uvicorn.run(web.app, host=HOST, port=port, log_level="info")
    finally:
        _remove_runtime_state_if_owned(pid)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as exc:
        print(f"启动失败: {type(exc).__name__}: {exc}", flush=True)
        sys.exit(1)

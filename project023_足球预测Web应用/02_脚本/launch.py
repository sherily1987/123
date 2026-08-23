#!/usr/bin/env python3
"""手动启动工作台：起来后再开浏览器；关掉本窗口即停止。"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
import webbrowser

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def _existing_workbench() -> bool:
    """Return true only when the port already serves this workbench."""
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=0.8) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("ok") is True
    except Exception:
        return False


def wait_and_open() -> None:
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{URL}/api/health", timeout=1)
            webbrowser.open(URL)
            print(f"已打开 {URL}  关掉本窗口即停止。", flush=True)
            return
        except Exception:
            time.sleep(0.25)
    print("服务 10 秒内没有起来，请看上面的报错。", flush=True)


def main() -> None:
    if _existing_workbench():
        print(f"工作台已在运行：{URL}，复用现有服务。", flush=True)
        webbrowser.open(URL)
        return
    print(f"工作台启动中… {URL}", flush=True)
    threading.Thread(target=wait_and_open, daemon=True).start()
    import uvicorn
    import app as web
    uvicorn.run(web.app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"启动失败: {type(exc).__name__}: {exc}", flush=True)
        sys.exit(1)

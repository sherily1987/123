from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "run_llm_4markets.py"


def test_cli_accepts_required_paths_and_writes_empty_outputs_without_api_calls(tmp_path):
    raw = tmp_path / "raw.json"
    out_json = tmp_path / "output.json"
    out_txt = tmp_path / "output.txt"
    raw.write_text(json.dumps({"matches": []}), encoding="utf-8")

    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = "http://must-be-cleared.invalid:9999"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--raw", str(raw), "--out-json", str(out_json), "--out-txt", str(out_txt)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(out_json.read_text(encoding="utf-8")) == []
    assert "models=['zhipu/glm-4-flash', 'qwen/qwen-flash', 'deepseek/deepseek-chat']" in out_txt.read_text(encoding="utf-8")


def test_runtime_proxy_cleanup_removes_only_required_proxy_names(monkeypatch):
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        import run_llm_4markets
    finally:
        sys.path.pop(0)

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(key, "http://proxy.invalid")
    monkeypatch.setenv("NO_PROXY", "localhost")

    run_llm_4markets.clear_runtime_proxies()

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert key not in os.environ
    assert os.environ["NO_PROXY"] == "localhost"

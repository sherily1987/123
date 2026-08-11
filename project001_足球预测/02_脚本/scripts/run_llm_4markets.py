"""Production entry point for the validated domestic three-model, four-market run.

The prediction implementation remains in the verified 20260808 runner; this thin
entry point owns the canonical command-line contract and runtime proxy cleanup.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_RUNNER = PROJECT_ROOT / "05_交付" / "今日推荐_双轨4玩法_20260808" / "run_llm_4markets.py"
PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def clear_runtime_proxies() -> None:
    """Remove proxy variables incompatible with the domestic model providers."""
    for name in PROXY_VARIABLES:
        os.environ.pop(name, None)


def _load_validated_runner():
    spec = importlib.util.spec_from_file_location("_validated_llm_4markets", LEGACY_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load validated runner: {LEGACY_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _requested_paths() -> tuple[Path, Path, Path]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-txt", required=True)
    args, _ = parser.parse_known_args()
    return Path(args.raw), Path(args.out_json), Path(args.out_txt)


def main() -> None:
    raw_path, out_json, out_txt = _requested_paths()
    clear_runtime_proxies()
    runner = _load_validated_runner()
    runner.load_user_env_keys()
    clear_runtime_proxies()
    runner.main()

    # The validated runner streams files per match; preserve the CLI contract
    # for a valid zero-match input without invoking any model provider.
    raw = json.loads(raw_path.read_text(encoding="utf-8-sig"))
    if not (raw.get("matches") or []):
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text("[]", encoding="utf-8")
        out_txt.write_text(
            f"LLM 4玩法 models={runner.MODELS} n=0\\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()

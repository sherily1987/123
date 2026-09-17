#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the football prediction / quant-fusion repo.
# Safe to run repeatedly: it only refreshes the virtualenv and Python deps.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The stock image ships python3 but not the venv module; install it once.
if ! python3 -c "import venv" >/dev/null 2>&1; then
  echo "[install] python3-venv missing; installing via apt"
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-pip
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[install] creating virtualenv at .venv"
  python3 -m venv .venv
fi

echo "[install] upgrading pip"
./.venv/bin/python -m pip install --quiet --upgrade pip

echo "[install] installing Python dependencies"
./.venv/bin/python -m pip install --quiet -r .cursor/requirements.txt

echo "[install] done. Python: $(./.venv/bin/python --version)"

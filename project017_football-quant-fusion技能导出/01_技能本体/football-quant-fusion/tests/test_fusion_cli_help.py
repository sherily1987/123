import subprocess
import sys
from pathlib import Path


def test_top_level_help_lists_supported_commands():
    script = Path(__file__).parents[1] / "scripts" / "fusion_cli.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"], text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0
    assert "record" in completed.stdout
    assert "backtest" in completed.stdout

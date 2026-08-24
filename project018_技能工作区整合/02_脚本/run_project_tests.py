"""Run project test suites in isolated working directories.

The repository contains several legacy modules named ``predict.py``. Running
all test files in one pytest collection lets those names collide in
``sys.modules``. This runner keeps each suite's local import context isolated.
"""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


@dataclass(frozen=True)
class TestCommand:
    cwd: Path
    args: list[str]


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_commands(root: Path) -> list[TestCommand]:
    suites = [
        root / "project018_技能工作区整合" / "02_脚本" / "llm" / "football-llm-predictor",
        root / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts",
        root / "project018_技能工作区整合" / "02_脚本" / "skill" / "football-quant-fusion" / "tests",
        root / "project021_五大联赛APIFootball训练" / "02_脚本",
        root / "project023_足球预测Web应用" / "02_脚本",
    ]
    return [
        TestCommand(cwd=suite, args=[sys.executable, "-m", "pytest", ".", "-q", "--disable-warnings"])
        for suite in suites
        if suite.exists()
    ]


def main() -> int:
    root = repository_root()
    commands = build_commands(root)
    if not commands:
        print("没有找到可运行的测试套件", file=sys.stderr)
        return 2
    for index, command in enumerate(commands, 1):
        print(f"[{index}/{len(commands)}] pytest: {command.cwd}", flush=True)
        result = subprocess.run(command.args, cwd=command.cwd, check=False)
        if result.returncode:
            print(f"测试套件失败，退出码={result.returncode}: {command.cwd}", file=sys.stderr)
            return result.returncode
    print(f"全部 {len(commands)} 个测试套件通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

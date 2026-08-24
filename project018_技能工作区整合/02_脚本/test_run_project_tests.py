import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_project_tests.py")


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_project_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_commands_isolates_same_named_modules_by_working_directory():
    runner = _load_runner()

    commands = runner.build_commands(Path("F:/HM足球比赛预测"))

    assert commands
    assert all(item.cwd.exists() for item in commands)
    assert all(item.args[:3] == [runner.sys.executable, "-m", "pytest"] for item in commands)
    assert any("football-llm-predictor" in str(item.cwd) for item in commands)


def test_repository_root_is_workspace_root():
    runner = _load_runner()
    assert runner.repository_root() == Path(__file__).resolve().parents[2]

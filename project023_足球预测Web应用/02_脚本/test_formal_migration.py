from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


def test_windows_batch_entrypoints_use_crlf():
    entrypoints = [
        PROJECT_DIR / "启动B3工作台.bat",
        PROJECT_DIR / "启动工作台.bat",
        PROJECT_DIR / "02_脚本" / "start.bat",
        PROJECT_DIR / "02_脚本" / "stop.bat",
    ]
    for path in entrypoints:
        payload = path.read_bytes()
        assert b"\r\n" in payload, f"Windows cmd requires CRLF line endings: {path}"
        assert b"\n" not in payload.replace(b"\r\n", b""), (
            f"bare LF line ending breaks Windows cmd parsing: {path}"
        )


def test_formal_runtime_has_no_worktree_dependency():
    checked = [
        PROJECT_DIR / "启动B3工作台.bat",
        PROJECT_DIR / "启动工作台.bat",
        PROJECT_DIR / "02_脚本" / "launch.py",
    ]
    for path in checked:
        assert path.exists(), f"missing formal runtime file: {path}"
        assert ".worktrees" not in path.read_text(encoding="utf-8", errors="ignore")

    import workbench_runtime

    assert workbench_runtime.PROJECT_DIR == PROJECT_DIR.resolve()
    assert ".worktrees" not in str(workbench_runtime.PROJECT_DIR)


def test_formal_launcher_delegates_to_b3_entry():
    legacy = (PROJECT_DIR / "启动工作台.bat").read_text(encoding="utf-8")
    assert "启动B3工作台.bat" in legacy
    assert "02_脚本\\start.bat" not in legacy


def test_formal_launcher_prefers_8766():
    import launch

    assert launch.PORT == 8766


def test_quant_runtime_resolves_to_primary_workspace():
    import workbench_runtime

    expected = Path(__file__).resolve().parents[2]
    assert workbench_runtime.PRIMARY_WORKSPACE_ROOT == expected
    assert workbench_runtime.FUSION_SCRIPTS == (
        expected
        / "project018_技能工作区整合"
        / "02_脚本"
        / "skill"
        / "football-quant-fusion"
        / "scripts"
    )

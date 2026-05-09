import subprocess
from pathlib import Path

from aethr.context import collect_context


def test_collect_context_reads_file_and_missing_file(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("hello docs\n", encoding="utf-8")

    context = collect_context(["file:README.md", "file:MISSING.md"], root=tmp_path)

    assert "--- file:README.md ---" in context
    assert "hello docs" in context
    assert "[missing file:" in context


def test_collect_context_reads_glob_and_notes_unreadable_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (src / "data.py").write_bytes(b"\xff\xfe\x00")

    context = collect_context(["glob:src/**/*.py"], root=tmp_path)

    assert "--- src/app.py ---" in context
    assert "print('hi')" in context
    assert "[skipped non-UTF-8 file:" in context


def test_collect_context_git_diff_placeholder_outside_repo(tmp_path: Path) -> None:
    context = collect_context(["git_diff"], root=tmp_path)

    assert "--- git_diff ---" in context
    assert "[git diff unavailable:" in context


def test_collect_context_git_diff_includes_worktree_diff(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    tracked.write_text("new\n", encoding="utf-8")

    context = collect_context(["git_diff"], root=tmp_path)

    assert "--- git_diff ---" in context
    assert "-old" in context
    assert "+new" in context

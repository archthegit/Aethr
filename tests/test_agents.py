from aethr.agents import OpenCodeAgentClient


def test_opencode_command_keeps_permissions_by_default() -> None:
    client = OpenCodeAgentClient("openai:gpt-5.3-codex", working_directory="/tmp/project")

    command = client._command("make the change")

    assert "--dangerously-skip-permissions" not in command
    assert command[-1] == "make the change"


def test_opencode_command_can_opt_into_unsafe_permissions() -> None:
    client = OpenCodeAgentClient(
        "openai:gpt-5.3-codex",
        working_directory="/tmp/project",
        unsafe_permissions=True,
    )

    command = client._command("make the change")

    assert "--dangerously-skip-permissions" in command
    assert command[-1] == "make the change"


def test_opencode_evidence_includes_changed_files_and_diff(monkeypatch) -> None:
    client = OpenCodeAgentClient("openai:gpt-5.3-codex", working_directory="/tmp/project")

    def fake_run(*args, **kwargs):
        command = args[0]
        if command[0:3] == ["git", "-C", "/tmp/project"] and "status" in command:
            return type("Result", (), {"stdout": " M file.py\n?? new_file.py\n"})()
        if "--stat" in command:
            return type("Result", (), {"stdout": " file.py | 2 ++\n new_file.py | 2 ++\n 2 files changed"})()
        return type("Result", (), {"stdout": "diff --git a/file.py b/file.py\n+print('hi')\n"})()

    monkeypatch.setattr("aethr.agents.subprocess.run", fake_run)
    new_file = client.cwd / "new_file.py"
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text("print('new')\n", encoding="utf-8")

    artifacts = client._capture_worktree_artifacts()

    assert artifacts.changed_files == ["file.py", "new_file.py"]
    assert "file.py | 2 ++" in artifacts.diff_stat
    assert "print('hi')" in artifacts.git_diff
    assert "new file mode 100644" in artifacts.git_diff
    assert "print('new')" in artifacts.git_diff

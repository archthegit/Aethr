from pathlib import Path

from typer.testing import CliRunner

from aethr.auth import status
from aethr.cli import app


def test_auth_login_writes_project_env(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["auth", "login", "openai", "--key", "sk-test"])

    assert result.exit_code == 0
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY='sk-test'" in env_text or 'OPENAI_API_KEY="sk-test"' in env_text
    assert "Stored" in result.output


def test_auth_status_reports_present_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=anthropic-test\n", encoding="utf-8")

    result = status(tmp_path / ".env")

    assert result["anthropic"] == "set"
    assert result["openai"] == "missing"

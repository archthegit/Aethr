import os
from pathlib import Path

from aethr.env import load_project_dotenv


def test_load_project_dotenv_loads_nearest_file(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    nested = project_root / "src" / "pkg"
    nested.mkdir(parents=True)
    (project_root / ".env").write_text("AETHR_MODEL=openai:gpt-4o-mini\n", encoding="utf-8")

    monkeypatch.chdir(nested)
    monkeypatch.delenv("AETHR_MODEL", raising=False)

    loaded = load_project_dotenv()

    assert loaded == str(project_root / ".env")
    assert (project_root / ".env").samefile(loaded)
    assert os.getenv("AETHR_MODEL") == "openai:gpt-4o-mini"


def test_load_project_dotenv_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("AETHR_MODEL=openai:gpt-4o-mini\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AETHR_MODEL", "anthropic:claude-sonnet-4")

    load_project_dotenv()

    assert os.getenv("AETHR_MODEL") == "anthropic:claude-sonnet-4"


def test_load_project_dotenv_returns_none_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    loaded = load_project_dotenv()

    assert loaded is None


def test_load_project_dotenv_handles_malformed_entries(tmp_path: Path, monkeypatch) -> None:
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "NOT A VALID LINE\nAETHR_MODEL=anthropic:claude-sonnet-4\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AETHR_MODEL", raising=False)

    loaded = load_project_dotenv()

    assert loaded == str(dotenv_file)
    assert os.getenv("AETHR_MODEL") == "anthropic:claude-sonnet-4"


def test_load_project_dotenv_returns_none_for_invalid_dotenv_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aethr.env.find_dotenv", lambda usecwd=True: str(tmp_path / "missing.env"))

    loaded = load_project_dotenv()

    assert loaded is None

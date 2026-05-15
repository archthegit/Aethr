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


def test_load_project_dotenv_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("AETHR_MODEL=openai:gpt-4o-mini\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AETHR_MODEL", "anthropic:claude-sonnet-4")

    load_project_dotenv()

    assert os.getenv("AETHR_MODEL") == "anthropic:claude-sonnet-4"

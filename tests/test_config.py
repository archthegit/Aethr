from pathlib import Path

import pytest

from aethr.config import ConfigError, load_workflow_config


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_workflow_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: typo-test
roles:
  worker: Do the work.
models:
  worker: openai:gpt-5.5
steps:
  - id: work
    role: worker
review_looop:
  enabled: true
""",
    )

    with pytest.raises(ConfigError, match="review_looop"):
        load_workflow_config(config_path)


def test_load_workflow_config_rejects_step_with_undefined_role(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: missing-role
roles:
  planner: Plan the work.
models:
  planner: openai:gpt-5.5
steps:
  - id: review
    role: reviewer
""",
    )

    with pytest.raises(ConfigError, match="undefined roles: reviewer"):
        load_workflow_config(config_path)


def test_load_workflow_config_rejects_model_for_undefined_role(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: bad-model-route
roles:
  worker: Do the work.
models:
  reviewer: openai:gpt-5.5
steps:
  - id: work
    role: worker
""",
    )

    with pytest.raises(ConfigError, match="models reference undefined roles: reviewer"):
        load_workflow_config(config_path)


def test_load_workflow_config_accepts_step_context(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: context-test
roles:
  reviewer: Review the work.
models:
  reviewer: openai:gpt-5.5
steps:
  - id: review
    role: reviewer
    context:
      - git_diff
      - file:README.md
      - glob:src/**/*.py
""",
    )

    config = load_workflow_config(config_path)

    assert config.steps[0].context == ["git_diff", "file:README.md", "glob:src/**/*.py"]


def test_load_workflow_config_accepts_agent_backend(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: backend-test
roles:
  implementer: Implement the work.
models:
  implementer: openai:gpt-5.3-codex
steps:
  - id: implement
    role: implementer
    backend: opencode
""",
    )

    config = load_workflow_config(config_path)

    assert config.steps[0].backend == "opencode"

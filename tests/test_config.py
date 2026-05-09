from pathlib import Path

import pytest

from relay.config import ConfigError, load_workflow_config


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_workflow_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".relay.yaml",
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
        tmp_path / ".relay.yaml",
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
        tmp_path / ".relay.yaml",
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

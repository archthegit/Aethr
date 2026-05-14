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


def test_load_workflow_config_accepts_unsafe_permissions_flag(tmp_path: Path) -> None:
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
    unsafe_permissions: true
""",
    )

    config = load_workflow_config(config_path)

    assert config.steps[0].unsafe_permissions is True


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


def test_load_workflow_config_accepts_history_visibility(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: visibility-test
roles:
  reviewer: Review the work.
models:
  reviewer: openai:gpt-4o-mini
steps:
  - id: review
    role: reviewer
    history_visibility: latest
""",
    )

    config = load_workflow_config(config_path)

    assert config.steps[0].history_visibility == "latest"


def test_load_workflow_config_accepts_repeat_block(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: loop-test
roles:
  implementer: Implement the work.
  reviewer: Review the work.
models:
  implementer: openai:gpt-5.3-codex
  reviewer: openai:gpt-4o-mini
steps:
  - id: implement
    role: implementer
    backend: opencode
  - id: review
    role: reviewer
    repeat:
      back_to: implement
      until_review_pass: true
      max_iterations: 3
""",
    )

    config = load_workflow_config(config_path)

    repeat = config.steps[1].repeat
    assert repeat is not None
    assert repeat.back_to == "implement"
    assert repeat.until_review_pass is True
    assert repeat.max_iterations == 3


def test_load_workflow_config_rejects_repeat_from_future_step(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / ".aethr.yaml",
        """
workflow: loop-test
roles:
  implementer: Implement the work.
  reviewer: Review the work.
models:
  implementer: openai:gpt-5.3-codex
  reviewer: openai:gpt-4o-mini
steps:
  - id: review
    role: reviewer
    repeat:
      back_to: implement
      until_review_pass: true
      max_iterations: 3
  - id: implement
    role: implementer
    backend: opencode
""",
    )

    with pytest.raises(ConfigError, match="must repeat from an earlier step"):
        load_workflow_config(config_path)

from pathlib import Path

import pytest

from relay.workflow import WorkflowTemplateError, available_workflows, init_workflow


def test_available_workflows_includes_core_presets() -> None:
    assert {
        "plan-implement-review",
        "review-existing-diff",
        "test-failure-debug",
        "docs-update",
        "custom",
    }.issubset(set(available_workflows()))


def test_init_workflow_refuses_overwrite_without_force(tmp_path: Path) -> None:
    destination = tmp_path / ".relay.yaml"
    destination.write_text("existing: true\n", encoding="utf-8")

    with pytest.raises(WorkflowTemplateError, match="already exists"):
        init_workflow("custom", destination=destination)

    assert destination.read_text(encoding="utf-8") == "existing: true\n"


def test_init_workflow_overwrites_with_force(tmp_path: Path) -> None:
    destination = tmp_path / ".relay.yaml"
    destination.write_text("existing: true\n", encoding="utf-8")

    init_workflow("custom", destination=destination, force=True)

    assert "workflow: custom" in destination.read_text(encoding="utf-8")

from pathlib import Path

import pytest

from aethr.workflow import WorkflowTemplateError, available_workflows, init_workflow


def test_available_workflows_includes_core_presets() -> None:
    assert {
        "add-tests",
        "plan-implement-review",
        "review-existing-diff",
        "debug-failing-test",
        "docs-sync",
        "custom",
    }.issubset(set(available_workflows()))


def test_init_workflow_refuses_overwrite_without_force(tmp_path: Path) -> None:
    destination = tmp_path / ".aethr.yaml"
    destination.write_text("existing: true\n", encoding="utf-8")

    with pytest.raises(WorkflowTemplateError, match="already exists"):
        init_workflow("custom", destination=destination)

    assert destination.read_text(encoding="utf-8") == "existing: true\n"


def test_init_workflow_overwrites_with_force(tmp_path: Path) -> None:
    destination = tmp_path / ".aethr.yaml"
    destination.write_text("existing: true\n", encoding="utf-8")

    init_workflow("custom", destination=destination, force=True)

    assert "workflow: custom" in destination.read_text(encoding="utf-8")


def test_context_presets_declare_explicit_context(tmp_path: Path) -> None:
    review_config = tmp_path / "review.yaml"
    docs_config = tmp_path / "docs.yaml"
    tests_config = tmp_path / "tests.yaml"
    debug_config = tmp_path / "debug.yaml"

    init_workflow("review-existing-diff", destination=review_config)
    init_workflow("docs-sync", destination=docs_config)
    init_workflow("add-tests", destination=tests_config)
    init_workflow("debug-failing-test", destination=debug_config)

    review_text = review_config.read_text(encoding="utf-8")
    assert "context:\n      - git_diff" in review_text
    assert "anthropic:" not in review_text
    docs_text = docs_config.read_text(encoding="utf-8")
    assert "- git_diff" in docs_text
    assert "- file:README.md" in docs_text
    assert "- glob:docs/**/*.md" in docs_text
    tests_text = tests_config.read_text(encoding="utf-8")
    assert "- glob:src/**/*.py" in tests_text
    assert "- glob:tests/**/*.py" in tests_text
    assert "anthropic:" not in tests_text
    debug_text = debug_config.read_text(encoding="utf-8")
    assert "- git_diff" in debug_text
    assert "- glob:src/**/*.py" in debug_text
    assert "- glob:tests/**/*.py" in debug_text
    assert "anthropic:" not in debug_text

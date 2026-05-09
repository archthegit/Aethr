"""Built-in workflow template management."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from relay.config import CONFIG_FILE


WORKFLOW_PACKAGE = "relay.workflows"


class WorkflowTemplateError(Exception):
    """Raised when a workflow template cannot be initialized."""


def available_workflows() -> list[str]:
    """Return built-in workflow preset names."""

    root = resources.files(WORKFLOW_PACKAGE)
    names = []
    for item in root.iterdir():
        if item.name.endswith(".yaml"):
            names.append(item.name.removesuffix(".yaml").replace("_", "-"))
    return sorted(names)


def workflow_template_text(name: str) -> str:
    """Return a built-in workflow template by preset name."""

    filename = f"{name.replace('-', '_')}.yaml"
    root = resources.files(WORKFLOW_PACKAGE)
    template = root / filename
    if not template.is_file():
        choices = ", ".join(available_workflows())
        raise WorkflowTemplateError(f"Unknown workflow '{name}'. Available workflows: {choices}")
    return template.read_text(encoding="utf-8")


def init_workflow(name: str, destination: Path | str = CONFIG_FILE, force: bool = False) -> Path:
    """Copy a built-in workflow template to the project config path."""

    path = Path(destination)
    if path.exists() and not force:
        raise WorkflowTemplateError(f"{path} already exists. Pass --force to overwrite it.")

    path.write_text(workflow_template_text(name), encoding="utf-8")
    return path

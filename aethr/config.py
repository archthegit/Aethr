"""Workflow configuration schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


CONFIG_FILE = ".aethr.yaml"


class ConfigError(Exception):
    """Raised when workflow configuration cannot be loaded."""


class WorkflowStep(BaseModel):
    """One sequential step in an Aethr workflow."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    backend: Literal["model", "opencode"] = "model"
    context: list[str] = Field(default_factory=list)


class WorkflowConfig(BaseModel):
    """A YAML-defined Aethr workflow."""

    model_config = ConfigDict(extra="forbid")

    workflow: str = Field(min_length=1)
    roles: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_roles(self) -> "WorkflowConfig":
        """Ensure configured steps and model routes reference known roles."""

        known_roles = set(self.roles)
        step_roles = {step.role for step in self.steps}
        missing_step_roles = sorted(step_roles - known_roles)
        if missing_step_roles:
            joined = ", ".join(missing_step_roles)
            raise ValueError(f"steps reference undefined roles: {joined}")

        unknown_model_roles = sorted(set(self.models) - known_roles)
        if unknown_model_roles:
            joined = ", ".join(unknown_model_roles)
            raise ValueError(f"models reference undefined roles: {joined}")

        return self


def load_workflow_config(path: Path | str = CONFIG_FILE) -> WorkflowConfig:
    """Load and validate an Aethr workflow config file."""

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Workflow config not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if raw is None:
        raise ConfigError(f"Workflow config is empty: {config_path}")
    if not isinstance(raw, dict):
        raise ConfigError(f"Workflow config must be a YAML mapping: {config_path}")

    try:
        return WorkflowConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigError(f"Invalid workflow config in {config_path}: {details}") from exc

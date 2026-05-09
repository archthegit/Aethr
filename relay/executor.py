"""Sequential workflow execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from relay.config import WorkflowConfig, WorkflowStep
from relay.context import collect_context
from relay.llm import ModelClient
from relay.prompts import step_prompt


@dataclass(frozen=True)
class StepResult:
    """In-memory result from one workflow step."""

    step_id: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StepPrompt:
    """Exact prompt planned for one workflow step."""

    step_id: str
    prompt: str
    metadata: dict[str, str] = field(default_factory=dict)


StepCallback = Callable[[StepResult], None]


def run_workflow(
    task: str,
    config: WorkflowConfig,
    on_step_result: StepCallback | None = None,
) -> list[StepResult]:
    """Run a configured workflow as a simple in-memory sequence."""

    results: list[StepResult] = []
    for step in config.steps:
        result = run_step(task, step, config, results)
        results.append(result)
        if on_step_result is not None:
            on_step_result(result)

    return results


def build_workflow_prompts(task: str, config: WorkflowConfig) -> list[StepPrompt]:
    """Build exact prompts for each step without calling models."""

    prompts: list[StepPrompt] = []
    previous_results: list[StepResult] = []
    for step in config.steps:
        planned = build_step_prompt(task, step, config, previous_results)
        prompts.append(planned)
        previous_results.append(
            StepResult(step_id=step.id, content=f"[output from {step.id}]", metadata=planned.metadata)
        )
    return prompts


def run_step(
    task: str,
    step: WorkflowStep,
    config: WorkflowConfig,
    previous_results: list[StepResult],
) -> StepResult:
    """Run one workflow step."""

    planned = build_step_prompt(task, step, config, previous_results)
    model = ModelClient(config.models.get(step.role))
    content = model.complete(planned.prompt)
    return StepResult(step_id=step.id, content=content, metadata=planned.metadata)


def build_step_prompt(
    task: str,
    step: WorkflowStep,
    config: WorkflowConfig,
    previous_results: list[StepResult],
) -> StepPrompt:
    """Build one step prompt and metadata."""

    model = ModelClient(config.models.get(step.role))
    previous_context = format_previous_results(previous_results)
    explicit_context = collect_context(step.context)
    prompt = step_prompt(
        task=task,
        step=step,
        previous_context=previous_context,
        explicit_context=explicit_context,
        role_description=config.roles.get(step.role, ""),
    )
    metadata = {
        "role": step.role,
        "model": model.model or "mock",
        "context_sources": str(len(step.context)),
    }
    return StepPrompt(step_id=step.id, prompt=prompt, metadata=metadata)


def format_previous_results(results: list[StepResult]) -> str:
    """Format prior in-memory step outputs for the next prompt."""

    if not results:
        return "No previous step output."
    return "\n\n".join(f"--- {result.step_id} ---\n{result.content.rstrip()}" for result in results)

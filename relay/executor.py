"""Sequential workflow execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from relay.config import WorkflowConfig, WorkflowStep
from relay.llm import ModelClient
from relay.prompts import step_prompt


@dataclass(frozen=True)
class StepResult:
    """In-memory result from one workflow step."""

    step_id: str
    content: str
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

    if config.review_loop.enabled and config.steps:
        review_step = config.steps[-1]
        for iteration in range(2, config.review_loop.max_iterations + 1):
            result = run_step(task, review_step, config, results, iteration=iteration)
            results.append(result)
            if on_step_result is not None:
                on_step_result(result)

    return results


def run_step(
    task: str,
    step: WorkflowStep,
    config: WorkflowConfig,
    previous_results: list[StepResult],
    iteration: int = 1,
) -> StepResult:
    """Run one workflow step."""

    model = ModelClient(config.models.get(step.role))
    context = format_previous_results(previous_results)
    prompt = step_prompt(
        task=task,
        step=step,
        context=context,
        role_description=config.roles.get(step.role, ""),
    )
    content = model.complete(prompt)
    metadata = {"role": step.role, "model": model.model or "mock", "iteration": str(iteration)}
    return StepResult(step_id=step.id, content=content, metadata=metadata)


def format_previous_results(results: list[StepResult]) -> str:
    """Format prior in-memory step outputs for the next prompt."""

    if not results:
        return "No previous step output."
    return "\n\n".join(f"--- {result.step_id} ---\n{result.content.rstrip()}" for result in results)

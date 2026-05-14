"""Sequential workflow execution."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from aethr.config import WorkflowConfig, WorkflowStep
from aethr.agents import OpenCodeAgentClient
from aethr.context import collect_context
from aethr.llm import LLMError, ModelClient, UsageSummary
from aethr.prompts import step_prompt


@dataclass(frozen=True)
class StepResult:
    """In-memory result from one workflow step."""

    step_id: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    usage: UsageSummary | None = None


@dataclass(frozen=True)
class StepPrompt:
    """Exact prompt planned for one workflow step."""

    step_id: str
    prompt: str
    metadata: dict[str, str] = field(default_factory=dict)


class WorkflowStepError(Exception):
    """Raised when a step fails and a resumable checkpoint is available."""

    def __init__(self, step_id: str, completed_results: list[StepResult], cause: Exception) -> None:
        self.step_id = step_id
        self.completed_results = completed_results
        self.cause = cause
        super().__init__(f"Workflow failed at step '{step_id}': {cause}")


StepCallback = Callable[[StepResult], None]
StepChunkCallback = Callable[[str, str], None]
StepStartCallback = Callable[[int, int, StepPrompt], None]


def run_workflow(
    task: str,
    config: WorkflowConfig,
    previous_results: list[StepResult] | None = None,
    on_step_start: StepStartCallback | None = None,
    on_step_chunk: StepChunkCallback | None = None,
    on_step_result: StepCallback | None = None,
) -> list[StepResult]:
    """Run a configured workflow as a simple in-memory sequence."""

    results = list(previous_results or [])
    validate_checkpoint(results, config)

    start_index = len(results)
    for position, step in enumerate(config.steps[start_index:], start=start_index + 1):
        planned = build_step_prompt(task, step, config, results)
        if on_step_start is not None:
            on_step_start(position, len(config.steps), planned)

        try:
            result = run_step(
                task,
                step,
                config,
                results,
                planned=planned,
                on_chunk=on_step_chunk,
            )
        except LLMError as exc:
            raise WorkflowStepError(step.id, results, exc) from exc

        results.append(result)
        if on_step_result is not None:
            on_step_result(result)

    return results


def build_workflow_prompts(task: str, config: WorkflowConfig, previous_results: list[StepResult] | None = None) -> list[StepPrompt]:
    """Build exact prompts for each step without calling models."""

    prompts: list[StepPrompt] = []
    history = list(previous_results or [])
    validate_checkpoint(history, config)

    for step in config.steps[len(history) :]:
        planned = build_step_prompt(task, step, config, history)
        prompts.append(planned)
        history.append(
            StepResult(
                step_id=step.id,
                content=f"[simulated previous output from {step.id}]",
                metadata=planned.metadata,
            )
        )
    return prompts


def run_step(
    task: str,
    step: WorkflowStep,
    config: WorkflowConfig,
    previous_results: list[StepResult],
    planned: StepPrompt | None = None,
    on_chunk: StepChunkCallback | None = None,
) -> StepResult:
    """Run one workflow step."""

    if planned is None:
        planned = build_step_prompt(task, step, config, previous_results)
    chunk_callback = (lambda chunk: on_chunk(step.id, chunk)) if on_chunk is not None else None
    if step.backend == "opencode":
        agent = OpenCodeAgentClient(config.models.get(step.role))
        completion = agent.complete(planned.prompt, on_chunk=chunk_callback)
    else:
        model = ModelClient(config.models.get(step.role))
        completion = model.complete(planned.prompt, on_chunk=chunk_callback)
    return StepResult(step_id=step.id, content=completion.content, metadata=planned.metadata, usage=completion.usage)


def build_step_prompt(
    task: str,
    step: WorkflowStep,
    config: WorkflowConfig,
    previous_results: list[StepResult],
) -> StepPrompt:
    """Build one step prompt and metadata."""

    model = ModelClient(config.models.get(step.role))
    backend = step.backend
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
        "model": model.requested_model or "mock",
        "backend": backend,
        "context_sources": str(len(step.context)),
    }
    return StepPrompt(step_id=step.id, prompt=prompt, metadata=metadata)


def format_previous_results(results: list[StepResult]) -> str:
    """Format prior in-memory step outputs for the next prompt."""

    if not results:
        return "No previous step output."
    return "\n\n".join(f"--- {result.step_id} ---\n{result.content.rstrip()}" for result in results)


def validate_checkpoint(results: list[StepResult], config: WorkflowConfig) -> None:
    """Ensure a resume checkpoint matches the configured workflow prefix."""

    if len(results) > len(config.steps):
        raise ValueError("resume checkpoint has more step results than the workflow defines")

    for result, step in zip(results, config.steps):
        if result.step_id != step.id:
            raise ValueError(
                f"resume checkpoint does not match workflow order at '{step.id}'"
            )


def serialize_checkpoint(results: list[StepResult]) -> str:
    """Serialize completed step results into a copyable JSON checkpoint."""

    return json.dumps([checkpoint_entry(result) for result in results], indent=2)


def load_checkpoint(raw: str) -> list[StepResult]:
    """Load step results from a JSON checkpoint string."""

    data = json.loads(raw)
    if isinstance(data, dict) and "results" in data:
        data = data["results"]
    if not isinstance(data, list):
        raise ValueError("resume checkpoint must be a JSON array of step results")

    results: list[StepResult] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("resume checkpoint entries must be JSON objects")
        step_id = item.get("step_id")
        content = item.get("content")
        if not isinstance(step_id, str) or not isinstance(content, str):
            raise ValueError("resume checkpoint entries require 'step_id' and 'content'")
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        usage_data = item.get("usage")
        usage = None
        if isinstance(usage_data, dict):
            usage = UsageSummary(
                prompt_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage_data.get("completion_tokens", 0) or 0),
                total_tokens=int(usage_data.get("total_tokens", 0) or 0),
                cost=float(usage_data.get("cost", 0.0) or 0.0),
            )
        results.append(
            StepResult(
                step_id=step_id,
                content=content,
                metadata={str(key): str(value) for key, value in metadata.items()},
                usage=usage,
            )
        )
    return results


def summarize_results(results: list[StepResult]) -> str:
    """Summarize step count, tokens, and cost for terminal output."""

    prompt_tokens = sum(result.usage.prompt_tokens for result in results if result.usage is not None)
    completion_tokens = sum(
        result.usage.completion_tokens for result in results if result.usage is not None
    )
    total_tokens = sum(result.usage.total_tokens for result in results if result.usage is not None)
    cost = sum(result.usage.cost for result in results if result.usage is not None)
    token_count = total_tokens or (prompt_tokens + completion_tokens)
    return f"{len(results)} steps, {format_token_count(token_count)}, ${cost:.2f}"


def format_token_count(total_tokens: int) -> str:
    """Format token counts with a compact human-readable suffix."""

    if total_tokens < 1_000:
        return f"{total_tokens} tokens"
    if total_tokens < 10_000:
        return f"{total_tokens / 1_000:.1f}k tokens"
    return f"{total_tokens / 1_000:.0f}k tokens"


def checkpoint_entry(result: StepResult) -> dict[str, object]:
    """Convert a step result into a JSON-serializable checkpoint entry."""

    entry: dict[str, object] = {
        "step_id": result.step_id,
        "content": result.content,
        "metadata": result.metadata,
    }
    if result.usage is not None:
        entry["usage"] = {
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
            "cost": result.usage.cost,
        }
    return entry

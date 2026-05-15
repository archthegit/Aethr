"""Line-based interactive terminal session for Aethr workflows."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from aethr.config import WorkflowConfig
from aethr.executor import (
    StepPrompt,
    StepResult,
    build_step_prompt,
    run_repeat_block,
    run_step,
    workflow_cursor,
)
from aethr import session as terminal_session
from aethr.render import clean_display_text


@dataclass(frozen=True)
class SteeringMessage:
    """One user or assistant message in the steering log."""

    role: str
    text: str


@dataclass
class ReplState:
    """Mutable state for one REPL workflow session."""

    task: str
    config: WorkflowConfig
    results: list[StepResult] = field(default_factory=list)
    stream_enabled: bool = True
    prompt_visible: bool = False
    status: str = "Type a steering note and press Enter to re-run the last completed step."
    current_step: StepPrompt | None = None
    last_result: StepResult | None = None
    steering_history: list[SteeringMessage] = field(default_factory=list)


def run_repl_workflow(
    task: str,
    config: WorkflowConfig,
    previous_results: list[StepResult] | None = None,
    *,
    stream: bool = True,
    bootstrap_first_step: bool = False,
) -> list[StepResult]:
    """Run a workflow through a compact terminal session."""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("aethr interactive session requires an interactive terminal")

    state = ReplState(task=task, config=config, results=list(previous_results or []), stream_enabled=stream)
    terminal_session.set_stream_rendering_enabled(stream)
    try:
        terminal_session.console.print()
        terminal_session.console.print(f"[bold]Workflow[/bold] {config.workflow}")
        terminal_session.render_workflow_overview(config, previous_results=state.results)

        if bootstrap_first_step and workflow_cursor(state.results, state.config) < len(state.config.steps):
            _run_current_step(state)

        while True:
            planned = _planned_step(state)
            if planned is None:
                terminal_session.console.print(f"[green]Workflow complete[/green] ({len(state.results)} step(s))")
                return state.results

            terminal_session.console.print()
            terminal_session.console.print(
                f"[bold]Current[/bold] {planned.step_id} "
                f"[dim]role={planned.metadata['role']} model={planned.metadata['model']} "
                f"context={planned.metadata['context_sources']}[/dim]"
            )
            terminal_session.console.print("[dim]Enter a note to steer the current step, or /help for commands.[/dim]")

            if state.prompt_visible:
                terminal_session.print_step_prompt(planned)

            command = terminal_session.console.input("[bold]steer> [/bold]")
            action = command.strip()
            if not action:
                _run_current_step(state)
                continue

            if action.startswith("/"):
                if _handle_command(state, action):
                    return state.results
                continue

            state.steering_history.append(SteeringMessage(role="user", text=action))
            state.status = "Steering note added. Re-running the last completed step..."
            if state.last_result is None:
                _run_current_step(state)
            else:
                _rewind_and_run_last_step(state)
    finally:
        terminal_session.set_stream_rendering_enabled(False)


def compose_task_with_steering(task: str, steering_history: list[SteeringMessage], *, limit: int = 8) -> str:
    """Add recent steering notes to the task context for prompt building."""

    if not steering_history:
        return task

    lines = [task, "", "Session steering:"]
    for message in steering_history[-limit:]:
        label = "You" if message.role == "user" else "Aethr"
        lines.append(f"{label}: {clean_display_text(message.text).strip()}")
    return "\n".join(lines)


def _planned_step(state: ReplState) -> StepPrompt | None:
    """Build the prompt for the current workflow step."""

    step_index = workflow_cursor(state.results, state.config)
    if step_index >= len(state.config.steps):
        state.current_step = None
        state.status = "Workflow complete. Type /quit or /exit to leave."
        return None

    step = state.config.steps[step_index]
    task = compose_task_with_steering(state.task, state.steering_history)
    planned = build_step_prompt(task, step, state.config, state.results)
    state.current_step = planned
    return planned


def _handle_command(state: ReplState, command: str) -> bool:
    """Handle one slash command. Return True to exit."""

    name = command[1:].strip().lower()
    if name in {"quit", "q", "exit"}:
        state.status = "Session stopped."
        terminal_session.console.print("[dim]Session stopped.[/dim]")
        return True
    if name in {"prompt", "p"}:
        state.prompt_visible = not state.prompt_visible
        state.status = "Prompt preview toggled."
        terminal_session.console.print(f"[dim]{state.status}[/dim]")
        return False
    if name in {"clear", "c"}:
        state.steering_history.clear()
        state.status = "Steering cleared."
        terminal_session.console.print(f"[dim]{state.status}[/dim]")
        return False
    if name in {"map", "m"}:
        terminal_session.render_workflow_overview(state.config, previous_results=state.results)
        return False
    if name in {"help", "h", "?"}:
        terminal_session.console.print(
            "[dim]Commands: /prompt /clear /map /quit. Plain text notes re-run the last completed step.[/dim]"
        )
        return False
    terminal_session.console.print(f"[red]Unknown command:[/red] {command}")
    return False


def _run_current_step(state: ReplState) -> bool:
    """Run the currently selected step with the accumulated steering context."""

    step_index = workflow_cursor(state.results, state.config)
    return _run_step_at_index(state, step_index)


def _run_step_at_index(state: ReplState, step_index: int) -> bool:
    """Run a specific workflow step by index."""

    if step_index >= len(state.config.steps):
        state.status = "Workflow complete. Type /quit or /exit to leave."
        terminal_session.console.print(f"[green]{state.status}[/green]")
        return False

    step = state.config.steps[step_index]
    task = compose_task_with_steering(state.task, state.steering_history)
    planned = build_step_prompt(task, step, state.config, state.results)
    state.current_step = planned
    state.status = f"Running {planned.step_id}..."

    terminal_session.print_step_start(step_index + 1, len(state.config.steps), planned)
    result = run_step(
        task,
        step,
        state.config,
        state.results,
        planned=planned,
        on_chunk=(lambda _step_id, chunk: terminal_session.print_step_chunk(_step_id, chunk))
        if state.stream_enabled
        else None,
    )
    state.results.append(result)
    state.last_result = result
    if state.stream_enabled:
        terminal_session.print_step_status(result)
    else:
        terminal_session.print_step_result(result)
    state.steering_history.append(SteeringMessage(role="assistant", text=_summarize_result_for_steering(result)))

    if step.repeat is not None:
        state.status = f"Running repeat loop for {planned.step_id}..."
        terminal_session.console.print(f"[dim]{state.status}[/dim]")
        state.results = run_repeat_block(
            task,
            step_index,
            step,
            state.config,
            state.results,
            on_step_start=lambda _index, _total, replay_planned: terminal_session.print_step_start(
                _index, _total, replay_planned
            ),
            on_step_chunk=(
                lambda _step_id, chunk: terminal_session.print_step_chunk(_step_id, chunk)
            )
            if state.stream_enabled
            else None,
            on_step_result=lambda replay_result: terminal_session.print_step_status(replay_result)
            if state.stream_enabled
            else terminal_session.print_step_result(replay_result),
        )
        state.last_result = state.results[-1]
        state.steering_history.append(
            SteeringMessage(role="assistant", text=_summarize_result_for_steering(state.last_result))
        )

    state.status = "Step complete. Type another steering note or press Enter to continue."
    terminal_session.console.print(f"[dim]{state.status}[/dim]")
    return False


def _rewind_and_run_last_step(state: ReplState) -> bool:
    """Rewind the last completed step and run it again with fresh steering context."""

    step_id = state.last_result.step_id if state.last_result is not None else None
    if state.results:
        state.results.pop()
    state.last_result = state.results[-1] if state.results else None

    if step_id is None:
        state.status = "No completed step available to re-run."
        terminal_session.console.print(f"[dim]{state.status}[/dim]")
        return False

    try:
        step_index = next(index for index, step in enumerate(state.config.steps) if step.id == step_id)
    except StopIteration:
        state.status = f"Unknown step to re-run: {step_id}"
        terminal_session.console.print(f"[red]{state.status}[/red]")
        return False

    return _run_step_at_index(state, step_index)


def _summarize_result_for_steering(result: StepResult) -> str:
    """Render a compact assistant reply for the steering history."""

    body = clean_display_text(result.content).strip()
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if result.artifacts is not None and result.artifacts.changed_files:
        files = ", ".join(result.artifacts.changed_files[:3])
        if len(result.artifacts.changed_files) > 3:
            files += ", …"
        return f"{result.step_id} complete. Changed files: {files}"
    if first_line:
        return f"{result.step_id} complete. {first_line[:160]}"
    return f"{result.step_id} complete."

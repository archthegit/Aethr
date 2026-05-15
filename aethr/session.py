"""Shared terminal rendering helpers for Aethr workflows."""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aethr.artifacts import format_artifact_summary
from aethr.config import WorkflowConfig
from aethr.executor import (
    StepResult,
    workflow_cursor,
)
from aethr.render import clean_display_text


console = Console()


@dataclass
class StreamRenderState:
    """Live render state for one streaming step."""

    step_id: str
    content: str = ""
    live: Live | None = None


_STREAM_RENDERING_ENABLED = False
_ACTIVE_STREAM: StreamRenderState | None = None


def set_stream_rendering_enabled(enabled: bool) -> None:
    """Toggle live stream rendering for the current run."""

    global _STREAM_RENDERING_ENABLED
    _STREAM_RENDERING_ENABLED = enabled


def render_workflow_overview(config: WorkflowConfig, previous_results: list[StepResult] | None = None) -> None:
    """Render a compact step overview before execution starts."""

    completed = {result.step_id for result in (previous_results or [])}
    current_index = workflow_cursor(list(previous_results or []), config)
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Step", style="bold")
    table.add_column("Role")
    table.add_column("Backend")
    table.add_column("Perms", width=8)
    table.add_column("Model")
    table.add_column("Ctx", justify="right", width=4)
    table.add_column("Hist", width=8)
    table.add_column("Loop", width=18)
    table.add_column("State", width=10)

    for index, step in enumerate(config.steps):
        if step.id in completed:
            state = "[green]done[/green]"
        elif index == current_index:
            state = "[yellow]current[/yellow]"
        else:
            state = "[dim]pending[/dim]"

        backend = step.backend if step.backend != "model" else "model"
        permissions = ""
        if step.backend == "opencode":
            permissions = "unsafe" if step.unsafe_permissions else "safe"
        history = step.history_visibility
        loop = ""
        if step.repeat is not None:
            loop = f"{step.repeat.back_to}→{step.id} x{step.repeat.max_iterations}"
        model = config.models.get(step.role, "mock")
        table.add_row(
            str(index + 1),
            step.id,
            step.role,
            backend,
            permissions,
            model,
            str(len(step.context)),
            history,
            loop,
            state,
        )

    console.print(Panel(table, title="Workflow map", border_style="blue", box=box.ROUNDED))


def print_step_start(index: int, total: int, planned: StepPrompt) -> None:
    """Print a compact header before a step begins."""

    stop_stream_render()
    backend = planned.metadata.get("backend", "model")
    backend_text = f" backend={backend}" if backend != "model" else ""
    permissions_text = permissions_suffix(planned.metadata)
    details = Table.grid(expand=True, padding=(0, 1))
    details.add_column(ratio=1)
    details.add_column(ratio=2)
    details.add_row(
        f"[bold cyan]{index}/{total}[/bold cyan] [bold]{planned.step_id}[/bold]",
        f"[dim]role={planned.metadata['role']} model={planned.metadata['model']}{backend_text} "
        f"context={planned.metadata['context_sources']}{permissions_text}[/dim]",
    )
    console.print()
    console.print(Panel(details, border_style="cyan", box=box.SIMPLE))
    if _STREAM_RENDERING_ENABLED:
        start_stream_render(planned.step_id)


def print_step_chunk(_step_id: str, chunk: str) -> None:
    """Stream a chunk of model output."""

    if append_stream_chunk(chunk):
        return
    cleaned = clean_display_text(chunk)
    if cleaned:
        console.print(cleaned, end="", markup=False)


def print_step_result(result: StepResult) -> None:
    """Print one in-memory step result."""

    console.print()
    body = clean_display_text(result.content)
    renderable = Text(body or "[no content]")
    console.print(Panel(renderable, title=f"{result.step_id} complete", border_style="green", box=box.SIMPLE))

    if result.artifacts is not None:
        console.print(
            Panel(
                Text(format_artifact_summary(result.artifacts)),
                title=f"{result.step_id} artifacts",
                border_style="cyan",
                box=box.SIMPLE,
            )
        )


def print_step_status(result: StepResult) -> None:
    """Print a compact completion line after a streamed step."""

    if _ACTIVE_STREAM is not None and _ACTIVE_STREAM.step_id == result.step_id:
        if result.content.strip():
            _ACTIVE_STREAM.content = result.content
        stop_stream_render()

    console.print()
    console.print(
        f"[green]✓[/green] [bold]{result.step_id}[/bold] "
        f"[dim]role={result.metadata['role']} model={result.metadata['model']}"
        f"{backend_suffix(result.metadata)}{permissions_suffix(result.metadata)}{loop_suffix(result.metadata)}[/dim]"
    )


def permissions_suffix(metadata: dict[str, str]) -> str:
    """Render permission mode for agent-backed steps."""

    permissions = metadata.get("permissions")
    if not permissions:
        return ""
    return f" permissions={permissions}"


def backend_suffix(metadata: dict[str, str]) -> str:
    """Render backend mode for a step."""

    backend = metadata.get("backend", "model")
    if backend == "model":
        return ""
    return f" backend={backend}"


def loop_suffix(metadata: dict[str, str]) -> str:
    """Render loop outcome metadata for controller steps."""

    status = metadata.get("loop_status")
    if not status:
        return ""
    iterations = metadata.get("loop_iterations", "")
    suffix = f" loop={status}"
    if iterations:
        suffix += f"x{iterations}"
    return f" {suffix}"


def start_stream_render(step_id: str) -> None:
    """Start a live rendered box for streaming output."""

    global _ACTIVE_STREAM
    stop_stream_render()
    state = StreamRenderState(step_id=step_id)
    state.live = Live(stream_panel(state), console=console, refresh_per_second=12, transient=False)
    state.live.__enter__()
    _ACTIVE_STREAM = state


def append_stream_chunk(chunk: str) -> bool:
    """Append a chunk to the active live stream, if any."""

    if _ACTIVE_STREAM is None or _ACTIVE_STREAM.live is None:
        return False

    _ACTIVE_STREAM.content += chunk
    _ACTIVE_STREAM.live.update(stream_panel(_ACTIVE_STREAM))
    return True


def stop_stream_render() -> None:
    """Stop the active live stream, preserving its last rendered state."""

    global _ACTIVE_STREAM
    if _ACTIVE_STREAM is None or _ACTIVE_STREAM.live is None:
        _ACTIVE_STREAM = None
        return

    _ACTIVE_STREAM.live.__exit__(None, None, None)
    _ACTIVE_STREAM = None


def stream_panel(state: StreamRenderState) -> Panel:
    """Render the current streaming buffer as a boxed text panel."""

    body = clean_display_text(state.content)
    renderable = Text(body) if body else Text("waiting for output...", style="dim")
    return Panel(renderable, title=f"{state.step_id} streaming", border_style="green", box=box.SIMPLE)

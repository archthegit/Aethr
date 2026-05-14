"""Command-line interface for Aethr."""

from __future__ import annotations

import re
import shlex
import tempfile
import textwrap
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.table import Table

from aethr import __version__
from aethr.auth import env_var_for, login as auth_login, status as auth_status
from aethr.artifacts import format_artifact_block, format_artifact_summary
from aethr.config import CONFIG_FILE, ConfigError, load_workflow_config
from aethr.executor import (
    StepPrompt,
    StepResult,
    WorkflowStepError,
    build_workflow_prompts,
    format_token_count,
    load_checkpoint,
    workflow_cursor,
    run_workflow,
    serialize_checkpoint,
    summarize_results,
    validate_checkpoint,
)
from aethr.llm import LLMError
from aethr.workflow import WorkflowTemplateError, available_workflows, init_workflow


app = typer.Typer(help="Explicit, reproducible AI coding workflows.")
console = Console()
auth_app = typer.Typer(help="Manage project-local API key credentials.")
app.add_typer(auth_app, name="auth")


@app.callback()
def main() -> None:
    """Aethr command group."""


@app.command()
def init(
    preset: Annotated[str | None, typer.Argument(help="Workflow preset to initialize.")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite an existing .aethr.yaml.")] = False,
    list_only: Annotated[bool, typer.Option("--list", "-l", help="List available workflow presets.")] = False,
) -> None:
    """Initialize a workflow config from a built-in YAML preset."""

    workflows = available_workflows()
    if list_only:
        for workflow in workflows:
            console.print(workflow)
        return

    selected = preset
    if selected is None:
        console.print("Available workflows:")
        for index, workflow in enumerate(workflows, start=1):
            console.print(f"  {index}. {workflow}")
        choice = typer.prompt("Select a workflow", default="1")
        selected = _resolve_workflow_choice(choice, workflows)

    try:
        path = init_workflow(selected, force=force)
    except WorkflowTemplateError as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print(f"Initialized [bold]{path}[/bold] from [cyan]{selected}[/cyan]")


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="Coding task to run through the pipeline.")],
    show_prompt: Annotated[
        bool,
        typer.Option("--show-prompt", help="Print exact step prompts without calling models."),
    ] = False,
    stream: Annotated[
        bool,
        typer.Option("--stream/--no-stream", help="Stream step output live instead of using panels."),
    ] = True,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Print the full checkpoint JSON on failure."),
    ] = False,
    resume_checkpoint: Annotated[
        str | None,
        typer.Option(
            "--resume-checkpoint",
            help="JSON array or @file with previously completed step results.",
        ),
    ] = None,
) -> None:
    """Run the configured sequential workflow."""

    console.print(Panel.fit(task, title="Aethr Task", border_style="cyan"))
    try:
        config = load_workflow_config()
    except ConfigError as exc:
        raise typer.BadParameter(f"{exc}. Run 'aethr init' to create {CONFIG_FILE}.") from exc

    console.print(f"[bold]Workflow[/bold] {config.workflow}")
    previous_results = _load_resume_results(resume_checkpoint, config)
    if previous_results:
        console.print(f"[dim]Resuming from {len(previous_results)} completed step(s).[/dim]")
    render_workflow_overview(config, previous_results=previous_results)

    if show_prompt:
        console.print("[bold]Mode[/bold] prompt preview")
        prompts = build_workflow_prompts(task, config, previous_results=previous_results)
        if not prompts:
            console.print("[green]No remaining steps to preview[/green]")
            return
        for index, planned in enumerate(prompts, start=len(previous_results) + 1):
            _print_step_start(index, len(config.steps), planned)
            _print_step_prompt(planned)
        console.print("[green]Prompt preview complete[/green]")
        return

    try:
        results = run_workflow(
            task,
            config,
            previous_results=previous_results,
            on_step_start=_print_step_start,
            on_step_chunk=_print_step_chunk if stream else None,
            on_step_result=_print_step_status if stream else _print_step_result,
        )
    except LLMError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except WorkflowStepError as exc:
        _print_workflow_failure(task, exc, verbose=verbose)
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Workflow complete[/green] ({summarize_results(results)})")


@app.command()
def version() -> None:
    """Print the Aethr version."""

    console.print(f"Aethr {__version__}")


@auth_app.command()
def status(
    env_file: Annotated[
        str,
        typer.Option("--env-file", help="Project .env file to inspect."),
    ] = ".env",
) -> None:
    """Show which provider credentials are available."""

    file_status = auth_status(env_file)
    console.print(f"[bold]Credential status[/bold] ({env_file})")
    for provider, state in sorted(file_status.items()):
        console.print(f"  {provider}: {state}")


@auth_app.command()
def login(
    provider: Annotated[str, typer.Argument(help="Provider to store credentials for.")],
    key: Annotated[
        str | None,
        typer.Option("--key", help="API key value. Prompts if omitted."),
    ] = None,
    env_file: Annotated[
        str,
        typer.Option("--env-file", help="Project .env file to update."),
    ] = ".env",
) -> None:
    """Store a provider API key in the project .env file."""

    try:
        env_var, _ = env_var_for(provider)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    value = key or typer.prompt(f"{env_var}", hide_input=True)
    if not value.strip():
        raise typer.BadParameter("API key cannot be empty")

    _, path = auth_login(provider, value.strip(), env_file=env_file)
    console.print(f"[green]Stored[/green] {env_var} in [bold]{path}[/bold]")


def _print_step_start(index: int, total: int, planned: StepPrompt) -> None:
    """Print a compact header before a step begins."""

    backend = planned.metadata.get("backend", "model")
    backend_text = f" backend={backend}" if backend != "model" else ""
    permissions_text = _permissions_suffix(planned.metadata)
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


def _print_step_chunk(_step_id: str, chunk: str) -> None:
    """Stream a chunk of model output."""

    console.print(chunk, end="", markup=False)


def _print_step_result(result: StepResult) -> None:
    """Print one in-memory step result."""

    console.print()
    body = _clean_display_text(result.content)
    console.print(Panel(body or "[no content]", title=f"{result.step_id} complete", border_style="green", box=box.SIMPLE))

    if result.artifacts is not None:
        console.print(
            Panel(
                format_artifact_summary(result.artifacts),
                title=f"{result.step_id} artifacts",
                border_style="cyan",
                box=box.SIMPLE,
            )
    )


def _clean_display_text(text: str) -> str:
    """Remove common markdown markers before rendering terminal output."""

    cleaned_lines: list[str] = []
    in_code_block = False

    for raw_line in textwrap.dedent(text).strip().splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            cleaned_lines.append(line)
            continue

        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if heading is not None:
            cleaned_lines.append(heading.group(1).strip())
            continue

        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", line)
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _print_step_status(result: StepResult) -> None:
    """Print a compact completion line after a streamed step."""

    usage = ""
    if result.usage is not None and (result.usage.total_tokens or result.usage.cost):
        usage = f" [dim]{format_token_count(result.usage.total_tokens)} ${result.usage.cost:.2f}[/dim]"

    backend = result.metadata.get("backend", "model")
    backend_text = f" backend={backend}" if backend != "model" else ""
    permissions_text = _permissions_suffix(result.metadata)
    loop_status = _loop_suffix(result.metadata)
    console.print()
    console.print(
        f"[green]✓[/green] [bold]{result.step_id}[/bold] "
        f"[dim]role={result.metadata['role']} model={result.metadata['model']}{backend_text}"
        f"{permissions_text}{loop_status}[/dim]{usage}"
    )


def _print_step_prompt(planned: StepPrompt) -> None:
    """Print one planned prompt."""

    console.print(Panel(planned.prompt, title=f"{planned.step_id} prompt", border_style="yellow", box=box.SIMPLE))


def render_workflow_overview(config, previous_results: list[StepResult] | None = None) -> None:
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


def _permissions_suffix(metadata: dict[str, str]) -> str:
    """Render permission mode for agent-backed steps."""

    permissions = metadata.get("permissions")
    if not permissions:
        return ""
    return f" permissions={permissions}"


def _loop_suffix(metadata: dict[str, str]) -> str:
    """Render loop outcome metadata for controller steps."""

    status = metadata.get("loop_status")
    if not status:
        return ""
    iterations = metadata.get("loop_iterations", "")
    suffix = f" loop={status}"
    if iterations:
        suffix += f"x{iterations}"
    return f" {suffix}"


def _load_resume_results(resume_checkpoint: str | None, config) -> list[StepResult]:
    """Load a copyable checkpoint if one was provided."""

    if resume_checkpoint is None:
        return []

    checkpoint_text = _read_text_or_file(resume_checkpoint)
    try:
        results = load_checkpoint(checkpoint_text)
        validate_checkpoint(results, config)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return results


def _read_text_or_file(value: str) -> str:
    """Read inline JSON or a file reference prefixed with @."""

    if value.startswith("@"):
        try:
            return Path(value[1:]).read_text(encoding="utf-8")
        except OSError as exc:
            raise typer.BadParameter(f"Unable to read checkpoint file '{value[1:]}': {exc}") from exc
    return value


def _print_workflow_failure(task: str, error: WorkflowStepError, *, verbose: bool = False) -> None:
    """Print a compact failure summary and a resumable checkpoint path."""

    console.print()
    console.print(f"[red]Workflow failed[/red] at step [bold]{error.step_id}[/bold]")
    console.print(f"[bold]Reason:[/bold] {friendly_failure_reason(error)}")

    checkpoint = serialize_checkpoint(error.completed_results)
    checkpoint_path = write_checkpoint_file(checkpoint)
    resume_command = shlex.join(["aethr", "run", task, "--resume-checkpoint", f"@{checkpoint_path}"])

    console.print("[bold]To resume:[/bold]")
    console.print("1. Fix the missing credential or other issue.")
    typer.echo(f"Resume command: {resume_command}")

    if verbose:
        console.print()
        console.print(Panel(checkpoint, title="Resume checkpoint", border_style="red"))
    else:
        console.print(f"[dim]Checkpoint saved to {checkpoint_path}[/dim]")


def friendly_failure_reason(error: WorkflowStepError) -> str:
    """Reduce noisy provider errors into a compact terminal reason."""

    message = str(error.cause)
    provider = provider_from_message(message)
    lower = message.lower()
    if (
        "invalid_api_key" in lower
        or "invalid api key" in lower
        or "incorrect api key" in lower
        or "api key expired" in lower
        or "expired api key" in lower
        or "key expired" in lower
    ):
        return message.rstrip(".")
    if (
        "api_key client option must be set" in lower
        or "api key client option must be set" in lower
        or "missing api key" in lower
        or "no api key" in lower
        or "api key is required" in lower
        or ("missing key" in lower and provider is not None)
    ):
        if provider == "anthropic":
            return "Missing Anthropic API key."
        if provider == "openai":
            return "Missing OpenAI API key."
        if provider in {"google", "gemini"}:
            return "Missing Google API key."
        return "Missing API key."
    return message.rstrip(".")


def provider_from_message(message: str) -> str | None:
    """Extract a provider name from an error message when possible."""

    match = re.search(r"for '([^']+)'", message)
    if not match:
        return None
    model = match.group(1)
    if ":" in model:
        provider = model.split(":", 1)[0]
    elif "/" in model:
        provider = model.split("/", 1)[0]
    else:
        provider = model
    return provider.lower()


def write_checkpoint_file(checkpoint: str) -> str:
    """Persist the resume checkpoint to a temp file for copy-free recovery."""

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="aethr-checkpoint-",
        suffix=".json",
        delete=False,
    ) as handle:
        handle.write(checkpoint)
        return handle.name


def _resolve_workflow_choice(choice: str, workflows: list[str]) -> str:
    """Resolve an interactive workflow prompt response."""

    if choice.isdigit():
        index = int(choice)
        if 1 <= index <= len(workflows):
            return workflows[index - 1]
    if choice in workflows:
        return choice
    choices = ", ".join(workflows)
    raise typer.BadParameter(f"Unknown workflow '{choice}'. Available workflows: {choices}")


if __name__ == "__main__":
    app()

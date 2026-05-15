"""Command-line interface for Aethr."""

from __future__ import annotations

import re
import shlex
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich import box
from rich.panel import Panel

from aethr import __version__
from aethr.auth import env_var_for, login as auth_login, status as auth_status
from aethr.config import CONFIG_FILE, ConfigError, load_workflow_config
from aethr.env import load_project_dotenv
from aethr.executor import (
    StepResult,
    WorkflowStepError,
    build_workflow_prompts,
    load_checkpoint,
    run_workflow,
    serialize_checkpoint,
    summarize_results,
    validate_checkpoint,
)
from aethr.llm import LLMError
from aethr import session as terminal_session
from aethr.tui import run_tui_workflow
from aethr.workflow import WorkflowTemplateError, available_workflows, init_workflow


app = typer.Typer(help="Explicit, reproducible AI coding workflows.")
console = Console()
auth_app = typer.Typer(help="Manage project-local API key credentials.")
app.add_typer(auth_app, name="auth")


@app.callback()
def main() -> None:
    """Aethr command group."""

    load_project_dotenv()


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
    terminal_session.render_workflow_overview(config, previous_results=previous_results)
    terminal_session.set_stream_rendering_enabled(stream)

    if show_prompt:
        console.print("[bold]Mode[/bold] prompt preview")
        prompts = build_workflow_prompts(task, config, previous_results=previous_results)
        if not prompts:
            console.print("[green]No remaining steps to preview[/green]")
            return
        for index, planned in enumerate(prompts, start=len(previous_results) + 1):
            terminal_session.print_step_start(index, len(config.steps), planned)
            terminal_session.print_step_prompt(planned)
        console.print("[green]Prompt preview complete[/green]")
        return

    try:
        results = run_workflow(
            task,
            config,
            previous_results=previous_results,
            on_step_start=terminal_session.print_step_start,
            on_step_chunk=terminal_session.print_step_chunk if stream else None,
            on_step_result=terminal_session.print_step_status if stream else terminal_session.print_step_result,
        )
    except LLMError as exc:
        terminal_session.stop_stream_render()
        raise typer.BadParameter(str(exc)) from exc
    except WorkflowStepError as exc:
        terminal_session.stop_stream_render()
        _print_workflow_failure(task, exc, verbose=verbose)
        raise typer.Exit(code=1) from exc
    finally:
        terminal_session.set_stream_rendering_enabled(False)

    console.print(f"[green]Workflow complete[/green] ({summarize_results(results)})")


@app.command()
def tui(
    task: Annotated[str, typer.Argument(help="Coding task to run through the TUI.")],
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
    """Run the configured workflow inside a full-screen terminal UI."""

    try:
        config = load_workflow_config()
    except ConfigError as exc:
        raise typer.BadParameter(f"{exc}. Run 'aethr init' to create {CONFIG_FILE}.") from exc

    previous_results = _load_resume_results(resume_checkpoint, config)

    try:
        results = run_tui_workflow(task, config, previous_results=previous_results)
    except LLMError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except RuntimeError as exc:
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


def _permissions_suffix(metadata: dict[str, str]) -> str:
    """Render permission mode for agent-backed steps."""

    permissions = metadata.get("permissions")
    if not permissions:
        return ""
    return f" permissions={permissions}"


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
    resume_command = _build_resume_command(task, checkpoint_path)

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
    if _is_invalid_or_expired_api_key_error(lower):
        return message.rstrip(".")
    if _is_missing_api_key_error(lower, provider):
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


def _build_resume_command(task: str, checkpoint_path: str) -> str:
    """Build a copy/paste-safe resume command for POSIX shells."""

    return shlex.join(["aethr", "run", task, "--resume-checkpoint", f"@{checkpoint_path}"])


def _is_missing_api_key_error(message_lower: str, provider: str | None) -> bool:
    """Detect true missing-key errors while excluding invalid/expired keys."""

    if _is_invalid_or_expired_api_key_error(message_lower):
        return False
    if (
        "api_key client option must be set" in message_lower
        or "api key client option must be set" in message_lower
        or "missing api key" in message_lower
        or "no api key" in message_lower
        or "api key is required" in message_lower
    ):
        return True
    return "missing key" in message_lower and provider is not None


def _is_invalid_or_expired_api_key_error(message_lower: str) -> bool:
    """Detect invalid/expired key errors and avoid labeling them as missing."""

    direct_markers = (
        "invalid_api_key",
        "invalid api key",
        "incorrect api key",
        "api key invalid",
        "api key expired",
        "expired api key",
        "revoked api key",
        "invalid key provided",
        "key is expired",
    )
    if any(marker in message_lower for marker in direct_markers):
        return True

    has_auth_context = (
        "api key" in message_lower
        or "authentication" in message_lower
        or "unauthorized" in message_lower
        or "forbidden" in message_lower
    )
    if not has_auth_context:
        return False

    return bool(
        re.search(r"\b(invalid|incorrect|expired|revoked)\b[^\n]{0,24}\b(api key|key)\b", message_lower)
        or re.search(r"\b(api key|key)\b[^\n]{0,24}\b(invalid|incorrect|expired|revoked)\b", message_lower)
    )


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

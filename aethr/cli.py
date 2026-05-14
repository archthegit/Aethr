"""Command-line interface for Aethr."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from aethr import __version__
from aethr.config import CONFIG_FILE, ConfigError, load_workflow_config
from aethr.executor import (
    StepPrompt,
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
from aethr.workflow import WorkflowTemplateError, available_workflows, init_workflow


app = typer.Typer(help="Explicit, reproducible AI coding workflows.")
console = Console()


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
            on_step_chunk=_print_step_chunk,
            on_step_result=_print_step_result,
        )
    except LLMError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except WorkflowStepError as exc:
        _print_workflow_failure(exc)
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Workflow complete[/green] ({summarize_results(results)})")


@app.command()
def version() -> None:
    """Print the Aethr version."""

    console.print(f"Aethr {__version__}")


def _print_step_start(index: int, total: int, planned: StepPrompt) -> None:
    """Print a compact header before a step begins."""

    console.print()
    console.print(
        f"[bold cyan]{index}/{total}[/bold cyan] "
        f"[bold]{planned.step_id}[/bold] "
        f"[dim]role={planned.metadata['role']} "
        f"model={planned.metadata['model']} "
        f"context={planned.metadata['context_sources']}[/dim]"
    )


def _print_step_chunk(_step_id: str, chunk: str) -> None:
    """Stream a chunk of model output."""

    console.print(chunk, end="")


def _print_step_result(result: StepResult) -> None:
    """Print one in-memory step result."""

    console.print()
    console.print(Panel(result.content, border_style="green"))


def _print_step_prompt(planned: StepPrompt) -> None:
    """Print one planned prompt."""

    console.print(Panel(planned.prompt, border_style="yellow"))


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


def _print_workflow_failure(error: WorkflowStepError) -> None:
    """Print a resumable checkpoint when a step fails."""

    console.print()
    console.print(f"[red]Workflow failed[/red] at step [bold]{error.step_id}[/bold]")
    console.print(Panel(str(error.cause), title="Error", border_style="red"))
    checkpoint = serialize_checkpoint(error.completed_results)
    console.print(Panel(checkpoint, title="Resume checkpoint", border_style="red"))
    console.print("[dim]Save the JSON above and pass it back with --resume-checkpoint @file.json.[/dim]")


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

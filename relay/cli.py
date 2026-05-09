"""Command-line interface for Relay."""

from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from relay import __version__
from relay.config import CONFIG_FILE, ConfigError, load_workflow_config
from relay.executor import StepPrompt, StepResult, build_workflow_prompts, run_workflow
from relay.llm import LLMError
from relay.workflow import WorkflowTemplateError, available_workflows, init_workflow


app = typer.Typer(help="Explicit, reproducible AI coding workflows.")
console = Console()


@app.callback()
def main() -> None:
    """Relay command group."""


@app.command()
def init(
    preset: Annotated[str | None, typer.Argument(help="Workflow preset to initialize.")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite an existing .relay.yaml.")] = False,
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
) -> None:
    """Run the configured sequential workflow."""

    console.print(Panel.fit(task, title="Relay Task", border_style="cyan"))
    try:
        config = load_workflow_config()
    except ConfigError as exc:
        raise typer.BadParameter(f"{exc}. Run 'relay init' to create {CONFIG_FILE}.") from exc

    console.print(f"[bold]Workflow[/bold] {config.workflow}")
    if show_prompt:
        console.print("[bold]Mode[/bold] prompt preview")
        for planned in build_workflow_prompts(task, config):
            _print_step_prompt(planned)
        console.print("[green]Prompt preview complete[/green]")
        return

    try:
        results = run_workflow(task, config, on_step_result=_print_step_result)
    except LLMError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]Workflow complete[/green] ({len(results)} step results)")


@app.command()
def version() -> None:
    """Print the Relay version."""

    console.print(f"Relay {__version__}")


def _print_step_result(result: StepResult) -> None:
    """Print one in-memory step result."""

    title = step_title(result.step_id, result.metadata)
    console.print()
    console.print(Panel(result.content, title=title, border_style="green"))


def _print_step_prompt(planned: StepPrompt) -> None:
    """Print one planned prompt."""

    title = step_title(planned.step_id, planned.metadata)
    console.print()
    console.print(Panel(planned.prompt, title=title, border_style="yellow"))


def step_title(step_id: str, metadata: dict[str, str]) -> str:
    """Build a compact terminal title for a step."""

    return (
        f"{step_id} | role={metadata['role']} | "
        f"model={metadata['model']} | context={metadata['context_sources']}"
    )


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

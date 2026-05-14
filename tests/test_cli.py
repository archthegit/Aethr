from typer.testing import CliRunner

from aethr.cli import app
from aethr.config import WorkflowConfig, WorkflowStep
from aethr.executor import StepPrompt, StepResult, WorkflowStepError
from aethr.llm import LLMError


def test_version_command() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "Aethr 0.1.5" in result.output


def test_run_failure_is_compact(monkeypatch) -> None:
    runner = CliRunner()
    config = WorkflowConfig(
        workflow="plan-implement-review",
        roles={"planner": "Plan.", "implementer": "Implement.", "reviewer": "Review."},
        models={
            "planner": "openai:gpt-4o-mini",
            "implementer": "openai:gpt-5.3-codex",
            "reviewer": "openai:gpt-4o-mini",
        },
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="implement", role="implementer"),
            WorkflowStep(id="review", role="reviewer"),
        ],
    )

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr(
        "aethr.cli.run_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            WorkflowStepError(
                "implement",
                [StepResult(step_id="plan", content="seed")],
                LLMError("Model call failed for 'anthropic/claude-sonnet-4-20250514': missing key"),
            )
        ),
    )

    result = runner.invoke(app, ["run", "add support for loading .env files"])

    assert result.exit_code == 1
    assert "Workflow failed at step implement" in result.output
    assert "Reason:" in result.output
    assert "Missing Anthropic API key." in result.output
    assert "Resume command:" in result.output
    assert "step_id" not in result.output


def test_run_failure_verbose_shows_checkpoint(monkeypatch) -> None:
    runner = CliRunner()
    config = WorkflowConfig(
        workflow="plan-implement-review",
        roles={"planner": "Plan.", "implementer": "Implement.", "reviewer": "Review."},
        models={
            "planner": "openai:gpt-4o-mini",
            "implementer": "openai:gpt-5.3-codex",
            "reviewer": "openai:gpt-4o-mini",
        },
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="implement", role="implementer"),
            WorkflowStep(id="review", role="reviewer"),
        ],
    )

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr(
        "aethr.cli.run_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            WorkflowStepError(
                "implement",
                [StepResult(step_id="plan", content="seed")],
                LLMError("Model call failed for 'anthropic/claude-sonnet-4-20250514': missing key"),
            )
        ),
    )

    result = runner.invoke(app, ["run", "add support for loading .env files", "--verbose"])

    assert result.exit_code == 1
    assert "Resume checkpoint" in result.output
    assert '"step_id": "plan"' in result.output


def test_run_streams_chunks_and_prints_compact_status(monkeypatch) -> None:
    runner = CliRunner()
    config = WorkflowConfig(
        workflow="stream",
        roles={"reviewer": "Review."},
        models={"reviewer": "openai:gpt-4o-mini"},
        steps=[WorkflowStep(id="review", role="reviewer")],
    )

    def fake_run_workflow(task, config, previous_results=None, on_step_start=None, on_step_chunk=None, on_step_result=None):
        planned = StepPrompt(
            step_id="review",
            prompt="prompt",
            metadata={"role": "reviewer", "model": "openai:gpt-4o-mini", "context_sources": "0"},
        )
        if on_step_start is not None:
            on_step_start(1, 1, planned)
        if on_step_chunk is not None:
            on_step_chunk("review", "live chunk")
        result = StepResult(step_id="review", content="full content", metadata=planned.metadata)
        if on_step_result is not None:
            on_step_result(result)
        return [result]

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr("aethr.cli.run_workflow", fake_run_workflow)

    result = runner.invoke(app, ["run", "review my changes"])

    assert result.exit_code == 0
    assert "Workflow map" in result.output
    assert "live chunk" in result.output
    assert "✓" in result.output
    assert "full content" not in result.output


def test_run_no_stream_prints_full_result_panel(monkeypatch) -> None:
    runner = CliRunner()
    config = WorkflowConfig(
        workflow="panel",
        roles={"reviewer": "Review."},
        models={"reviewer": "openai:gpt-4o-mini"},
        steps=[WorkflowStep(id="review", role="reviewer")],
    )

    def fake_run_workflow(task, config, previous_results=None, on_step_start=None, on_step_chunk=None, on_step_result=None):
        planned = StepPrompt(
            step_id="review",
            prompt="prompt",
            metadata={"role": "reviewer", "model": "openai:gpt-4o-mini", "context_sources": "0"},
        )
        if on_step_start is not None:
            on_step_start(1, 1, planned)
        result = StepResult(step_id="review", content="full content", metadata=planned.metadata)
        if on_step_result is not None:
            on_step_result(result)
        return [result]

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr("aethr.cli.run_workflow", fake_run_workflow)

    result = runner.invoke(app, ["run", "review my changes", "--no-stream"])

    assert result.exit_code == 0
    assert "full content" in result.output
    assert "live chunk" not in result.output

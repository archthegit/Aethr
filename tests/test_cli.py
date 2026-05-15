import os
import shlex

import pytest
from typer.testing import CliRunner

from aethr.cli import app, friendly_failure_reason
from aethr.config import WorkflowConfig, WorkflowStep
from aethr.executor import StepPrompt, StepResult, WorkflowStepError
from aethr.llm import LLMError


def test_version_command() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "Aethr 0.1.14" in result.output


def test_cli_callback_loads_project_dotenv(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AETHR_MODEL", raising=False)
    (tmp_path / ".env").write_text("AETHR_MODEL=openai:gpt-4o-mini\n", encoding="utf-8")

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert os.getenv("AETHR_MODEL") == "openai:gpt-4o-mini"


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


def test_run_failure_resume_command_quotes_checkpoint_path(monkeypatch) -> None:
    _assert_resume_command_uses_single_safe_checkpoint_argument(
        monkeypatch,
        "/tmp/checkpoint folder/with 'quote'.json",
    )


def test_run_failure_resume_command_matches_shlex_join(monkeypatch) -> None:
    runner = CliRunner()
    checkpoint_path = "/tmp/checkpoint with 'quote'.json"
    task = "add support for loading .env files"
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
    monkeypatch.setattr("aethr.cli.write_checkpoint_file", lambda checkpoint: checkpoint_path)
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

    result = runner.invoke(app, ["run", task])

    assert result.exit_code == 1
    resume_command = _extract_resume_command(result.output)
    assert resume_command == shlex.join(["aethr", "run", task, "--resume-checkpoint", f"@{checkpoint_path}"])


@pytest.mark.parametrize(
    "checkpoint_path",
    [
        "/tmp/checkpoint folder/with spaces.json",
        "/tmp/checkpoint[1]{draft}.json",
        "/tmp/checkpoint;$HOME&&echo boom.json",
        '/tmp/checkpoint"double"\'single\'.json',
        r"C:\\Users\\Jane Doe\\AppData\\Local\\Temp\\checkpoint'state.json",
    ],
)
def test_run_failure_resume_command_handles_shell_sensitive_paths(monkeypatch, checkpoint_path: str) -> None:
    _assert_resume_command_uses_single_safe_checkpoint_argument(monkeypatch, checkpoint_path)


def _assert_resume_command_uses_single_safe_checkpoint_argument(monkeypatch, checkpoint_path: str) -> None:
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
    monkeypatch.setattr("aethr.cli.write_checkpoint_file", lambda checkpoint: checkpoint_path)
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
    resume_command = _extract_resume_command(result.output)
    command_parts = shlex.split(resume_command)
    assert command_parts[:3] == ["aethr", "run", "add support for loading .env files"]
    assert command_parts[3] == "--resume-checkpoint"
    assert command_parts[4] == f"@{checkpoint_path}"


def _extract_resume_command(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Resume command:"):
            return line.replace("Resume command:", "", 1).strip()
    raise AssertionError("Resume command line was not printed")


@pytest.mark.parametrize(
    "message",
    [
        "Model call failed for 'openai/gpt-4o-mini': AuthenticationError: invalid_api_key",
        "Model call failed for 'anthropic/claude-sonnet-4-20250514': API key expired",
        "Model call failed for 'openai/gpt-4o-mini': Incorrect API key provided",
        "Model call failed for 'openai/gpt-4o-mini': Unauthorized: invalid API key",
        "Model call failed for 'openai/gpt-4o-mini': invalid API key; missing key in previous request",
        "Model call failed for 'openai/gpt-4o-mini': invalid key provided; missing key",
        "Model call failed for 'openai/gpt-4o-mini': unauthorized because key is expired",
        "Model call failed for 'openai/gpt-4o-mini': Authentication failed: revoked api key",
    ],
)
def test_friendly_failure_reason_does_not_label_invalid_or_expired_keys_as_missing(message: str) -> None:
    reason = friendly_failure_reason(
        WorkflowStepError(
            "implement",
            [],
            LLMError(message),
        )
    )

    assert reason == message
    assert "Missing" not in reason


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Model call failed for 'openai/gpt-4o-mini': API key client option must be set",
            "Missing OpenAI API key.",
        ),
        (
            "Model call failed for 'anthropic/claude-sonnet-4-20250514': missing key",
            "Missing Anthropic API key.",
        ),
        (
            "Model call failed for 'gemini/gemini-2.5-flash': missing api key",
            "Missing Google API key.",
        ),
        (
            "Authentication failed: no api key",
            "Missing API key.",
        ),
    ],
)
def test_friendly_failure_reason_labels_only_true_missing_key_cases(message: str, expected: str) -> None:
    reason = friendly_failure_reason(
        WorkflowStepError(
            "implement",
            [],
            LLMError(message),
        )
    )

    assert reason == expected


def test_friendly_failure_reason_does_not_treat_non_auth_invalid_key_text_as_missing() -> None:
    message = "Validation failed: invalid key name in schema"
    reason = friendly_failure_reason(
        WorkflowStepError(
            "implement",
            [],
            LLMError(message),
        )
    )

    assert reason == message


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


def test_run_no_stream_renders_markdown_without_literal_markup(monkeypatch) -> None:
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
        result = StepResult(
            step_id="review",
            content="Findings:\n\n1. **High Severity**: Fix the bug.\n2. **Low Severity**: Add a test.",
            metadata=planned.metadata,
        )
        if on_step_result is not None:
            on_step_result(result)
        return [result]

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr("aethr.cli.run_workflow", fake_run_workflow)

    result = runner.invoke(app, ["run", "review my changes", "--no-stream"])

    assert result.exit_code == 0
    assert "High Severity" in result.output
    assert "Low Severity" in result.output
    assert "**High Severity**" not in result.output
    assert "**Low Severity**" not in result.output


def test_run_streams_bracketed_chunks_without_markup(monkeypatch) -> None:
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
            on_step_chunk("review", "[/tmp/checkpoint folder/with spaces.json]")
            on_step_chunk("review", "<tag>plain text</tag>")
        result = StepResult(step_id="review", content="full content", metadata=planned.metadata)
        if on_step_result is not None:
            on_step_result(result)
        return [result]

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr("aethr.cli.run_workflow", fake_run_workflow)

    result = runner.invoke(app, ["run", "review my changes"])

    assert result.exit_code == 0
    assert "[/tmp/checkpoint folder/with spaces.json]" in result.output
    assert "<tag>plain text</tag>" in result.output


def test_tui_command_invokes_runner(monkeypatch) -> None:
    runner = CliRunner()
    config = WorkflowConfig(
        workflow="tui",
        roles={"reviewer": "Review."},
        models={"reviewer": "openai:gpt-4o-mini"},
        steps=[WorkflowStep(id="review", role="reviewer")],
    )

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr("aethr.cli.run_tui_workflow", lambda *args, **kwargs: [])

    result = runner.invoke(app, ["tui", "review my changes"])

    assert result.exit_code == 0
    assert "Workflow complete" in result.output


def test_run_streams_markdown_chunks_without_literal_markup(monkeypatch) -> None:
    runner = CliRunner()
    config = WorkflowConfig(
        workflow="stream",
        roles={"planner": "Plan."},
        models={"planner": "openai:gpt-4o-mini"},
        steps=[WorkflowStep(id="plan", role="planner")],
    )

    def fake_run_workflow(task, config, previous_results=None, on_step_start=None, on_step_chunk=None, on_step_result=None):
        planned = StepPrompt(
            step_id="plan",
            prompt="prompt",
            metadata={"role": "planner", "model": "openai:gpt-4o-mini", "context_sources": "0"},
        )
        if on_step_start is not None:
            on_step_start(1, 1, planned)
        if on_step_chunk is not None:
            on_step_chunk("plan", "### Implementation Plan\n\n**Objective:** Fix the bug.\n")
            on_step_chunk("plan", "1. **High Severity**: Handle edge cases.\n")
        result = StepResult(step_id="plan", content="full content", metadata=planned.metadata)
        if on_step_result is not None:
            on_step_result(result)
        return [result]

    monkeypatch.setattr("aethr.cli.load_workflow_config", lambda: config)
    monkeypatch.setattr("aethr.cli.run_workflow", fake_run_workflow)

    result = runner.invoke(app, ["run", "review my changes"])

    assert result.exit_code == 0
    assert "Implementation Plan" in result.output
    assert "Objective: Fix the bug." in result.output
    assert "High Severity" in result.output
    assert "###" not in result.output
    assert "**" not in result.output

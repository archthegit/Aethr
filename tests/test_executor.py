import pytest

from aethr.config import WorkflowConfig, WorkflowStep
from aethr.artifacts import StepArtifacts
from aethr.executor import (
    StepResult,
    WorkflowStepError,
    build_workflow_prompts,
    load_checkpoint,
    run_workflow,
    serialize_checkpoint,
    summarize_results,
)
from aethr.llm import CompletionResult, LLMError, UsageSummary


def test_run_workflow_returns_mock_step_results() -> None:
    config = WorkflowConfig(
        workflow="simple",
        roles={"first": "First step.", "second": "Second step."},
        models={"first": "openai:gpt-5.5", "second": "openai:gpt-5.5"},
        steps=[
            WorkflowStep(id="one", role="first"),
            WorkflowStep(id="two", role="second"),
        ],
    )

    results = run_workflow("do the thing", config)

    assert [result.step_id for result in results] == ["one", "two"]
    assert all("Mock model response." in result.content for result in results)
    assert results[0].metadata["role"] == "first"


def test_run_workflow_runs_each_configured_step_once() -> None:
    config = WorkflowConfig(
        workflow="explicit",
        roles={"planner": "Plan.", "reviewer": "Review."},
        models={"planner": "openai:gpt-5.5", "reviewer": "openai:gpt-5.5"},
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="review", role="reviewer"),
        ],
    )

    results = run_workflow("do the thing", config)

    assert [result.step_id for result in results] == ["plan", "review"]


def test_run_workflow_supports_resume_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    config = WorkflowConfig(
        workflow="resume",
        roles={"planner": "Plan.", "reviewer": "Review."},
        models={"planner": "openai:gpt-5.5", "reviewer": "openai:gpt-5.5"},
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="review", role="reviewer"),
        ],
    )
    previous_results = [
        StepResult(
            step_id="plan",
            content="seed plan",
            artifacts=StepArtifacts(
                changed_files=["src/app.py"],
                diff_stat=" src/app.py | 1 +",
                git_diff="diff --git a/src/app.py b/src/app.py\n+print('hi')\n",
            ),
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15, cost=0.01),
        )
    ]
    streamed_chunks: list[str] = []

    def fake_complete(self, prompt, on_chunk=None):
        if on_chunk is not None:
            on_chunk("chunk one")
            on_chunk("chunk two")
        return CompletionResult(
            content="reviewed output",
            usage=UsageSummary(prompt_tokens=20, completion_tokens=10, total_tokens=30, cost=0.02),
        )

    monkeypatch.setattr("aethr.executor.ModelClient.complete", fake_complete)

    results = run_workflow(
        "do the thing",
        config,
        previous_results=previous_results,
        on_step_chunk=lambda _step_id, chunk: streamed_chunks.append(chunk),
    )

    assert [result.step_id for result in results] == ["plan", "review"]
    assert results[0].content == "seed plan"
    assert results[1].content == "reviewed output"
    assert streamed_chunks == ["chunk one", "chunk two"]
    assert summarize_results(results) == "2 steps, 45 tokens, $0.03"


def test_run_workflow_routes_opencode_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    config = WorkflowConfig(
        workflow="agentic",
        roles={"implementer": "Implement."},
        models={"implementer": "openai:gpt-5.3-codex"},
        steps=[WorkflowStep(id="implement", role="implementer", backend="opencode")],
    )
    streamed_chunks: list[str] = []

    def fake_complete(self, prompt, on_chunk=None):
        if on_chunk is not None:
            on_chunk("open code chunk")
        return CompletionResult(
            content="agent changed files",
            usage=UsageSummary(prompt_tokens=0, completion_tokens=0, total_tokens=0, cost=0.0),
        )

    monkeypatch.setattr("aethr.agents.OpenCodeAgentClient.complete", fake_complete)

    results = run_workflow(
        "do the thing",
        config,
        on_step_chunk=lambda _step_id, chunk: streamed_chunks.append(chunk),
    )

    assert [result.step_id for result in results] == ["implement"]
    assert results[0].content == "agent changed files"
    assert streamed_chunks == ["open code chunk"]
    assert results[0].metadata["backend"] == "opencode"


def test_run_workflow_preserves_agent_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    config = WorkflowConfig(
        workflow="agentic",
        roles={"implementer": "Implement."},
        models={"implementer": "openai:gpt-5.3-codex"},
        steps=[WorkflowStep(id="implement", role="implementer", backend="opencode")],
    )

    def fake_complete(self, prompt, on_chunk=None):
        return type(
            "AgentCompletion",
            (),
            {
                "content": "agent changed files",
                "usage": UsageSummary(),
                "artifacts": type(
                    "Artifacts",
                    (),
                    {
                        "changed_files": ["src/app.py"],
                        "diff_stat": " src/app.py | 2 ++",
                        "git_diff": "diff --git a/src/app.py b/src/app.py\n+print('hi')\n",
                    },
                )(),
            },
        )()

    monkeypatch.setattr("aethr.agents.OpenCodeAgentClient.complete", fake_complete)

    results = run_workflow("do the thing", config)

    assert results[0].artifacts is not None
    assert results[0].artifacts.changed_files == ["src/app.py"]
    assert "print('hi')" in results[0].artifacts.git_diff


def test_build_workflow_prompts_does_not_call_models() -> None:
    config = WorkflowConfig(
        workflow="preview",
        roles={"planner": "Plan.", "reviewer": "Review."},
        models={"planner": "openai:gpt-5.5", "reviewer": "openai:gpt-5.5"},
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="review", role="reviewer", context=["file:MISSING.md"]),
        ],
    )

    prompts = build_workflow_prompts("do the thing", config)

    assert [prompt.step_id for prompt in prompts] == ["plan", "review"]
    assert prompts[0].metadata["model"] == "openai:gpt-5.5"
    assert prompts[1].metadata["context_sources"] == "1"
    assert "[simulated previous output from plan]" in prompts[1].prompt
    assert "[missing file:" in prompts[1].prompt


def test_run_workflow_emits_checkpoint_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    config = WorkflowConfig(
        workflow="fail-fast",
        roles={"planner": "Plan.", "reviewer": "Review."},
        models={"planner": "openai:gpt-5.5", "reviewer": "openai:gpt-5.5"},
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="review", role="reviewer"),
        ],
    )

    calls = {"count": 0}

    def fake_complete(self, prompt, on_chunk=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return type(
                "Completion",
                (),
                {
                    "content": "plan output",
                    "usage": UsageSummary(prompt_tokens=10, completion_tokens=4, total_tokens=14, cost=0.01),
                    "artifacts": StepArtifacts(
                        changed_files=["src/app.py"],
                        diff_stat=" src/app.py | 1 +",
                        git_diff="diff --git a/src/app.py b/src/app.py\n+print('hi')\n",
                    ),
                },
            )()
        raise LLMError("boom")

    monkeypatch.setattr("aethr.executor.ModelClient.complete", fake_complete)

    with pytest.raises(WorkflowStepError) as excinfo:
        run_workflow("do the thing", config)

    assert excinfo.value.step_id == "review"
    assert [result.step_id for result in excinfo.value.completed_results] == ["plan"]
    checkpoint = serialize_checkpoint(excinfo.value.completed_results)
    restored = load_checkpoint(checkpoint)
    assert restored[0].step_id == "plan"
    assert restored[0].artifacts is not None
    assert restored[0].artifacts.changed_files == ["src/app.py"]

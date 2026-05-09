from relay.config import WorkflowConfig, WorkflowStep
from relay.executor import build_workflow_prompts, run_workflow


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
    assert "[output from plan]" in prompts[1].prompt
    assert "[missing file:" in prompts[1].prompt

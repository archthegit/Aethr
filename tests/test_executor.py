from relay.config import ReviewLoopConfig, WorkflowConfig, WorkflowStep
from relay.executor import run_workflow


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


def test_review_loop_repeats_only_final_step() -> None:
    config = WorkflowConfig(
        workflow="loop",
        roles={"planner": "Plan.", "reviewer": "Review."},
        models={"planner": "openai:gpt-5.5", "reviewer": "openai:gpt-5.5"},
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="review", role="reviewer"),
        ],
        review_loop=ReviewLoopConfig(enabled=True, max_iterations=3),
    )

    results = run_workflow("do the thing", config)

    assert [result.step_id for result in results] == ["plan", "review", "review", "review"]
    assert [result.metadata["iteration"] for result in results] == ["1", "1", "2", "3"]

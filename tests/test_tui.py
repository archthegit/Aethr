from aethr.config import RepeatConfig, WorkflowConfig, WorkflowStep
from aethr.executor import StepPrompt, StepResult
from aethr.tui import build_step_detail_lines, build_workflow_map_lines


def test_workflow_map_lines_show_loop_and_state() -> None:
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
            WorkflowStep(
                id="implement",
                role="implementer",
                backend="opencode",
                history_visibility="latest",
            ),
            WorkflowStep(
                id="review",
                role="reviewer",
                history_visibility="latest",
                repeat=RepeatConfig(back_to="implement", until_review_pass=True, max_iterations=3),
            ),
        ],
    )
    previous_results = [StepResult(step_id="plan", content="planned")]

    lines = build_workflow_map_lines(config, previous_results)

    assert "1. plan" in lines[0]
    assert "done" in lines[0]
    assert "backend=opencode" in lines[1]
    assert "loop=implement→review x3" in lines[2]
    assert "current" in lines[1]


def test_step_detail_lines_clean_prompt_markdown() -> None:
    planned = StepPrompt(
        step_id="review",
        prompt="### Findings\n\n1. **High Severity**: Fix it.",
        metadata={"role": "reviewer", "model": "openai:gpt-4o-mini", "context_sources": "1"},
    )

    lines = build_step_detail_lines(planned, "### Live output\n\n**Chunk**", True, 60)
    rendered = "\n".join(lines)

    assert "Findings" in rendered
    assert "High Severity" in rendered
    assert "**" not in rendered
    assert "Live output:" in rendered

from aethr.config import RepeatConfig, WorkflowConfig, WorkflowStep
from aethr.executor import StepPrompt, StepResult
from aethr.tui import (
    ChatMessage,
    TuiState,
    build_chat_lines,
    build_step_detail_lines,
    build_stream_lines,
    build_workflow_map_lines,
    compose_task_with_chat,
    _rewind_and_run_current_step,
)


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


def test_step_detail_lines_default_to_prompt_summary() -> None:
    planned = StepPrompt(
        step_id="review",
        prompt="### Findings\n\n1. **High Severity**: Fix it.\n2. **Low Severity**: Add a test.\n\nMore details.",
        metadata={"role": "reviewer", "model": "openai:gpt-4o-mini", "context_sources": "1"},
    )

    lines = build_step_detail_lines(planned, "", False, 60)
    rendered = "\n".join(lines)

    assert "Prompt summary:" in rendered
    assert "Findings" in rendered
    assert "More details" not in rendered
    assert "…" in rendered
    assert "Press p for the full prompt." in rendered
    assert "**" not in rendered


def test_compose_task_with_chat_adds_recent_notes() -> None:
    task = "fix the auth issue"
    chat_history = [
        ChatMessage(role="user", text="Don't touch oauth.py."),
        ChatMessage(role="assistant", text="I can do a minimal fix."),
    ]

    composed = compose_task_with_chat(task, chat_history)

    assert "fix the auth issue" in composed
    assert "Session steering:" in composed
    assert "You: Don't touch oauth.py." in composed
    assert "Aethr: I can do a minimal fix." in composed


def test_build_chat_lines_show_prompt_and_input() -> None:
    config = WorkflowConfig(
        workflow="tui",
        roles={"reviewer": "Review."},
        models={"reviewer": "openai:gpt-4o-mini"},
        steps=[WorkflowStep(id="review", role="reviewer")],
    )
    state = type("State", (), {})()
    state.task = "fix the bug"
    state.config = config
    state.results = []
    state.stream_enabled = True
    state.prompt_visible = True
    state.status = "Type a steering note and press Enter to run the current step."
    state.current_step = None
    state.live_output = ""
    state.last_result = None
    state.chat_history = [ChatMessage(role="user", text="avoid snapshot changes")]
    state.input_buffer = "review the auth flow"

    lines = build_chat_lines(state, 80)

    rendered = "\n".join(lines)
    assert "avoid snapshot changes" in rendered
    assert "Steering:" in rendered
    assert "Compose:" in rendered
    assert "review the auth flow" in rendered


def test_rewind_and_run_current_step_reruns_last_completed_step(monkeypatch) -> None:
    config = WorkflowConfig(
        workflow="tui",
        roles={"reviewer": "Review.", "implementer": "Implement."},
        models={"reviewer": "openai:gpt-4o-mini", "implementer": "openai:gpt-5.3-codex"},
        steps=[
            WorkflowStep(id="review", role="reviewer"),
            WorkflowStep(id="implement", role="implementer", backend="opencode"),
        ],
    )
    state = TuiState(task="fix the bug", config=config)
    state.results = [
        StepResult(step_id="review", content="old result"),
        StepResult(step_id="implement", content="new result"),
    ]
    state.last_result = state.results[-1]

    called: list[int] = []

    def fake_run_step_at_index(stdscr, current_state, step_index):
        called.append(step_index)
        return False

    monkeypatch.setattr("aethr.tui._run_step_at_index", fake_run_step_at_index)

    _rewind_and_run_current_step(None, state)

    assert len(state.results) == 1
    assert state.results[0].content == "old result"
    assert state.last_result.content == "old result"
    assert called == [1]


def test_build_stream_lines_show_live_output() -> None:
    config = WorkflowConfig(
        workflow="tui",
        roles={"reviewer": "Review."},
        models={"reviewer": "openai:gpt-4o-mini"},
        steps=[WorkflowStep(id="review", role="reviewer")],
    )
    state = TuiState(task="fix the bug", config=config, live_output="Streaming implement...\nDone.")
    state.status = "Streaming review..."

    lines = build_stream_lines(state, 80)

    rendered = "\n".join(lines)
    assert "OpenCode output:" in rendered
    assert "Streaming implement..." in rendered
    assert "Done." in rendered

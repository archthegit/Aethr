from aethr.config import WorkflowConfig, WorkflowStep
from aethr.executor import StepResult
from aethr.repl import (
    ReplState,
    SteeringMessage,
    _rewind_and_run_last_step,
    compose_task_with_steering,
    run_repl_workflow,
)


def test_compose_task_with_steering_adds_recent_notes() -> None:
    task = "fix the auth issue"
    steering_history = [
        SteeringMessage(role="user", text="Don't touch oauth.py."),
        SteeringMessage(role="assistant", text="I can do a minimal fix."),
    ]

    composed = compose_task_with_steering(task, steering_history)

    assert "fix the auth issue" in composed
    assert "Session steering:" in composed
    assert "You: Don't touch oauth.py." in composed
    assert "Aethr: I can do a minimal fix." in composed


def test_rewind_and_run_last_step_reruns_last_completed_step(monkeypatch) -> None:
    config = WorkflowConfig(
        workflow="repl",
        roles={"planner": "Plan.", "implementer": "Implement.", "reviewer": "Review."},
        models={
            "planner": "openai:gpt-4o-mini",
            "implementer": "openai:gpt-5.3-codex",
            "reviewer": "openai:gpt-4o-mini",
        },
        steps=[
            WorkflowStep(id="plan", role="planner"),
            WorkflowStep(id="implement", role="implementer", backend="opencode"),
            WorkflowStep(id="review", role="reviewer"),
        ],
    )
    state = ReplState(task="fix the bug", config=config)
    state.results = [
        StepResult(step_id="plan", content="planned"),
        StepResult(step_id="implement", content="implemented"),
        StepResult(step_id="review", content="reviewed"),
    ]
    state.last_result = state.results[-1]

    called: list[int] = []

    def fake_run_step_at_index(current_state, step_index):
        called.append(step_index)
        return False

    monkeypatch.setattr("aethr.repl._run_step_at_index", fake_run_step_at_index)

    _rewind_and_run_last_step(state)

    assert len(state.results) == 2
    assert state.results[-1].step_id == "implement"
    assert state.last_result.step_id == "implement"
    assert called == [2]


def test_run_repl_workflow_bootstraps_first_step(monkeypatch) -> None:
    config = WorkflowConfig(
        workflow="repl",
        roles={"reviewer": "Review."},
        models={"reviewer": "openai:gpt-4o-mini"},
        steps=[WorkflowStep(id="review", role="reviewer")],
    )
    calls: list[str] = []

    monkeypatch.setattr("aethr.repl.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("aethr.repl.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("aethr.repl.terminal_session.render_workflow_overview", lambda *args, **kwargs: None)
    monkeypatch.setattr("aethr.repl.terminal_session.set_stream_rendering_enabled", lambda *args, **kwargs: None)
    monkeypatch.setattr("aethr.repl.terminal_session.console.print", lambda *args, **kwargs: None)
    monkeypatch.setattr("aethr.repl.terminal_session.console.input", lambda *args, **kwargs: "/quit")

    def fake_run_current_step(state):
        calls.append(state.task)
        state.last_result = StepResult(step_id="review", content="done")
        state.results.append(state.last_result)
        return False

    monkeypatch.setattr("aethr.repl._run_current_step", fake_run_current_step)

    results = run_repl_workflow("review my current changes", config, bootstrap_first_step=True)

    assert calls == ["review my current changes"]
    assert len(results) == 1
    assert results[0].content == "done"

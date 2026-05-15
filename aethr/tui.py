"""Full-screen terminal UI for Aethr workflows."""

from __future__ import annotations

import curses
import sys
from dataclasses import dataclass, field
from textwrap import wrap

from aethr.artifacts import format_artifact_summary
from aethr.config import WorkflowConfig
from aethr.executor import (
    StepPrompt,
    StepResult,
    build_step_prompt,
    run_repeat_block,
    run_step,
    workflow_cursor,
)
from aethr.render import clean_display_text


@dataclass
class TuiState:
    """Mutable state for one TUI workflow session."""

    task: str
    config: WorkflowConfig
    results: list[StepResult] = field(default_factory=list)
    stream_enabled: bool = True
    prompt_visible: bool = True
    phase: str = "preview"
    status: str = "Press r to run, p to toggle prompt, q to quit."
    current_step: StepPrompt | None = None
    live_output: str = ""
    last_result: StepResult | None = None


def run_tui_workflow(
    task: str,
    config: WorkflowConfig,
    previous_results: list[StepResult] | None = None,
    *,
    stream: bool = True,
) -> list[StepResult]:
    """Run a workflow inside a full-screen terminal UI."""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("aethr tui requires an interactive terminal")

    state = TuiState(task=task, config=config, results=list(previous_results or []), stream_enabled=stream)
    curses.wrapper(_run_curses_session, state)
    return state.results


def build_workflow_map_lines(config: WorkflowConfig, previous_results: list[StepResult]) -> list[str]:
    """Build workflow-map lines for rendering and testing."""

    completed = {result.step_id for result in previous_results}
    current_index = workflow_cursor(list(previous_results), config)
    lines = []
    for index, step in enumerate(config.steps):
        if step.id in completed:
            state = "done"
        elif index == current_index:
            state = "current"
        else:
            state = "pending"

        backend = step.backend if step.backend != "model" else "model"
        permissions = ""
        if step.backend == "opencode":
            permissions = " unsafe" if step.unsafe_permissions else " safe"
        loop = ""
        if step.repeat is not None:
            loop = f" loop={step.repeat.back_to}→{step.id} x{step.repeat.max_iterations}"
        lines.append(
            f"{index + 1}. {step.id} | role={step.role} | backend={backend}{permissions} "
            f"| model={config.models.get(step.role, 'mock')} | ctx={len(step.context)} "
            f"| hist={step.history_visibility}{loop} | {state}"
        )
    return lines


def build_step_detail_lines(
    planned: StepPrompt,
    live_output: str,
    prompt_visible: bool,
    width: int,
    result: StepResult | None = None,
) -> list[str]:
    """Build detail pane lines for the current step."""

    backend = planned.metadata.get("backend", "model")
    permissions = planned.metadata.get("permissions")
    header = (
        f"role={planned.metadata['role']} model={planned.metadata['model']}"
        f"{f' backend={backend}' if backend != 'model' else ''}"
        f" context={planned.metadata['context_sources']}"
    )
    if permissions:
        header += f" permissions={permissions}"

    lines = [header, ""]
    if prompt_visible:
        lines.append("Prompt:")
        lines.extend(_wrap_block(clean_display_text(planned.prompt), width))
        lines.append("")

    lines.append("Live output:")
    output = clean_display_text(live_output).strip()
    if output:
        lines.extend(_wrap_block(output, width))
    else:
        lines.append("(waiting for output)")
    if result is not None and result.artifacts is not None:
        lines.append("")
        lines.append("Artifacts:")
        lines.extend(_wrap_block(format_artifact_summary(result.artifacts), width))
    return lines


def build_status_lines(state: TuiState) -> list[str]:
    """Build footer lines for the current state."""

    lines = [state.status]
    lines.append("Keys: r run | p prompt | n next | q quit")
    if state.last_result is not None:
        result = state.last_result
        summary = f"{result.step_id} complete | role={result.metadata.get('role', 'unknown')}"
        backend = result.metadata.get("backend", "model")
        if backend != "model":
            summary += f" backend={backend}"
        permissions = result.metadata.get("permissions")
        if permissions:
            summary += f" permissions={permissions}"
        if result.usage is not None and (result.usage.total_tokens or result.usage.cost):
            summary += f" | {result.usage.total_tokens} tokens ${result.usage.cost:.2f}"
        lines.append(summary)
    return lines


def _run_curses_session(stdscr: curses.window, state: TuiState) -> None:
    """Drive the curses event loop."""

    curses.curs_set(0)
    curses.use_default_colors()
    _init_colors()
    stdscr.keypad(True)
    stdscr.nodelay(False)

    while True:
        step_index = workflow_cursor(state.results, state.config)
        if step_index >= len(state.config.steps):
            state.status = "Workflow complete. Press q to quit."
            _render(stdscr, state, None)
            if _read_key(stdscr) in {"q", "Q"}:
                return
            continue

        step = state.config.steps[step_index]
        planned = build_step_prompt(state.task, step, state.config, state.results)
        state.current_step = planned
        state.phase = "preview"
        state.live_output = ""
        state.status = "Press r to run, p to toggle prompt, q to quit."
        _render(stdscr, state, planned)

        while True:
            key = _read_key(stdscr)
            if key in {"q", "Q"}:
                state.status = "Session stopped."
                _render(stdscr, state, planned)
                return
            if key in {"p", "P"}:
                state.prompt_visible = not state.prompt_visible
                _render(stdscr, state, planned)
                continue
            if key in {"r", "R", "\n", "\r", " "}:
                break

        state.phase = "running"
        state.status = f"Running {planned.step_id}..."
        _render(stdscr, state, planned)
        result = run_step(
            state.task,
            step,
            state.config,
            state.results,
            planned=planned,
            on_chunk=(lambda _step_id, chunk: _on_step_chunk(stdscr, state, planned, chunk)) if state.stream_enabled else None,
        )
        state.results.append(result)
        state.last_result = result
        state.live_output = result.content
        state.phase = "idle"
        state.status = f"{planned.step_id} complete. Press n for next step or q to quit."
        _render(stdscr, state, planned)

        if step.repeat is not None:
            state.status = f"Running repeat loop for {planned.step_id}..."
            _render(stdscr, state, planned)
            state.results = run_repeat_block(
                state.task,
                step_index,
                step,
                state.config,
                state.results,
                on_step_start=lambda _index, _total, replay_planned: _on_step_start(stdscr, state, replay_planned),
                on_step_chunk=(lambda _step_id, chunk: _on_step_chunk(stdscr, state, planned, chunk)) if state.stream_enabled else None,
                on_step_result=lambda result: _on_step_result(stdscr, state, result),
            )
            state.last_result = state.results[-1]
            state.live_output = state.last_result.content
            state.status = f"{planned.step_id} loop complete. Press n for next step or q to quit."
            _render(stdscr, state, planned)

        while True:
            key = _read_key(stdscr)
            if key in {"q", "Q"}:
                state.status = "Session stopped."
                _render(stdscr, state, planned)
                return
            if key in {"p", "P"}:
                state.prompt_visible = not state.prompt_visible
                _render(stdscr, state, planned)
                continue
            if key in {"n", "N", "\n", "\r", " "}:
                break


def _on_step_chunk(stdscr: curses.window, state: TuiState, planned: StepPrompt, chunk: str) -> None:
    """Append streamed output and repaint the screen."""

    state.live_output += chunk
    state.phase = "running"
    state.status = f"Streaming {planned.step_id}..."
    _render(stdscr, state, planned)


def _on_step_start(stdscr: curses.window, state: TuiState, planned: StepPrompt) -> None:
    """Capture the step that is currently executing."""

    state.current_step = planned
    state.status = f"Running {planned.step_id}..."
    _render(stdscr, state, planned)


def _on_step_result(stdscr: curses.window, state: TuiState, result: StepResult) -> None:
    """Capture the latest result and repaint the screen."""

    state.last_result = result
    state.live_output = result.content
    state.phase = "idle"
    _render(stdscr, state, state.current_step)


def _render(stdscr: curses.window, state: TuiState, planned: StepPrompt | None) -> None:
    """Render the full-screen TUI."""

    stdscr.erase()
    height, width = stdscr.getmaxyx()
    title = f"Aethr | {state.config.workflow} | {state.task}"
    _draw_header(stdscr, 0, 0, width, title)

    map_lines = build_workflow_map_lines(state.config, state.results)
    map_height = max(6, min(len(map_lines) + 2, max(6, height // 3)))
    detail_height = max(8, height - map_height - 4)

    _draw_box(
        stdscr,
        1,
        0,
        map_height,
        width,
        "Workflow map",
        map_lines,
        color=curses.color_pair(1),
    )

    detail_lines = ["No step selected."]
    if planned is not None:
        detail_lines = build_step_detail_lines(
            planned,
            state.live_output,
            state.prompt_visible,
            max(20, width - 4),
            result=state.last_result,
        )
    _draw_box(
        stdscr,
        map_height + 1,
        0,
        detail_height,
        width,
        "Current step",
        detail_lines,
        color=curses.color_pair(2),
    )

    footer_lines = build_status_lines(state)
    _draw_box(
        stdscr,
        height - 3,
        0,
        3,
        width,
        "Status",
        footer_lines,
        color=curses.color_pair(3),
        border=False,
    )
    stdscr.refresh()


def _draw_header(stdscr: curses.window, y: int, x: int, width: int, text: str) -> None:
    """Draw a compact title bar."""

    stdscr.attron(curses.A_BOLD)
    stdscr.addnstr(y, x, text, width - 1)
    stdscr.attroff(curses.A_BOLD)


def _draw_box(
    stdscr: curses.window,
    y: int,
    x: int,
    height: int,
    width: int,
    title: str,
    lines: list[str],
    *,
    color: int = 0,
    border: bool = True,
) -> None:
    """Draw a boxed region with clipped text."""

    max_rows, max_cols = stdscr.getmaxyx()
    if y < 0 or x < 0 or height <= 0 or width <= 0:
        return
    if y + height > max_rows or x + width > max_cols:
        return

    win = stdscr.derwin(height, width, y, x)
    win.erase()

    if border:
        win.attron(color)
        win.attron(curses.A_BOLD)
        win.box()
        win.attroff(curses.A_BOLD)
        win.attroff(color)
        win.attron(color)
        win.addnstr(0, 2, f" {title} ", max(0, width - 4))
        win.attroff(color)
        content_y = 1
        content_x = 2
        available_width = max(1, width - 4)
        max_row = height - 2
    else:
        win.addnstr(0, 0, title, width - 1)
        content_y = 1
        content_x = 0
        available_width = max(1, width - 2)
        max_row = height - 1

    row = content_y
    for line in lines:
        if row > max_row:
            break
        for wrapped in _wrap_block(line, available_width) or [""]:
            if row > max_row:
                break
            win.addnstr(row, content_x, wrapped, available_width)
            row += 1


def _wrap_block(text: str, width: int) -> list[str]:
    """Wrap a paragraph into terminal-width lines."""

    cleaned = clean_display_text(text)
    if not cleaned:
        return []
    lines: list[str] = []
    for paragraph in cleaned.splitlines():
        if not paragraph:
            lines.append("")
            continue
        lines.extend(wrap(paragraph, width=width) or [""])
    return lines


def _init_colors() -> None:
    """Initialize a small palette for the TUI."""

    if not curses.has_colors():
        return
    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_MAGENTA, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)


def _read_key(stdscr: curses.window) -> str:
    """Read one key from the terminal."""

    code = stdscr.getch()
    if code in (curses.KEY_ENTER, 10, 13):
        return "\n"
    if 0 <= code <= 255:
        return chr(code)
    return ""

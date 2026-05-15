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


@dataclass(frozen=True)
class ChatMessage:
    """One user or assistant message in the workflow steering log."""

    role: str
    text: str


@dataclass
class TuiState:
    """Mutable state for one TUI workflow session."""

    task: str
    config: WorkflowConfig
    results: list[StepResult] = field(default_factory=list)
    stream_enabled: bool = True
    prompt_visible: bool = False
    status: str = "Type a steering note and press Enter to re-run the current step."
    current_step: StepPrompt | None = None
    live_output: str = ""
    last_result: StepResult | None = None
    chat_history: list[ChatMessage] = field(default_factory=list)
    input_buffer: str = ""


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


def compose_task_with_chat(task: str, chat_history: list[ChatMessage], *, limit: int = 8) -> str:
    """Add recent steering notes to the task context for prompt building."""

    if not chat_history:
        return task

    lines = [task, "", "Session steering:"]
    for message in chat_history[-limit:]:
        label = "You" if message.role == "user" else "Aethr"
        lines.append(f"{label}: {clean_display_text(message.text).strip()}")
    return "\n".join(lines)


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
    else:
        lines.append("Prompt summary:")
        lines.extend(_wrap_block(_prompt_summary(planned.prompt), width))
        lines.append("")
        lines.append("Press p for the full prompt.")
    return lines


def build_stream_lines(state: TuiState, width: int) -> list[str]:
    """Build the live output pane lines."""

    lines = [state.status, ""]
    lines.append("OpenCode output:")
    output = clean_display_text(state.live_output).strip()
    if output:
        lines.extend(_wrap_block(output, width))
    else:
        lines.append("(waiting for output)")

    if state.last_result is not None and state.last_result.artifacts is not None:
        lines.append("")
        lines.append("Artifacts:")
        lines.extend(_wrap_block(format_artifact_summary(state.last_result.artifacts), width))
    return lines


def build_chat_lines(state: TuiState, width: int) -> list[str]:
    """Build the transcript and composer lines for the bottom steering pane."""

    lines = [state.status, ""]
    lines.append("Keys: Enter send/run | p prompt | /clear | /quit")
    lines.append("")
    transcript = state.chat_history[-6:]
    if transcript:
        lines.append("Steering:")
        for message in transcript:
            label = "You" if message.role == "user" else "Aethr"
            lines.append(f"{label}:")
            lines.extend(_wrap_block(message.text, width))
            lines.append("")
    else:
        lines.append("Steering:")
        lines.append("Type a note and press Enter to steer the current step.")
        lines.append("")

    lines.append("Compose:")
    lines.append(state.input_buffer or "")
    return lines


def _run_curses_session(stdscr: curses.window, state: TuiState) -> None:
    """Drive the curses event loop."""

    curses.curs_set(1)
    curses.use_default_colors()
    stdscr.keypad(True)

    while True:
        planned = _planned_step(state)
        _render(stdscr, state, planned)
        key = _read_key(stdscr)
        if _handle_key(stdscr, state, planned, key):
            return


def _planned_step(state: TuiState) -> StepPrompt | None:
    """Build the prompt for the current workflow step with chat context."""

    step_index = workflow_cursor(state.results, state.config)
    if step_index >= len(state.config.steps):
        state.current_step = None
        state.status = "Workflow complete. Type /quit or q to exit."
        return None

    step = state.config.steps[step_index]
    task = compose_task_with_chat(state.task, state.chat_history)
    planned = build_step_prompt(task, step, state.config, state.results)
    state.current_step = planned
    return planned


def _handle_key(stdscr: curses.window, state: TuiState, planned: StepPrompt | None, key: str) -> bool:
    """Handle one keypress. Return True to exit."""

    if key in {"\x03", "\x04"}:
        state.status = "Session stopped."
        _render(stdscr, state, planned)
        return True

    if key in {"\b", "\x7f", curses.KEY_BACKSPACE}:
        if state.input_buffer:
            state.input_buffer = state.input_buffer[:-1]
            state.status = "Editing note."
        _render(stdscr, state, planned)
        return False

    if key in {"\n", "\r"}:
        return _submit_input(stdscr, state, planned)

    if key in {"p", "P"} and not state.input_buffer:
        state.prompt_visible = not state.prompt_visible
        state.status = "Prompt preview toggled."
        _render(stdscr, state, planned)
        return False

    if key and len(key) == 1 and key.isprintable():
        state.input_buffer += key
        state.status = "Type Enter to send the steering note."
        _render(stdscr, state, planned)
        return False

    if key in {"q", "Q"} and not state.input_buffer:
        state.status = "Session stopped."
        _render(stdscr, state, planned)
        return True

    return False


def _submit_input(stdscr: curses.window, state: TuiState, planned: StepPrompt | None) -> bool:
    """Submit the current composer buffer or run the current step."""

    text = state.input_buffer.strip()
    state.input_buffer = ""

    if text.startswith("/"):
        command = text[1:].strip().lower()
        if command in {"quit", "q", "exit"}:
            state.status = "Session stopped."
            _render(stdscr, state, planned)
            return True
        if command in {"prompt", "p"}:
            state.prompt_visible = not state.prompt_visible
            state.status = "Prompt preview toggled."
            _render(stdscr, state, planned)
            return False
        if command in {"clear", "c"}:
            state.chat_history.clear()
            state.status = "Steering cleared."
            _render(stdscr, state, planned)
            return False
        state.status = f"Unknown command: {text}"
        _render(stdscr, state, planned)
        return False

    if text:
        state.chat_history.append(ChatMessage(role="user", text=text))
        state.status = "Steering note added. Re-running the last completed step..."
        _render(stdscr, state, planned)
        return _rewind_and_run_current_step(stdscr, state)

    if planned is not None:
        state.status = "Running the current step..."
        _render(stdscr, state, planned)
        return _run_current_step(stdscr, state)

    state.status = "Workflow complete. Type /quit or q to exit."
    _render(stdscr, state, planned)
    return False


def _run_current_step(stdscr: curses.window, state: TuiState) -> bool:
    """Run the currently selected step with the accumulated steering context."""

    step_index = workflow_cursor(state.results, state.config)
    return _run_step_at_index(stdscr, state, step_index)


def _run_step_at_index(stdscr: curses.window, state: TuiState, step_index: int) -> bool:
    """Run a specific workflow step by index."""

    if step_index >= len(state.config.steps):
        state.status = "Workflow complete. Type /quit or q to exit."
        _render(stdscr, state, None)
        return False

    step = state.config.steps[step_index]
    task = compose_task_with_chat(state.task, state.chat_history)
    planned = build_step_prompt(task, step, state.config, state.results)
    state.current_step = planned
    state.live_output = ""
    state.status = f"Running {planned.step_id}..."
    _render(stdscr, state, planned)
    result = run_step(
        task,
        step,
        state.config,
        state.results,
        planned=planned,
        on_chunk=(lambda _step_id, chunk: _on_step_chunk(stdscr, state, planned, chunk)) if state.stream_enabled else None,
    )
    state.results.append(result)
    state.last_result = result
    state.live_output = result.content
    state.chat_history.append(ChatMessage(role="assistant", text=_summarize_result_for_chat(result)))

    if step.repeat is not None:
        state.status = f"Running repeat loop for {planned.step_id}..."
        _render(stdscr, state, planned)
        state.results = run_repeat_block(
            task,
            step_index,
            step,
            state.config,
            state.results,
            on_step_start=lambda _index, _total, replay_planned: _on_step_start(stdscr, state, replay_planned),
            on_step_chunk=(lambda _step_id, chunk: _on_step_chunk(stdscr, state, planned, chunk)) if state.stream_enabled else None,
            on_step_result=lambda replay_result: _on_step_result(stdscr, state, replay_result),
        )
        state.last_result = state.results[-1]
        state.live_output = state.last_result.content
        state.chat_history.append(ChatMessage(role="assistant", text=_summarize_result_for_chat(state.last_result)))

    state.status = "Step complete. Type another steering note or press Enter to continue."
    _render(stdscr, state, planned)
    return False


def _rewind_and_run_current_step(stdscr: curses.window, state: TuiState) -> bool:
    """Rewind one completed step and run it again with the new steering note."""

    step_id = state.last_result.step_id if state.last_result is not None else None
    if state.results:
        state.results.pop()
    state.last_result = state.results[-1] if state.results else None

    if step_id is None:
        state.status = "No completed step available to re-run."
        _render(stdscr, state, state.current_step)
        return False

    try:
        step_index = next(index for index, step in enumerate(state.config.steps) if step.id == step_id)
    except StopIteration:
        state.status = f"Unknown step to re-run: {step_id}"
        _render(stdscr, state, state.current_step)
        return False

    return _run_step_at_index(stdscr, state, step_index)


def _summarize_result_for_chat(result: StepResult) -> str:
    """Render a compact assistant reply for the chat transcript."""

    body = clean_display_text(result.content).strip()
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if result.artifacts is not None and result.artifacts.changed_files:
        files = ", ".join(result.artifacts.changed_files[:3])
        if len(result.artifacts.changed_files) > 3:
            files += ", …"
        return f"{result.step_id} complete. Changed files: {files}"
    if first_line:
        return f"{result.step_id} complete. {truncate_text(first_line, 160)}"
    return f"{result.step_id} complete."


def _on_step_chunk(stdscr: curses.window, state: TuiState, planned: StepPrompt, chunk: str) -> None:
    """Append streamed output and repaint the screen."""

    state.live_output += chunk
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
    _render(stdscr, state, state.current_step)


def _render(stdscr: curses.window, state: TuiState, planned: StepPrompt | None) -> None:
    """Render the full-screen TUI."""

    stdscr.erase()
    height, width = stdscr.getmaxyx()
    title = f"Aethr | {state.config.workflow} | {state.task}"
    _draw_header(stdscr, 0, 0, width, title)

    map_lines = build_workflow_map_lines(state.config, state.results)
    map_height = max(6, min(len(map_lines) + 2, max(6, height // 3)))
    chat_height = max(7, max(7, height // 5))
    stream_height = max(7, max(7, height // 4))
    detail_height = max(8, height - map_height - stream_height - chat_height - 4)

    _draw_box(
        stdscr,
        1,
        0,
        map_height,
        width,
        "Workflow map",
        map_lines,
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
    )

    stream_y = map_height + detail_height + 2
    stream_title = "Streaming OpenCode output"
    if planned is not None:
        stream_title = f"Streaming {planned.step_id}…"

    _draw_box(
        stdscr,
        stream_y,
        0,
        stream_height,
        width,
        stream_title,
        build_stream_lines(state, max(20, width - 4)),
    )

    _draw_chat_box(
        stdscr,
        stream_y + stream_height + 1,
        0,
        height - (stream_y + stream_height + 1),
        width,
        state,
    )
    stdscr.refresh()
    _place_input_cursor(stdscr, state, stream_y + stream_height + 1, height - (stream_y + stream_height + 1), width)


def _draw_chat_box(
    stdscr: curses.window,
    y: int,
    x: int,
    height: int,
    width: int,
    state: TuiState,
) -> None:
    """Draw the bottom chat composer and transcript."""

    if height <= 0 or width <= 0:
        return
    if y + height > stdscr.getmaxyx()[0] or x + width > stdscr.getmaxyx()[1]:
        return

    win = stdscr.derwin(height, width, y, x)
    win.erase()
    win.bkgd(" ", curses.A_REVERSE)
    win.attron(curses.A_REVERSE)
    win.attron(curses.A_DIM)
    win.box()
    win.addnstr(0, 2, " Steering ", max(0, width - 4))
    win.attroff(curses.A_DIM)
    win.attroff(curses.A_REVERSE)

    inner_width = max(1, width - 4)
    transcript_height = max(1, height - 3)
    lines = build_chat_lines(state, inner_width)
    transcript = lines[:-2] if len(lines) >= 2 else lines

    row = 1
    for line in transcript:
        if row > transcript_height:
            break
        for wrapped in _wrap_block(line, inner_width) or [""]:
            if row > transcript_height:
                break
            win.addnstr(row, 2, wrapped, inner_width)
            row += 1

    compose_row = height - 2
    compose_text = f"Compose: {state.input_buffer}"
    win.attron(curses.A_BOLD)
    win.addnstr(compose_row, 2, compose_text, inner_width)
    win.attroff(curses.A_BOLD)


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


def _prompt_summary(prompt: str, line_limit: int = 3) -> str:
    """Build a short prompt summary for the collapsed prompt pane."""

    lines = [line for line in clean_display_text(prompt).splitlines() if line.strip()]
    if not lines:
        return "(empty prompt)"
    summary = "\n".join(lines[:line_limit])
    if len(lines) > line_limit:
        summary += "\n…"
    return summary


def _place_input_cursor(stdscr: curses.window, state: TuiState, y: int, height: int, width: int) -> None:
    """Place the cursor at the end of the composer line."""

    if height <= 0 or width <= 0:
        return
    if y + height > stdscr.getmaxyx()[0] or width < 12:
        return
    row = y + height - 2
    cursor_x = min(width - 2, 2 + len("Compose: ") + len(state.input_buffer))
    stdscr.move(row, cursor_x)


def truncate_text(text: str, limit: int) -> str:
    """Trim text to a readable length."""

    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _read_key(stdscr: curses.window) -> str:
    """Read one key from the terminal."""

    code = stdscr.getch()
    if code in (curses.KEY_ENTER, 10, 13):
        return "\n"
    if code in (curses.KEY_BACKSPACE, 127, 8):
        return "\b"
    if 0 <= code <= 255:
        return chr(code)
    return ""

"""Explicit in-memory context collection for workflow steps."""

from __future__ import annotations

import subprocess
from pathlib import Path


MAX_CONTEXT_CHARS = 40_000


def collect_context(
    sources: list[str],
    root: Path | str = ".",
    latest_diff: str | None = None,
) -> str:
    """Collect user-declared context sources into prompt text."""

    if not sources:
        return "No explicit context declared."

    project_root = Path(root)
    remaining = MAX_CONTEXT_CHARS
    blocks: list[str] = []

    def collect_source(source: str) -> str:
        """Collect one supported context source."""

        if source == "git_diff":
            return context_block(source, read_git_diff(project_root))
        if source == "latest_diff":
            return context_block(source, latest_diff or "[latest diff unavailable]")
        if source.startswith("file:"):
            path = source.removeprefix("file:")
            resolved = relative_path(project_root, path)
            if resolved is None:
                return context_block(source, f"[context path must be relative to project root: {path}]")
            return context_block(source, read_file(resolved))
        if source.startswith("glob:"):
            pattern = source.removeprefix("glob:")
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                return context_block(source, f"[glob pattern must be relative to project root: {pattern}]")
            return context_block(source, read_glob(project_root, pattern))
        return context_block(source, f"[unsupported context source: {source}]")

    for source in sources:
        block = collect_source(source)
        trimmed, remaining = trim_to_budget(block, remaining)
        blocks.append(trimmed)
        if remaining <= 0:
            blocks.append("[context truncated: limit reached]")
            break

    return "\n\n".join(blocks)


def read_git_diff(root: Path) -> str:
    """Return the current git diff or a clear placeholder."""

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--no-ext-diff"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return f"[git diff unavailable: {exc}]"

    if result.returncode != 0:
        message = result.stderr.strip() or "not a git repository"
        return f"[git diff unavailable: {message}]"
    if not result.stdout.strip():
        return "[git diff is empty]"
    return result.stdout.rstrip()


def read_file(path: Path) -> str:
    """Read a UTF-8 text file or return a placeholder."""

    if not path.exists():
        return f"[missing file: {path}]"
    if not path.is_file():
        return f"[not a file: {path}]"
    try:
        return path.read_text(encoding="utf-8").rstrip()
    except UnicodeDecodeError:
        return f"[skipped non-UTF-8 file: {path}]"
    except OSError as exc:
        return f"[unreadable file: {path}: {exc}]"


def read_glob(root: Path, pattern: str) -> str:
    """Read UTF-8 text files matching a glob pattern."""

    matches = sorted(path for path in root.glob(pattern) if path.is_file())
    if not matches:
        return f"[no files matched: {pattern}]"

    blocks = []
    remaining = MAX_CONTEXT_CHARS
    for path in matches:
        block = context_block(str(path.relative_to(root)), read_file(path))
        trimmed, remaining = trim_to_budget(block, remaining)
        blocks.append(trimmed)
        if remaining <= 0:
            blocks.append("[glob context truncated: limit reached]")
            break
    return "\n\n".join(blocks)


def context_block(name: str, content: str) -> str:
    """Format one context block."""

    return f"--- {name} ---\n{content.rstrip()}"


def relative_path(root: Path, value: str) -> Path | None:
    """Return a root-relative path, rejecting absolute or parent traversal."""

    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return root / path


def trim_to_budget(content: str, remaining: int) -> tuple[str, int]:
    """Trim content to the remaining context character budget."""

    if remaining <= 0:
        return "", 0
    if len(content) <= remaining:
        return content, remaining - len(content)
    marker = "\n[context truncated]"
    keep = max(0, remaining - len(marker))
    return content[:keep].rstrip() + marker, 0

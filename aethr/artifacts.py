"""Structured artifacts produced by implementation steps."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StepArtifacts:
    """Worktree evidence captured from an implementation step."""

    changed_files: list[str] = field(default_factory=list)
    diff_stat: str = ""
    git_diff: str = ""


def format_artifact_block(artifacts: StepArtifacts, diff_limit: int = 12_000) -> str:
    """Render artifacts as prompt-ready text."""

    blocks: list[str] = []
    if artifacts.changed_files:
        blocks.append("Changed files:\n" + "\n".join(f"- {path}" for path in artifacts.changed_files))
    if artifacts.diff_stat.strip():
        blocks.append("Diff stat:\n" + artifacts.diff_stat.rstrip())
    if artifacts.git_diff.strip():
        blocks.append("Diff:\n" + truncate_text(artifacts.git_diff, diff_limit))
    return "\n\n".join(blocks) if blocks else "[no artifacts]"


def format_artifact_summary(artifacts: StepArtifacts, diff_limit: int = 6_000) -> str:
    """Render a compact terminal-facing artifact summary."""

    blocks: list[str] = []
    if artifacts.changed_files:
        blocks.append("Changed files:\n" + "\n".join(f"- {path}" for path in artifacts.changed_files))
    if artifacts.diff_stat.strip():
        blocks.append("Diff stat:\n" + artifacts.diff_stat.rstrip())
    if artifacts.git_diff.strip():
        blocks.append("Diff preview:\n" + truncate_text(artifacts.git_diff, diff_limit))
    return "\n\n".join(blocks) if blocks else "[no artifacts]"


def format_step_result_for_prompt(step_id: str, content: str, artifacts: StepArtifacts | None) -> str:
    """Render a completed step for prompt context."""

    blocks = [f"--- {step_id} ---"]
    if content.strip():
        blocks.append(content.rstrip())
    if artifacts is not None:
        blocks.append(format_artifact_block(artifacts))
    return "\n\n".join(blocks)


def truncate_text(text: str, limit: int) -> str:
    """Trim large text blobs so prompts stay readable."""

    if len(text) <= limit:
        return text
    return text[: max(0, limit - 40)].rstrip() + "\n[diff truncated for terminal output]"

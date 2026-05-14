"""Tiny external agent backends for workflow implementation steps."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aethr.artifacts import StepArtifacts
from aethr.llm import LLMError, UsageSummary, normalize_model_name

ChunkCallback = Callable[[str], None]


@dataclass(frozen=True)
class AgentCompletion:
    """Content, usage, and artifacts from an external agent run."""

    content: str
    usage: UsageSummary
    artifacts: StepArtifacts


@dataclass(frozen=True)
class OpenCodeAgentClient:
    """Run an implementer step through the OpenCode CLI."""

    model: str | None = None
    working_directory: Path | str | None = None
    unsafe_permissions: bool = False

    def __post_init__(self) -> None:
        requested_model = os.getenv("AETHR_MODEL") or self.model
        object.__setattr__(self, "requested_model", requested_model)
        object.__setattr__(self, "model", normalize_model_name(requested_model))
        object.__setattr__(self, "cwd", Path(self.working_directory or Path.cwd()))

    def complete(self, prompt: str, on_chunk: ChunkCallback | None = None) -> AgentCompletion:
        """Run OpenCode non-interactively and stream its output."""

        command = self._command(prompt)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise LLMError(
                "OpenCode CLI not found. Install `opencode` to run agent-backed implementer steps."
            ) from exc

        assert process.stdout is not None
        chunks: list[str] = []
        for chunk in process.stdout:
            chunks.append(chunk)
            if on_chunk is not None:
                on_chunk(chunk)
        returncode = process.wait()
        output = "".join(chunks).strip()

        if returncode != 0:
            details = output or f"opencode exited with status {returncode}"
            raise LLMError(f"OpenCode agent failed for '{self.requested_model}': {details}")

        artifacts = self._capture_worktree_artifacts()
        return AgentCompletion(
            content="OpenCode agent changed the working tree.",
            usage=UsageSummary(),
            artifacts=artifacts,
        )

    def _command(self, prompt: str) -> list[str]:
        command = [
            "opencode",
            "run",
            "--model",
            self.model or "",
            "--dir",
            str(self.cwd),
        ]
        if self.unsafe_permissions:
            command.append("--dangerously-skip-permissions")
        command.append(prompt)
        return [part for part in command if part]

    def _capture_worktree_artifacts(self) -> StepArtifacts:
        """Return the actual worktree evidence for downstream review."""

        status_result = subprocess.run(
            ["git", "-C", str(self.cwd), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
        )
        stat_result = subprocess.run(
            ["git", "-C", str(self.cwd), "diff", "--stat", "--no-ext-diff"],
            check=False,
            capture_output=True,
            text=True,
        )
        diff_result = subprocess.run(
            ["git", "-C", str(self.cwd), "diff", "--no-ext-diff", "--unified=3"],
            check=False,
            capture_output=True,
            text=True,
        )
        changed_files = self._changed_files_from_status(status_result.stdout)
        diff_stat = stat_result.stdout.strip()
        diff_text = diff_result.stdout.strip()
        untracked_diff = self._untracked_file_patches(status_result.stdout)
        if untracked_diff:
            diff_text = "\n\n".join(part for part in [diff_text, untracked_diff] if part)
        return StepArtifacts(
            changed_files=changed_files,
            diff_stat=diff_stat,
            git_diff=diff_text,
        )

    def _changed_files_from_status(self, status_text: str) -> list[str]:
        """Parse `git status --short` output into file paths."""

        changed_files: list[str] = []
        for line in status_text.splitlines():
            if not line.strip():
                continue
            path = line[3:].strip() if len(line) > 3 else line.strip()
            if "->" in path:
                path = path.split("->", 1)[-1].strip()
            changed_files.append(path)
        return changed_files

    def _untracked_file_patches(self, status_text: str) -> str:
        """Render synthetic patches for untracked files so reviewers can see them."""

        patches: list[str] = []
        for line in status_text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("?? "):
                continue
            path = stripped[3:].strip()
            if not path:
                continue
            file_path = self.cwd / path
            try:
                content = file_path.read_text(encoding="utf-8").rstrip()
            except (OSError, UnicodeDecodeError):
                patches.append(f"Untracked file {path} could not be read as UTF-8 text.")
                continue
            lines = content.splitlines() or [""]
            body = "\n".join(f"+{line}" for line in lines)
            patches.append(
                "\n".join(
                    [
                        f"diff --git a/{path} b/{path}",
                        "new file mode 100644",
                        "--- /dev/null",
                        f"+++ b/{path}",
                        "@@",
                        body,
                    ]
                )
            )
        return "\n\n".join(patches)

"""Tiny external agent backends for workflow implementation steps."""

from __future__ import annotations

import subprocess
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aethr.llm import CompletionResult, LLMError, UsageSummary, normalize_model_name

ChunkCallback = Callable[[str], None]


@dataclass(frozen=True)
class OpenCodeAgentClient:
    """Run an implementer step through the OpenCode CLI."""

    model: str | None = None
    working_directory: Path | str | None = None

    def __post_init__(self) -> None:
        requested_model = os.getenv("AETHR_MODEL") or self.model
        object.__setattr__(self, "requested_model", requested_model)
        object.__setattr__(self, "model", normalize_model_name(requested_model))
        object.__setattr__(self, "cwd", Path(self.working_directory or Path.cwd()))

    def complete(self, prompt: str, on_chunk: ChunkCallback | None = None) -> CompletionResult:
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

        return CompletionResult(content=self._summarize_worktree(), usage=UsageSummary())

    def _command(self, prompt: str) -> list[str]:
        command = [
            "opencode",
            "run",
            "--model",
            self.model or "",
            "--dir",
            str(self.cwd),
            "--dangerously-skip-permissions",
            prompt,
        ]
        return [part for part in command if part]

    def _summarize_worktree(self) -> str:
        """Return a compact description of the resulting working tree changes."""

        result = subprocess.run(
            ["git", "-C", str(self.cwd), "diff", "--stat", "--no-ext-diff"],
            check=False,
            capture_output=True,
            text=True,
        )
        summary = result.stdout.strip()
        if summary:
            return f"OpenCode agent modified the working tree:\n{summary}"
        return "OpenCode agent completed without producing a worktree diff."

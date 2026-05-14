"""A tiny model-call wrapper around LiteLLM.

Aethr defaults to mock responses so workflows are runnable without API keys.
Project-level ``.env`` files are loaded automatically before model selection.
Set ``AETHR_LIVE=1`` to use workflow models, or ``AETHR_MODEL`` to override
all roles.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from dotenv import find_dotenv, load_dotenv

ChunkCallback = Callable[[str], None]


class LLMError(Exception):
    """Raised when a live model call fails."""


@dataclass(frozen=True)
class UsageSummary:
    """Usage and cost metadata for one model completion."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0


@dataclass(frozen=True)
class CompletionResult:
    """Content and usage from one model completion."""

    content: str
    usage: UsageSummary


def normalize_model_name(model: str | None) -> str | None:
    """Convert Relay's provider:model form into provider/model for backends."""

    if model is None:
        return None
    if ":" in model and "/" not in model:
        provider, name = model.split(":", 1)
        if provider and name:
            return f"{provider}/{name}"
    return model


class ModelClient:
    """Minimal model client used by workflow steps."""

    def __init__(self, model: str | None = None) -> None:
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path, override=False)
        self.requested_model = os.getenv("AETHR_MODEL") or model
        self.model = normalize_model_name(self.requested_model)
        self.live = os.getenv("AETHR_LIVE") == "1" or os.getenv("AETHR_MODEL") is not None

    def complete(self, prompt: str, on_chunk: ChunkCallback | None = None) -> CompletionResult:
        """Return a model completion for a prompt."""

        if not self.model or not self.live:
            content = self._mock_complete(prompt)
            self._emit_mock_stream(content, on_chunk)
            return CompletionResult(content=content, usage=self._mock_usage(prompt, content))

        try:
            if on_chunk is None:
                response = self._litellm_completion(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = self._response_text(response)
                usage = self._summarize_usage(prompt, content, response_usage=getattr(response, "usage", None))
                return CompletionResult(content=content, usage=usage)

            streamed = self._litellm_completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                stream_options={"include_usage": True},
            )
            chunks: list[str] = []
            final_usage: Any = None
            for chunk in streamed:
                chunk_text = self._chunk_text(chunk)
                if chunk_text:
                    chunks.append(chunk_text)
                    on_chunk(chunk_text)
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    final_usage = usage

            content = "".join(chunks)
            usage = self._summarize_usage(prompt, content, response_usage=final_usage)
            return CompletionResult(content=content, usage=usage)
        except Exception as exc:
            raise LLMError(f"Model call failed for '{self.requested_model}': {exc}") from exc

    def _litellm_completion(self, **kwargs: Any) -> Any:
        from litellm import completion

        return completion(**kwargs)

    def _mock_complete(self, prompt: str) -> str:
        """Return a deterministic placeholder completion."""

        first_line = next((line for line in prompt.splitlines() if line.strip()), "")
        return (
            "Mock model response.\n\n"
            f"Prompt: {first_line}\n\n"
            "This placeholder keeps Aethr runnable without credentials."
        )

    def _emit_mock_stream(self, content: str, on_chunk: ChunkCallback | None) -> None:
        if on_chunk is None:
            return
        for chunk in self._chunk_text_iter(content):
            on_chunk(chunk)

    def _summarize_usage(
        self,
        prompt: str,
        content: str,
        response_usage: Any | None = None,
        *,
        cost: float | None = None,
    ) -> UsageSummary:
        prompt_tokens = self._prompt_token_count(prompt)
        completion_tokens = self._completion_token_count(content)

        if response_usage is not None:
            prompt_tokens = self._extract_usage_field(response_usage, "prompt_tokens", prompt_tokens)
            completion_tokens = self._extract_usage_field(
                response_usage, "completion_tokens", completion_tokens
            )
            total_tokens = self._extract_usage_field(
                response_usage, "total_tokens", prompt_tokens + completion_tokens
            )
        else:
            total_tokens = prompt_tokens + completion_tokens

        if cost is None:
            cost = self._completion_cost(prompt, content)

        return UsageSummary(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
        )

    def _mock_usage(self, prompt: str, content: str) -> UsageSummary:
        """Summarize mock usage without touching LiteLLM helpers."""

        prompt_tokens = self._count_words(prompt)
        completion_tokens = self._count_words(content)
        return UsageSummary(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost=0.0,
        )

    def _prompt_token_count(self, prompt: str) -> int:
        return self._safe_token_count(messages=[{"role": "user", "content": prompt}])

    def _completion_token_count(self, content: str) -> int:
        return self._safe_token_count(text=content)

    def _safe_token_count(
        self,
        *,
        text: str | None = None,
        messages: list[dict[str, str]] | None = None,
    ) -> int:
        try:
            from litellm import token_counter

            return token_counter(model=self.model or "", text=text, messages=messages)
        except Exception:
            if text is not None:
                return max(1, len(text.split())) if text.strip() else 0
            if messages:
                return sum(max(1, len(message.get("content", "").split())) for message in messages)
            return 0

    def _count_words(self, text: str) -> int:
        """Count whitespace-delimited words as a local fallback."""

        return len(text.split())

    def _completion_cost(self, prompt: str, content: str) -> float:
        try:
            from litellm.cost_calculator import completion_cost

            return float(
                completion_cost(
                    model=self.model or "",
                    prompt=prompt,
                    completion=content,
                )
            )
        except Exception:
            return 0.0

    def _response_text(self, response: Any) -> str:
        choice = response.choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            return ""
        return getattr(message, "content", "") or ""

    def _chunk_text(self, chunk: Any) -> str:
        try:
            choice = chunk.choices[0]
        except Exception:
            return ""

        delta = getattr(choice, "delta", None)
        if delta is not None:
            return getattr(delta, "content", "") or ""

        message = getattr(choice, "message", None)
        if message is not None:
            return getattr(message, "content", "") or ""

        return ""

    def _chunk_text_iter(self, content: str) -> Iterable[str]:
        chunks = content.splitlines(keepends=True)
        return chunks if chunks else [content]

    def _extract_usage_field(self, usage: Any, field: str, fallback: int) -> int:
        value = getattr(usage, field, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(field)
        if value is None:
            return fallback
        try:
            return int(value)
        except Exception:
            return fallback

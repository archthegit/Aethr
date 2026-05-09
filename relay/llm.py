"""A tiny model-call wrapper around LiteLLM.

Relay defaults to mock responses so workflows are runnable without API keys.
Set RELAY_LIVE=1 to use workflow models, or RELAY_MODEL to override all roles.
"""

from __future__ import annotations

import os


class LLMError(Exception):
    """Raised when a live model call fails."""


class ModelClient:
    """Minimal model client used by workflow steps."""

    def __init__(self, model: str | None = None) -> None:
        self.model = os.getenv("RELAY_MODEL") or model
        self.live = os.getenv("RELAY_LIVE") == "1" or os.getenv("RELAY_MODEL") is not None

    def complete(self, prompt: str) -> str:
        """Return a model completion for a prompt.

        Keep this wrapper small until real usage demands more.
        """

        if not self.model or not self.live:
            return self._mock_complete(prompt)

        try:
            from litellm import completion

            response = completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            return content or ""
        except Exception as exc:
            raise LLMError(f"Model call failed for '{self.model}': {exc}") from exc

    def _mock_complete(self, prompt: str) -> str:
        """Return a deterministic placeholder completion."""

        first_line = next((line for line in prompt.splitlines() if line.strip()), "")
        return (
            "Mock model response.\n\n"
            f"Prompt: {first_line}\n\n"
            "This placeholder keeps Relay runnable without credentials."
        )

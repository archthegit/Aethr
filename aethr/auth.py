"""Minimal project-local credential helpers."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from dotenv.main import set_key


SUPPORTED_PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", "Anthropic"),
    "google": ("GOOGLE_API_KEY", "Google"),
    "gemini": ("GOOGLE_API_KEY", "Google"),
    "openai": ("OPENAI_API_KEY", "OpenAI"),
    "openrouter": ("OPENROUTER_API_KEY", "OpenRouter"),
    "xai": ("XAI_API_KEY", "xAI"),
}


def login(provider: str, api_key: str, env_file: Path | str = ".env") -> tuple[str, Path]:
    """Write a provider API key to the project .env file."""

    env_var, _ = env_var_for(provider)
    path = Path(env_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(path), env_var, api_key)
    return env_var, path


def status(env_file: Path | str = ".env") -> dict[str, str]:
    """Return the current credential status for supported providers."""

    path = Path(env_file)
    file_values = dotenv_values(path) if path.exists() else {}
    result: dict[str, str] = {}
    for provider, (env_var, _) in SUPPORTED_PROVIDERS.items():
        value = os.getenv(env_var) or file_values.get(env_var)
        result[provider] = "set" if value else "missing"
    return result


def env_var_for(provider: str) -> tuple[str, str]:
    """Return the environment variable name for a supported provider."""

    normalized = provider.strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        choices = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ValueError(f"Unknown provider '{provider}'. Available providers: {choices}")
    return SUPPORTED_PROVIDERS[normalized]

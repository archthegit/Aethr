"""Project-local environment file loading helpers."""

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv


def load_project_dotenv() -> str | None:
    """Load the nearest project ``.env`` file into process environment.

    The first ``.env`` discovered from the current working directory upward is
    loaded once per process invocation without overriding existing OS-level
    environment variables.
    """

    dotenv_path = find_dotenv(usecwd=True)
    if not dotenv_path:
        return None
    load_dotenv(dotenv_path, override=False)
    return dotenv_path

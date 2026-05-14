import pytest


@pytest.fixture(autouse=True)
def clear_aethr_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests deterministic regardless of the caller's shell environment."""

    monkeypatch.delenv("AETHR_LIVE", raising=False)
    monkeypatch.delenv("AETHR_MODEL", raising=False)

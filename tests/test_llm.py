from pathlib import Path

import pytest

from aethr.llm import LLMError, ModelClient


def test_model_client_wraps_live_model_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHR_LIVE", "1")

    with pytest.raises(LLMError, match="Model call failed"):
        ModelClient("not-a-real-provider/model").complete("hello")


def test_model_client_loads_project_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "AETHR_LIVE=1\nAETHR_MODEL=openai:gpt-5.5\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AETHR_LIVE", raising=False)
    monkeypatch.delenv("AETHR_MODEL", raising=False)

    client = ModelClient("fallback-model")

    assert client.live is True
    assert client.requested_model == "openai:gpt-5.5"
    assert client.model == "openai/gpt-5.5"


def test_model_client_streams_mock_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AETHR_LIVE", raising=False)
    monkeypatch.delenv("AETHR_MODEL", raising=False)

    chunks: list[str] = []
    result = ModelClient("fallback-model").complete("hello\nworld", on_chunk=chunks.append)

    assert result.content.startswith("Mock model response.")
    assert chunks
    assert "".join(chunks) == result.content


def test_model_client_normalizes_provider_prefixed_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AETHR_LIVE", raising=False)
    monkeypatch.delenv("AETHR_MODEL", raising=False)

    client = ModelClient("openai:gpt-5.5")

    assert client.model == "openai/gpt-5.5"

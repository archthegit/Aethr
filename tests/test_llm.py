import pytest

from relay.llm import LLMError, ModelClient


def test_model_client_wraps_live_model_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAY_LIVE", "1")

    with pytest.raises(LLMError, match="Model call failed"):
        ModelClient("not-a-real-provider/model").complete("hello")

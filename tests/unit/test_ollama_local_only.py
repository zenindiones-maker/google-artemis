import pytest

from artemis.llm.router import ModelEndpoint, ModelFactory, ModelProvider, _apply_local_only_endpoint


def test_local_only_forces_qwen_and_loopback_endpoint(monkeypatch):
    monkeypatch.setenv("ARTEMIS_LOCAL_ONLY", "1")
    monkeypatch.setenv("ARTEMIS_LOCAL_MODEL", "qwen2.5:0.5b")

    endpoint = ModelEndpoint(
        provider="google",
        model_name="gemini-3.8-flash",
        api_key="should-not-be-used",
        api_base="https://example.invalid/v1",
    )

    result = _apply_local_only_endpoint(endpoint)

    assert result.provider is ModelProvider.OLLAMA
    assert result.model_name == "qwen2.5:0.5b"
    assert result.api_base == "http://127.0.0.1:11434/v1"
    assert result.api_key == "ollama-local"


def test_local_only_also_rewrites_fallback_endpoints(monkeypatch):
    monkeypatch.setenv("ARTEMIS_LOCAL_ONLY", "1")

    fallback = ModelEndpoint(
        provider="openai",
        model_name="gpt-4o",
        api_base="https://api.openai.com/v1",
    )

    result = _apply_local_only_endpoint(fallback)

    assert result.provider is ModelProvider.OLLAMA
    assert result.model_name == "artemis-qwen-local:latest"
    assert result.api_base == "http://127.0.0.1:11434/v1"


def test_without_local_only_mode_endpoint_is_unchanged(monkeypatch):
    monkeypatch.delenv("ARTEMIS_LOCAL_ONLY", raising=False)

    endpoint = ModelEndpoint(provider="google", model_name="gemini-test")
    result = _apply_local_only_endpoint(endpoint)

    assert result.provider is ModelProvider.GOOGLE
    assert result.model_name == "gemini-test"


def test_get_model_does_not_reuse_remote_cache_in_local_mode(monkeypatch):
    monkeypatch.setenv("ARTEMIS_LOCAL_ONLY", "1")
    monkeypatch.setenv("ARTEMIS_LOCAL_MODEL", "artemis-qwen-local:latest")
    monkeypatch.setattr(ModelFactory, "_cache", {})

    remote_endpoint = ModelEndpoint(
        provider="google",
        model_name="gemini-3.8-flash",
        api_key="remote-key-placeholder",
        api_base="https://example.invalid/v1",
    )
    remote_model = object()
    local_model = object()
    ModelFactory._cache[remote_endpoint.cache_key()] = remote_model

    created = []

    def fake_create_model(cls, endpoint):
        created.append(endpoint)
        return local_model

    monkeypatch.setattr(
        ModelFactory, "create_model", classmethod(fake_create_model)
    )

    result = ModelFactory.get_model(remote_endpoint)

    assert result is local_model
    assert result is not remote_model
    assert len(created) == 1
    assert created[0].provider is ModelProvider.OLLAMA
    assert created[0].model_name == "artemis-qwen-local:latest"

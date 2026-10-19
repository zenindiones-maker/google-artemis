"""E1: a missing optional LLM provider package gives an actionable error and does not
break the CLI or the other providers (OpenAI, Anthropic and Vertex each blocked)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from artemis.llm.router import (
    ModelEndpoint,
    ModelFactory,
    ProviderUnavailableError,
    VertexAIUnavailableError,
)

ROOT = Path(__file__).resolve().parents[2]

CASES = [
    ("openai", "langchain_openai", "langchain-openai"),
    ("openrouter", "langchain_openai", "langchain-openai"),
    ("xai", "langchain_openai", "langchain-openai"),
    ("ollama", "langchain_openai", "langchain-openai"),
    ("anthropic", "langchain_anthropic", "langchain-anthropic"),
]


@pytest.fixture(autouse=True)
def _real_factory(monkeypatch):
    monkeypatch.delenv("ARTEMIS_FAKE_LLM", raising=False)


@pytest.mark.parametrize(("provider", "module", "package"), CASES)
def test_missing_provider_package_raises_actionable_error(monkeypatch, provider, module, package):
    monkeypatch.setitem(sys.modules, module, None)  # makes the import raise ImportError
    with pytest.raises(ProviderUnavailableError) as excinfo:
        ModelFactory.create_model(ModelEndpoint(provider=provider, model_name="m"))
    message = str(excinfo.value)
    assert f"'{provider}' LLM provider" in message
    assert f"pip install {package}" in message
    assert "choose another provider" in message
    assert isinstance(excinfo.value, ImportError)
    assert isinstance(excinfo.value.__cause__, ImportError)


def test_vertex_error_is_a_provider_unavailable_error():
    assert issubclass(VertexAIUnavailableError, ProviderUnavailableError)


def test_blocked_providers_do_not_break_cli_or_gemini(tmp_path: Path) -> None:
    code = f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        BLOCKED = ("langchain_openai", "langchain_anthropic", "langchain_google_vertexai")
        class _Blocker:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError("blocked: " + name)
        sys.meta_path.insert(0, _Blocker())
        from artemis.llm.router import ModelEndpoint, ModelFactory, ProviderUnavailableError
        for provider in ("openai", "anthropic", "vertexai"):
            try:
                ModelFactory.create_model(ModelEndpoint(provider=provider, model_name="m"))
            except ProviderUnavailableError as exc:
                print("UNAVAILABLE", provider, type(exc).__name__)
        model = ModelFactory.create_model(
            ModelEndpoint(provider="google", model_name="gemini-2.5-flash")
        )
        print("GEMINI", type(model).__name__)
        sys.argv = ["artemis", "--help"]
        from artemis.interfaces.cli.main import cli
        try:
            cli()
        except SystemExit as exc:
            print("CLI_EXIT", exc.code or 0)
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GITHUB_", "FORCE_COLOR", "PY_COLORS", "ARTEMIS_FAKE_LLM"))
    }
    env.update(
        HOME=str(tmp_path),
        GOOGLE_API_KEY="ci-not-a-real-key",
        GEMINI_API_KEY="ci-not-a-real-key",
        PYTHONDONTWRITEBYTECODE="1",
        TERM="dumb",
    )
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = proc.stdout
    assert "UNAVAILABLE openai ProviderUnavailableError" in out
    assert "UNAVAILABLE anthropic ProviderUnavailableError" in out
    assert "UNAVAILABLE vertexai VertexAIUnavailableError" in out
    assert "GEMINI ChatGoogleGenerativeAI" in out
    assert "CLI_EXIT 0" in out

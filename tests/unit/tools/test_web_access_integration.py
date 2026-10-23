"""Testes de integração isolados para web_access.py."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "artemis" / "tools" / "web_access.py"

spec = importlib.util.spec_from_file_location(
    "web_access_integration_under_test", MODULE_PATH
)
assert spec is not None and spec.loader is not None
web_access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_access)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.chunks = chunks if chunks is not None else []
        self._content = b""
        self.encoding = "utf-8"
        self.url = "https://example.com/"

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk


class FakeStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def stream(self, method, url, **kwargs):
        self.requests.append((method, str(url), kwargs))
        if not self.responses:
            raise AssertionError("Foi feita uma requisição inesperada")
        return FakeStream(self.responses.pop(0))


@pytest.mark.asyncio
async def test_body_within_limit_is_read_and_preserved():
    expected = b"conteudo publico"
    response = FakeResponse(chunks=[b"conteudo ", b"publico"])
    client = FakeClient([response])

    result, body = await web_access._read_one_response(
        client, "https://example.com/"
    )

    assert result is response
    assert body == expected
    assert response._content == expected


@pytest.mark.asyncio
async def test_body_over_one_megabyte_is_rejected():
    response = FakeResponse(
        chunks=[
            b"a" * web_access.MAX_BODY_BYTES,
            b"b",
        ]
    )
    client = FakeClient([response])

    with pytest.raises(ValueError, match="limite de 1 MB"):
        await web_access._read_one_response(
            client, "https://example.com/"
        )


@pytest.mark.asyncio
async def test_redirect_chain_stops_at_configured_limit():
    responses = [
        FakeResponse(302, {"location": f"/hop-{index}"})
        for index in range(4)
    ]
    client = FakeClient(responses)

    # Isola o teste de redirect da resolução DNS e testa o limite do loop.
    with patch.object(web_access, "_validate_url", side_effect=lambda url: url):
        with pytest.raises(ValueError, match="redirecionamentos excedido"):
            await web_access._get_limited(
                client, "https://example.com/start"
            )

    assert len(client.requests) == 4


@pytest.mark.asyncio
async def test_redirect_without_location_is_rejected():
    client = FakeClient([FakeResponse(302)])

    with patch.object(web_access, "_validate_url", side_effect=lambda url: url):
        with pytest.raises(ValueError, match="sem destino"):
            await web_access._get_limited(
                client, "https://example.com/start"
            )

    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_http_error_status_is_rejected():
    client = FakeClient([FakeResponse(500)])

    with patch.object(web_access, "_validate_url", side_effect=lambda url: url):
        with pytest.raises(ValueError, match="HTTP 500"):
            await web_access._get_limited(
                client, "https://example.com/"
            )


@pytest.mark.asyncio
async def test_search_rejects_empty_query_without_network():
    with patch.object(
        web_access, "_get_limited", new_callable=AsyncMock
    ) as mocked:
        result = await web_access.web_search("   ")

    assert result == "Informe uma consulta de busca."
    mocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_reports_network_failure_without_raising():
    async def fail(*args, **kwargs):
        raise OSError("falha simulada")

    with patch.object(web_access, "_get_limited", side_effect=fail):
        result = await web_access.web_fetch("https://example.com/")

    assert result.startswith("Falha ao consultar página: OSError:")
    assert "falha simulada" in result

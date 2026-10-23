"""Regressões de segurança para artemis/tools/web_access.py."""

import importlib.util
import ipaddress
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "artemis" / "tools" / "web_access.py"

spec = importlib.util.spec_from_file_location(
    "web_access_security_under_test", MODULE_PATH
)
assert spec is not None and spec.loader is not None

web_access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_access)


def _dns_record(ip: str):
    """Registro mínimo compatível com socket.getaddrinfo."""
    return (None, None, None, None, (ip, 0))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://192.168.1.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://localhost/",
        "http://service.local/",
    ],
)
def test_rejects_local_or_private_destinations(url):
    with pytest.raises(ValueError):
        web_access._validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://user:password@example.com/",
        "",
    ],
)
def test_rejects_invalid_schemes_or_credentials(url):
    with pytest.raises(ValueError):
        web_access._validate_url(url)


def test_accepts_public_hostname():
    with patch.object(
        web_access.socket,
        "getaddrinfo",
        return_value=[_dns_record("93.184.216.34")],
    ):
        assert (
            web_access._validate_url("https://example.com/")
            == "https://example.com/"
        )


def test_rejects_hostname_with_mixed_public_and_private_dns_answers():
    with patch.object(
        web_access.socket,
        "getaddrinfo",
        return_value=[
            _dns_record("93.184.216.34"),
            _dns_record("127.0.0.1"),
        ],
    ):
        with pytest.raises(ValueError, match="Destino não público"):
            web_access._validate_url("https://rebind.example/")


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


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
        self.requests.append((method, url, kwargs))
        return FakeStream(self.responses.pop(0))


@pytest.mark.asyncio
async def test_blocks_redirect_to_loopback_before_second_request():
    client = FakeClient(
        [
            FakeResponse(
                302,
                {"location": "http://127.0.0.1/admin"},
            )
        ]
    )

    with pytest.raises(ValueError, match="Destino não público"):
        await web_access._get_limited(client, "https://example.com/")

    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_blocks_redirect_to_private_network():
    client = FakeClient(
        [
            FakeResponse(
                302,
                {"location": "http://192.168.1.1/admin"},
            )
        ]
    )

    with pytest.raises(ValueError, match="Destino não público"):
        await web_access._get_limited(client, "https://example.com/")

    assert len(client.requests) == 1


def test_public_ip_classification_used_by_python():
    assert ipaddress.ip_address("127.0.0.1").is_global is False
    assert ipaddress.ip_address("::1").is_global is False

"""Testes para fixação do IP validado na conexão TCP."""

import importlib.util
import ipaddress
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "artemis" / "tools" / "web_access.py"

spec = importlib.util.spec_from_file_location(
    "web_access_dns_pinning_under_test", MODULE_PATH
)
assert spec is not None and spec.loader is not None
web_access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_access)


@pytest.mark.asyncio
async def test_pinned_backend_connects_to_validated_ip():
    """O socket deve receber o IP validado, não resolver o hostname novamente."""
    validated_ip = ipaddress.ip_address("93.184.216.34")
    backend = web_access._PinnedNetworkBackend(
        {"example.com": {validated_ip}}
    )
    stream = object()
    backend._backend = type(
        "FakeBackend",
        (),
        {"connect_tcp": AsyncMock(return_value=stream)},
    )()

    result = await backend.connect_tcp("example.com", 443, timeout=2.0)

    assert result is stream
    backend._backend.connect_tcp.assert_awaited_once()
    args = backend._backend.connect_tcp.await_args
    assert args.args[0] == str(validated_ip)
    assert args.args[1] == 443


@pytest.mark.asyncio
async def test_pinned_backend_rejects_unvalidated_hostname():
    backend = web_access._PinnedNetworkBackend({})
    backend._backend = type(
        "FakeBackend",
        (),
        {"connect_tcp": AsyncMock()},
    )()

    with pytest.raises((ValueError, OSError)):
        await backend.connect_tcp("unknown.example", 443, timeout=2.0)

    backend._backend.connect_tcp.assert_not_awaited()

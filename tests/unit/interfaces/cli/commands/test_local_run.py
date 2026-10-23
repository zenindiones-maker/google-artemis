import pytest

from artemis.interfaces.cli.commands.local_run import dispatch_tool_calls


def test_dispatches_only_approved_tool_name():
    calls = [{
        "name": "open_url_firefox",
        "args": {"url": "https://example.com"},
    }]
    seen = []
    result = dispatch_tool_calls(calls, launcher=lambda url: seen.append(url) or "enviado")
    assert seen == ["https://example.com"]
    assert result == "enviado"


def test_rejects_unknown_tool_without_executing_it():
    seen = []
    with pytest.raises(RuntimeError, match="não permitida"):
        dispatch_tool_calls(
            [{"name": "shell", "args": {"command": "id"}}],
            launcher=lambda url: seen.append(url),
        )
    assert seen == []


def test_rejects_extra_arguments():
    seen = []
    with pytest.raises(ValueError):
        dispatch_tool_calls(
            [{"name": "open_url_firefox",
              "args": {"url": "https://example.com", "extra": "x"}}],
            launcher=lambda url: seen.append(url),
        )
    assert seen == []

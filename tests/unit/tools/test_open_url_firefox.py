"""Regression tests for explicitly authorized Firefox URL opening."""

from unittest.mock import patch

import pytest

from artemis.tools.mobile.open_url_firefox import (
    validate_http_url,
    request_url_approval,
    launch_url_in_firefox,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/path?q=1",
    ],
)
def test_accepts_http_and_https_urls(url):
    assert validate_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "intent://example.com",
        "https://",
        "https://user:password@example.com",
    ],
)
def test_rejects_invalid_or_unsafe_urls(url):
    with pytest.raises((ValueError, TypeError)):
        validate_http_url(url)


def test_approval_requires_exact_explicit_yes():
    with (
        patch("builtins.input", return_value="S"),
        patch(
            "artemis.tools.mobile.open_url_firefox.sys.stdin.isatty",
            return_value=True,
        ),
    ):
        assert request_url_approval("https://example.com") is True


@pytest.mark.parametrize("answer", ["", "n", "nao", "yes", "S ", "s\n"])
def test_non_exact_approval_is_denied(answer):
    with (
        patch("builtins.input", return_value=answer),
        patch(
            "artemis.tools.mobile.open_url_firefox.sys.stdin.isatty",
            return_value=True,
        ),
    ):
        assert request_url_approval("https://example.com") is False


def test_missing_interactive_terminal_denies_approval():
    with patch(
        "artemis.tools.mobile.open_url_firefox.sys.stdin.isatty",
        return_value=False,
    ):
        assert request_url_approval("https://example.com") is False


def test_denial_never_launches_firefox():
    with (
        patch(
            "artemis.tools.mobile.open_url_firefox.request_url_approval",
            return_value=False,
        ),
        patch(
            "artemis.tools.mobile.open_url_firefox.subprocess.run"
        ) as run,
    ):
        result = launch_url_in_firefox("https://example.com")
        run.assert_not_called()
        assert "negad" in result.lower() or "cancel" in result.lower()


def test_firefox_launch_targets_explicit_package():
    with (
        patch(
            "artemis.tools.mobile.open_url_firefox.request_url_approval",
            return_value=True,
        ),
        patch(
            "artemis.tools.mobile.open_url_firefox.subprocess.run"
        ) as run,
    ):
        run.return_value.returncode = 0
        result = launch_url_in_firefox("https://example.com")
        args = run.call_args.args[0]
        assert "org.mozilla.firefox" in args
        assert "https://example.com" in args
        assert "success" in result.lower() or "solicitação" in result.lower()


def test_launch_failure_is_not_reported_as_success():
    with (
        patch(
            "artemis.tools.mobile.open_url_firefox.request_url_approval",
            return_value=True,
        ),
        patch(
            "artemis.tools.mobile.open_url_firefox.subprocess.run",
            side_effect=OSError("Firefox launch failed"),
        ),
    ):
        result = launch_url_in_firefox("https://example.com")
        assert "error" in result.lower() or "falh" in result.lower()
        assert "success" not in result.lower()

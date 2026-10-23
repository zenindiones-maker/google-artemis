import unittest
from unittest.mock import patch, Mock

from artemis.tools.mobile.open_url_firefox import (
    validate_http_url,
    request_url_approval,
    launch_url_in_firefox,
)


class FirefoxUrlTests(unittest.TestCase):
    def test_accepts_http_and_https(self):
        self.assertEqual(validate_http_url("https://example.com"), "https://example.com")
        self.assertEqual(validate_http_url("http://example.com/path?q=1"),
                         "http://example.com/path?q=1")

    def test_rejects_unsafe_urls(self):
        invalid = [
            "", "   ", "file:///etc/passwd", "javascript:alert(1)",
            "intent://example.com", "https://", "https://user:pass@example.com",
            "https://example.com:99999", "https://example.com\nmalicious",
        ]
        for url in invalid:
            with self.subTest(url=repr(url)):
                with self.assertRaises((ValueError, TypeError)):
                    validate_http_url(url)

    def test_approval_requires_interactive_terminal_and_exact_S(self):
        with patch("artemis.tools.mobile.open_url_firefox.sys.stdin.isatty",
                   return_value=True), \
             patch("artemis.tools.mobile.open_url_firefox.input",
                   return_value="S", create=True):
            self.assertTrue(request_url_approval("https://example.com"))

        for answer in ("", "s", "S ", "yes", "n", "nao"):
            with self.subTest(answer=repr(answer)), \
                 patch("artemis.tools.mobile.open_url_firefox.sys.stdin.isatty",
                       return_value=True), \
                 patch("artemis.tools.mobile.open_url_firefox.input",
                       return_value=answer, create=True):
                self.assertFalse(request_url_approval("https://example.com"))

    def test_noninteractive_terminal_denies(self):
        with patch("artemis.tools.mobile.open_url_firefox.sys.stdin.isatty",
                   return_value=False):
            self.assertFalse(request_url_approval("https://example.com"))

    def test_denial_never_launches(self):
        with patch("artemis.tools.mobile.open_url_firefox.request_url_approval",
                   return_value=False), \
             patch("artemis.tools.mobile.open_url_firefox.subprocess.run") as run:
            result = launch_url_in_firefox("https://example.com")
            run.assert_not_called()
            self.assertIn("negad", result.lower())

    def test_launch_uses_firefox_without_shell(self):
        with patch("artemis.tools.mobile.open_url_firefox.request_url_approval",
                   return_value=True), \
             patch("artemis.tools.mobile.open_url_firefox.subprocess.run") as run:
            run.return_value = Mock(returncode=0, stdout="", stderr="")
            result = launch_url_in_firefox("https://example.com")
            args, kwargs = run.call_args
            self.assertIn("org.mozilla.firefox", args[0])
            self.assertIn("https://example.com", args[0])
            self.assertFalse(kwargs.get("shell", False))
            self.assertIn("solicitação", result.lower())

    def test_launch_failure_is_not_success(self):
        with patch("artemis.tools.mobile.open_url_firefox.request_url_approval",
                   return_value=True), \
             patch("artemis.tools.mobile.open_url_firefox.subprocess.run",
                   side_effect=OSError("launch failed")):
            result = launch_url_in_firefox("https://example.com")
            self.assertIn("falh", result.lower())
            self.assertNotIn("sucesso", result.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)

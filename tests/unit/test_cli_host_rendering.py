# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Regression tests: CLI help assertions must not depend on the CI host.

On GitHub Actions Typer forces a Rich terminal (``GITHUB_ACTIONS`` is set) and
Rich then splits option names with ANSI escapes, which broke six help tests in
run 39091977019.  These tests re-create that host in a subprocess (Typer reads
the variables at import time) and run the real help assertions there.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

HOSTILE_HOSTS = {
    "github_actions": {"GITHUB_ACTIONS": "true", "TERM": "xterm-256color"},
    "force_color": {"FORCE_COLOR": "1", "TERM": "xterm-256color"},
    "dumb_terminal": {"TERM": "dumb", "NO_COLOR": "1"},
}

HELP_TESTS = [
    "test_cli_help",
    "test_cli_run_help",
    "test_cli_batch_help",
    "test_cli_trace_help",
    "test_cli_mcp_help",
    "test_cli_restart_help",
    "test_cli_stop_help",
    "test_cli_status_help",
    "test_cli_restart_command",
    "test_cli_doctor_blocker_failure_shows_run_lines_and_splits_chains",
    "test_cli_doctor_optional_failure_is_degraded_not_blocked",
    "test_cli_doctor_host_warn_degrades_and_keeps_the_fix",
]


@pytest.mark.parametrize("host", sorted(HOSTILE_HOSTS))
def test_cli_assertions_are_host_independent(host: str) -> None:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTEST_ADDOPTS"}}
    for name in ("GITHUB_ACTIONS", "FORCE_COLOR", "PY_COLORS", "NO_COLOR", "TERM"):
        env.pop(name, None)
    env.update(HOSTILE_HOSTS[host])
    env.setdefault("GOOGLE_API_KEY", "ci-not-a-real-key")
    env.setdefault("GEMINI_API_KEY", "ci-not-a-real-key")
    selection = " or ".join(HELP_TESTS)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_cli.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:cov",
            "--color=no",
            "-k",
            selection,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    assert f"{len(HELP_TESTS)} passed" in proc.stdout

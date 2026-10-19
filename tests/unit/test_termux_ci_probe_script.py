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

"""Guards for the Termux-in-Docker CI probe script."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "termux_ci_probe.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_probe_script_has_valid_syntax():
    subprocess.run(["bash", "-n", str(PROBE)], check=True)


def test_cli_checks_are_critical_so_failures_turn_the_job_red():
    source = PROBE.read_text(encoding="utf-8")
    for check in ("import artemis CLI module", "artemis --version", "artemis --help"):
        assert re.search(rf'step critical "{re.escape(check)}"', source), check
    assert 'exit "${CRITICAL_FAILED}"' in source


def test_probe_never_uses_real_credentials_or_secrets():
    source = PROBE.read_text(encoding="utf-8")
    assert "secrets." not in source
    assert "API_KEY" not in source


def test_rust_extensions_get_an_android_api_level_for_maturin():
    source = PROBE.read_text(encoding="utf-8")
    assert "export ANDROID_API_LEVEL" in source
    assert "sys.getandroidapilevel()" in source


def test_opencv_runtime_dependency_dbus_is_installed():
    source = PROBE.read_text(encoding="utf-8")
    assert "install python-opencv-python dbus" in source


def test_numpy_dependent_sdists_build_against_termux_numpy():
    source = PROBE.read_text(encoding="utf-8")
    assert "--no-build-isolation bottleneck numexpr" in source

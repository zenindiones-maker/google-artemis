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


def test_probe_exercises_the_documented_install_script():
    source = PROBE.read_text(encoding="utf-8")
    assert re.search(r'step critical "scripts/install_termux.sh" (env PIP_NO_CACHE_DIR=1 )?bash', source)


def test_installer_handles_observed_termux_build_blockers():
    installer = (ROOT / "scripts" / "install_termux.sh").read_text(encoding="utf-8")
    pkgs = (ROOT / "requirements" / "termux-pkg.txt").read_text(encoding="utf-8")
    # maturin: "Failed to determine Android API level"
    assert "export ANDROID_API_LEVEL" in installer
    assert "sys.getandroidapilevel()" in installer
    # uvloop: "./configure: No such file or directory" without termux-exec
    assert 'export LD_PRELOAD="${lib}"' in installer
    assert "\ntermux-exec" in pkgs
    # cv2: "dlopen failed: library libdbus-1.so not found"
    assert "\ndbus " in pkgs


def test_probe_runs_imports_outside_the_copied_checkout():
    source = PROBE.read_text(encoding="utf-8")
    assert source.index('cd "$(mktemp -d)"') < source.index(
        'step critical "import artemis CLI module"'
    )


def test_probe_records_build_timing_and_disk_usage():
    source = PROBE.read_text(encoding="utf-8")
    assert 'export PIP_LOG="${OUT}/logs/pip-timestamped.log"' in source
    assert 'step optional "disk usage"' in source

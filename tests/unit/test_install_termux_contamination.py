"""Case 4: scripts/install_termux.sh detects venv/Python contamination.

Reproduced on 3e8927f:
* an existing ~/.artemis-venv built for another Python minor (e.g. after
  ``pkg upgrade python``) was silently reused, so pip installed into a broken venv;
* PYTHONPATH / PYTHONHOME / VIRTUAL_ENV / PIP_* from another environment leaked into
  the pip install.
Now the installer stops with an actionable message (it never deletes the venv) and
scrubs the leaking variables. Everything is stubbed; nothing is installed.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_termux.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="POSIX shell script"
)

VERSION_PROBE = 'case "$2" in *version_info*) echo {ver};; *) echo 24;; esac'
ENV_DUMP = 'echo "{name}-env PYTHONPATH=${{PYTHONPATH:-}} PYTHONHOME=${{PYTHONHOME:-}} VIRTUAL_ENV=${{VIRTUAL_ENV:-}} PIP_TARGET=${{PIP_TARGET:-}}" >> "$STUB_LOG"'


def _stub(directory: Path, name: str, body: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / name
    exe.write_text(f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\n{body}\nexit 0\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, *, system_py: str, venv_py: str, extra_env: dict[str, str] | None = None):
    stubs, sysbin, home = tmp_path / "stubs", tmp_path / "sysbin", tmp_path / "home"
    sysbin.mkdir()
    for tool in ("bash", "sh", "env", "cat", "sed", "dirname", "mkdir"):
        real = shutil.which(tool)
        if real:
            (sysbin / tool).symlink_to(real)
    prefix = tmp_path / "data/data/com.termux/files/usr"
    (prefix / "lib").mkdir(parents=True)
    _stub(stubs, "pkg")
    _stub(stubs, "dpkg-query")
    _stub(stubs, "python", body=VERSION_PROBE.format(ver=system_py))
    venv = home / ".artemis-venv"
    _stub(
        venv / "bin",
        "python",
        body=VERSION_PROBE.format(ver=venv_py) + "\n" + ENV_DUMP.format(name="venvpy"),
    )
    _stub(venv / "bin", "artemis")
    (venv / "keep.txt").write_text("user data")
    log = tmp_path / "calls.log"
    env = {
        "HOME": str(home),
        "PATH": f"{stubs}:{sysbin}",
        "STUB_LOG": str(log),
        "PREFIX": str(prefix),
        "TERMUX_VERSION": "0.118.3",
        **(extra_env or {}),
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls, venv


def test_venv_from_another_python_minor_is_rejected_and_preserved(tmp_path: Path) -> None:
    proc, calls, venv = _run(tmp_path, system_py="3.13", venv_py="3.12")
    assert proc.returncode != 0
    assert "Python 3.12" in proc.stderr and "3.13" in proc.stderr
    assert not any("-m pip install" in c for c in calls)
    assert (venv / "keep.txt").read_text() == "user data"


def test_matching_venv_is_still_reused(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, system_py="3.13", venv_py="3.13")
    assert proc.returncode == 0, proc.stderr
    assert "Reusing existing virtualenv" in proc.stdout
    assert any("-m pip install" in c for c in calls)


def test_leaking_python_environment_variables_are_scrubbed(tmp_path: Path) -> None:
    leak = {
        "PYTHONPATH": "/other/site-packages",
        "PYTHONHOME": "/other",
        "VIRTUAL_ENV": "/other/venv",
        "PIP_TARGET": "/other/target",
    }
    proc, calls, _ = _run(tmp_path, system_py="3.13", venv_py="3.13", extra_env=leak)
    assert proc.returncode == 0, proc.stderr
    assert "Ignoring PYTHONPATH" in proc.stdout
    dumps = [c for c in calls if c.startswith("venvpy-env")]
    assert dumps
    assert all("/other" not in c for c in dumps)

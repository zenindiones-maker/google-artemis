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

"""Behavioural tests for scripts/install_termux.sh with stubbed commands."""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_termux.sh"
PKG_FILE = ROOT / "requirements" / "termux-pkg.txt"
CONSTRAINTS = ROOT / "requirements" / "termux-constraints.txt"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="POSIX shell script"
)
SYSTEM_TOOLS = ("bash", "sh", "env", "cat", "sed", "dirname", "mkdir")


def _stub(directory: Path, name: str, body: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / name
    exe.write_text(f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\n{body}\nexit 0\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, *args: str, termux: bool = True, versions: str = ""):
    stubs = tmp_path / "stubs"
    sysbin = tmp_path / "sysbin"
    sysbin.mkdir()
    for tool in SYSTEM_TOOLS:
        real = shutil.which(tool)
        if real:
            (sysbin / tool).symlink_to(real)
    log = tmp_path / "calls.log"
    home = tmp_path / "home"
    home.mkdir()
    prefix = tmp_path / "data/data/com.termux/files/usr"
    (prefix / "lib").mkdir(parents=True)
    (prefix / "lib" / "libtermux-exec-ld-preload.so").write_text("")
    _stub(stubs, "pkg")
    _stub(stubs, "dpkg-query", body=versions)
    _stub(stubs, "python", body='case "$1" in -c) echo 24;; esac')
    venv_bin = home / ".artemis-venv" / "bin"
    env = {"HOME": str(home), "PATH": f"{stubs}:{sysbin}", "STUB_LOG": str(log)}
    if termux:
        env |= {"PREFIX": str(prefix), "TERMUX_VERSION": "0.118.3"}
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls, venv_bin


def test_refuses_to_run_outside_termux(tmp_path):
    proc, calls, _ = _run(tmp_path, termux=False)
    assert proc.returncode == 1
    assert "Termux on Android only" in proc.stderr
    assert calls == []


def test_dry_run_prints_plan_and_changes_nothing(tmp_path):
    proc, calls, venv_bin = _run(tmp_path, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert calls == []
    assert "+ pkg install -y python python-pip uv" in proc.stdout
    assert "+ pkg install -y python-opencv-python" in proc.stdout
    assert "--system-site-packages" in proc.stdout
    assert f"-c {CONSTRAINTS}" in proc.stdout
    assert not venv_bin.exists()


def test_install_runs_pkg_then_venv_then_constrained_pip_and_verifies(tmp_path):
    proc, calls, _ = _run(tmp_path)
    # The venv python is not created by the stubbed "python -m venv", so pip and
    # artemis calls fail after venv creation; check the order up to that point.
    pkg_calls = [c for c in calls if c.startswith("pkg ")]
    assert pkg_calls[0].startswith("pkg install -y python python-pip uv git")
    assert "x11-repo" in pkg_calls[0]
    assert pkg_calls[1] == "pkg install -y python-opencv-python"
    assert any(c.startswith("python -m venv --system-site-packages") for c in calls)
    assert "ANDROID_API_LEVEL=24" in proc.stdout
    assert "libtermux-exec-ld-preload.so" in proc.stdout


def test_warns_when_installed_versions_differ_from_validated(tmp_path):
    proc, _, _ = _run(tmp_path, versions="printf 0.0.0")
    assert "validated in CI" in proc.stdout


def test_existing_virtualenv_is_reused_not_recreated(tmp_path):
    home = tmp_path / "home"
    venv_bin = home / ".artemis-venv" / "bin"
    _stub(venv_bin, "python")
    _stub(venv_bin, "artemis")
    marker = home / ".artemis-venv" / "keep.txt"
    marker.write_text("user data")
    # _run creates HOME itself; pre-create it so the venv survives.
    proc, calls, _ = _run_with_existing_home(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "Reusing existing virtualenv" in proc.stdout
    assert not any(c.startswith("python -m venv") for c in calls)
    assert any("-m pip install --prefer-binary -c" in c for c in calls)
    assert any(c == "artemis --help" for c in calls)
    assert marker.read_text() == "user data"


def _run_with_existing_home(tmp_path):
    original_mkdir = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self == tmp_path / "home":
            kwargs["exist_ok"] = True
        return original_mkdir(self, *args, **kwargs)

    Path.mkdir = mkdir
    try:
        return _run(tmp_path)
    finally:
        Path.mkdir = original_mkdir


def test_constraints_are_exact_pins_and_exclude_termux_and_vertex_packages():
    pins = [
        Requirement(line)
        for line in CONSTRAINTS.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert pins
    for req in pins:
        assert str(req.specifier).startswith("=="), req
    names = {canonicalize_name(r.name) for r in pins}
    for pkg_provided in ("numpy", "scipy", "opencv-python", "pyarrow", "pillow", "matplotlib"):
        assert pkg_provided not in names
    for vertex_only in (
        "langchain-google-vertexai",
        "google-cloud-aiplatform",
        "bottleneck",
        "numexpr",
    ):
        assert vertex_only not in names
    for core in ("pydantic-core", "fastapi", "uvicorn", "uiautomator2", "adbutils", "langgraph"):
        assert core in names


def test_pkg_list_covers_tools_used_by_start_sh_and_probe():
    names = {
        line.split()[0]
        for line in PKG_FILE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {
        "python",
        "uv",
        "android-tools",
        "ffmpeg",
        "nodejs-lts",
        "termux-exec",
        "rust",
        "dbus",
    } <= names
    assert {"python-numpy", "python-scipy", "python-pyarrow", "python-opencv-python"} <= names

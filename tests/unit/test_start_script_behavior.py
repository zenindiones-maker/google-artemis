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

"""Behavioural tests for start.sh with every external command stubbed.

start.sh is copied into a temporary project directory and executed with a
fake HOME and a PATH made of (a) stub executables that only record their
arguments and (b) symlinks to the basic coreutils the script needs. Nothing
is downloaded or installed.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT / "start.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="start.sh is a POSIX shell script (Windows uses start.bat)",
)

# Basic tools the script legitimately needs from the host.
SYSTEM_TOOLS = (
    "bash",
    "sh",
    "env",
    "cat",
    "cut",
    "tr",
    "mkdir",
    "ln",
    "cp",
    "mv",
    "rm",
    "touch",
    "tar",
    "gzip",
    "sed",
    "dirname",
    "basename",
    "hostname",
    "whoami",
    "chmod",
    "ls",
    "head",
    "grep",
    "mktemp",
)


@dataclass
class Sandbox:
    project: Path
    home: Path
    stubs: Path
    log: Path
    env: dict[str, str]

    def stub(
        self, name: str, body: str = "", exit_code: int = 0, where: Path | None = None
    ) -> None:
        target = (where or self.stubs) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\n{body}\nexit {exit_code}\n',
            encoding="utf-8",
        )
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def calls(self, name: str) -> list[str]:
        if not self.log.exists():
            return []
        prefix = f"{name} "
        return [
            line[len(prefix) :]
            for line in self.log.read_text().splitlines()
            if line.startswith(prefix)
        ]

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.project / "start.sh")],
            cwd=self.project,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )


def _make_sandbox(tmp_path: Path, *, showcase_built: bool = True) -> Sandbox:
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy2(START_SCRIPT, project / "start.sh")
    if showcase_built:
        dist = project / "apps" / "showcase_ui" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    sysbin = tmp_path / "sysbin"
    sysbin.mkdir()
    for tool in SYSTEM_TOOLS:
        real = shutil.which(tool)
        if real:
            (sysbin / tool).symlink_to(real)

    log = tmp_path / "calls.log"
    env = {
        "HOME": str(home),
        "PATH": f"{stubs}:{sysbin}",
        "STUB_LOG": str(log),
        "TERM": "dumb",
        "LANG": "C.UTF-8",
        "ARTEMIS_SKIP_STANDARD_PATHS": "1",
    }
    box = Sandbox(project=project, home=home, stubs=stubs, log=log, env=env)
    # Deterministic identity: never root-escalate, never prompt.
    box.stub("id", body='[ "$1" = "-u" ] && echo 1000')
    box.stub("uname", body='case "$1" in -m) echo x86_64;; *) echo Linux;; esac')
    # Network access is always stubbed to fail.
    box.stub("curl", exit_code=22)
    return box


def _termux(box: Sandbox, tmp_path: Path) -> Path:
    prefix = tmp_path / "data" / "data" / "com.termux" / "files" / "usr"
    (prefix / "bin").mkdir(parents=True)
    box.env["PREFIX"] = str(prefix)
    box.env["TERMUX_VERSION"] = "0.118.3"
    return prefix / "bin"


def test_termux_without_uv_asks_for_pkg_and_never_runs_desktop_installer(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path)
    _termux(box, tmp_path)

    result = box.run()

    assert result.returncode == 1
    assert "pkg install uv" in result.stdout
    assert box.calls("curl") == []
    assert not (box.home / ".local" / "bin" / "uv").exists()


def test_desktop_without_uv_still_uses_astral_installer(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path)

    box.run()

    assert any("astral.sh/uv/install.sh" in call for call in box.calls("curl"))

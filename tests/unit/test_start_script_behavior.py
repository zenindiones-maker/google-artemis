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


def _common_tools(box: Sandbox, where: Path) -> None:
    box.stub("uv", where=where)


def test_termux_lists_pkg_names_for_missing_tools_and_adb_wireless_steps(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path)
    prefix_bin = _termux(box, tmp_path)
    _common_tools(box, prefix_bin)

    result = box.run()

    assert result.returncode == 0, result.stderr
    assert "pkg install android-tools ffmpeg" in result.stdout
    assert "scrcpy" not in result.stdout.split("Missing host tools", 1)[-1].split("\n", 1)[0]
    assert "adb pair 127.0.0.1:" in result.stdout
    assert "adb connect 127.0.0.1:" in result.stdout
    for desktop_tool in ("apt-get", "dnf", "pacman", "brew", "sudo"):
        assert box.calls(desktop_tool) == []
    assert box.calls("curl") == []


def test_termux_with_all_tools_prints_no_install_hint(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path)
    prefix_bin = _termux(box, tmp_path)
    _common_tools(box, prefix_bin)
    box.stub("adb", where=prefix_bin)
    box.stub("ffmpeg", where=prefix_bin)

    result = box.run()

    assert result.returncode == 0, result.stderr
    assert "Missing host tools" not in result.stdout
    assert any(call.startswith("start-server") for call in box.calls("adb"))


def test_termux_with_old_node_suggests_nodejs_lts_without_downloading(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, showcase_built=False)
    prefix_bin = _termux(box, tmp_path)
    _common_tools(box, prefix_bin)
    box.stub("node", body='[ "$1" = "-v" ] && echo v20.11.0', where=prefix_bin)
    box.stub("npm", body="echo 10.0.0", where=prefix_bin)

    result = box.run()

    assert result.returncode == 0, result.stderr
    assert "pkg install nodejs-lts" in result.stdout
    assert box.calls("curl") == []
    assert box.calls("npm") == []
    assert not any((box.home / ".local" / "share").glob("node*"))


def test_desktop_linux_still_installs_missing_tools_with_apt(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path)
    _common_tools(box, box.stubs)
    box.stub("id", body='[ "$1" = "-u" ] && echo 0')
    box.stub("apt-get")

    result = box.run()

    assert result.returncode == 0, result.stderr
    installs = [call for call in box.calls("apt-get") if " install " in f" {call} "]
    assert installs, box.log.read_text() if box.log.exists() else "no calls"
    assert {"adb", "ffmpeg", "scrcpy"} <= set(installs[0].split())
    assert "Termux detected" not in result.stdout
    # The portable scrcpy fallback is still attempted on desktop Linux.
    assert any("scrcpy-linux-x86_64" in call for call in box.calls("curl"))


def _desktop_without_node(box: Sandbox) -> None:
    _common_tools(box, box.stubs)
    for tool in ("adb", "ffmpeg", "scrcpy"):
        box.stub(tool)


def _fake_node(path: Path, version: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, body in (("node", f'[ "$1" = "-v" ] && echo {version}'), ("npm", "echo 10.9.0")):
        exe = path / name
        exe.write_text(f"#!/bin/sh\n{body}\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)


def test_failed_portable_node_download_leaves_no_partial_install(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, showcase_built=False)
    _desktop_without_node(box)

    result = box.run()

    assert result.returncode == 0, result.stderr
    assert any("nodejs.org/dist/v22.23.2" in call for call in box.calls("curl"))
    share = box.home / ".local" / "share"
    assert not (share / "node-v22.23.2").exists()
    assert list(share.glob(".node-*.partial.*")) == []
    assert "Could not configure compatible Node.js" in result.stdout


def test_existing_incomplete_node_dir_is_preserved_not_deleted(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, showcase_built=False)
    _desktop_without_node(box)
    incomplete = box.home / ".local" / "share" / "node-v22.23.2"
    incomplete.mkdir(parents=True)
    (incomplete / "user-note.txt").write_text("keep me", encoding="utf-8")

    box.run()

    assert (incomplete / "user-note.txt").read_text(encoding="utf-8") == "keep me"


def test_shared_legacy_node_directory_is_never_removed(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, showcase_built=False)
    _desktop_without_node(box)
    legacy = box.home / ".local" / "share" / "node"
    _fake_node(legacy / "bin", "v18.19.0")
    (legacy / "shared-config").write_text("shared", encoding="utf-8")

    box.run()

    assert (legacy / "shared-config").exists()
    assert (legacy / "bin" / "node").exists()


def test_versioned_portable_node_takes_precedence_over_legacy_dir(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, showcase_built=False)
    _desktop_without_node(box)
    _fake_node(box.home / ".local" / "share" / "node" / "bin", "v18.19.0")
    _fake_node(box.home / ".local" / "share" / "node-v22.23.2" / "bin", "v22.23.2")
    showcase = box.project / "apps" / "showcase_ui"
    showcase.mkdir(parents=True)

    result = box.run()

    assert result.returncode == 0, result.stderr
    assert "Node.js v22.23.2" in result.stdout
    assert not any("nodejs.org" in call for call in box.calls("curl"))

"""`artemis helper ... --serial X` must fail (exit 1) when X is not an attached device.

Reproduced on 868dd1b with a real adb 37.0.1 server and no device: `artemis helper
status --serial does-not-exist-123 --json` printed `"installed": false` and exited 0.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from artemis.interfaces.cli.commands import helper as helper_cmd
from artemis.runtime.device_pool import DeviceStatus

ROOT = Path(__file__).resolve().parents[2]


def _devices(monkeypatch, *devices: DeviceStatus) -> None:
    monkeypatch.setattr(helper_cmd.device_pool, "list_devices", lambda: list(devices))


def test_unknown_explicit_serial_exits_1(monkeypatch) -> None:
    _devices(monkeypatch)
    called = []
    monkeypatch.setattr(helper_cmd.helper_manager, "status", lambda s: called.append(s))
    result = CliRunner().invoke(helper_cmd.helper_app, ["status", "--serial", "nope", "--json"])
    assert result.exit_code == 1
    assert "not attached" in result.output
    assert called == []


def test_unauthorized_explicit_serial_exits_1(monkeypatch) -> None:
    _devices(monkeypatch, DeviceStatus(serial="abc", state="unauthorized"))
    result = CliRunner().invoke(helper_cmd.helper_app, ["status", "--serial", "abc", "--json"])
    assert result.exit_code == 1
    assert "unauthorized" in result.output


def test_attached_explicit_serial_is_used(monkeypatch) -> None:
    _devices(monkeypatch, DeviceStatus(serial="abc", state="device"))
    assert helper_cmd._resolve_serial("abc") == "abc"


@pytest.mark.skipif(shutil.which("adb") is None, reason="needs a real adb binary on PATH")
def test_real_adb_server_unknown_serial_propagates_exit_code(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "artemis", "helper", "status", "--serial", "does-not-exist-123", "--json"],
        capture_output=True, text=True, timeout=120, check=False, cwd=tmp_path,
        env={**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(ROOT)},
    )  # fmt: skip
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "not attached" in proc.stdout + proc.stderr

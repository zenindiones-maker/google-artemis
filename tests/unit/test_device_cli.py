"""`artemis device`: structure, exit codes and timeouts with a fake adbutils device.

These tests do NOT prove device control; that needs a real phone (A15, pending).
The real-adb test only proves the error path against a real adb server.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from artemis.interfaces.cli.commands import device as device_cmd
from artemis.interfaces.cli.commands import helper as helper_cmd

ROOT = Path(__file__).resolve().parents[2]
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class FakeDevice:
    def __init__(self, *, fail: str | None = None, slow: float = 0.0) -> None:
        self.fail, self.slow, self.focus, self.calls = fail, slow, "Window{1 u0 com.app/.Main}", []

    def shell2(self, cmd: str, timeout: float | None = None):
        self.calls.append(cmd)
        time.sleep(self.slow)
        if self.fail and self.fail in cmd:
            return SimpleNamespace(returncode=1, output="boom")
        out = {"getprop ro.product.model": "SM-A155M", "wm size": "Physical size: 1080x2340"}.get(
            cmd, "16"
        )
        if cmd == "dumpsys window":
            out = f"  mCurrentFocus={self.focus}\n"
        return SimpleNamespace(returncode=0, output=out)

    def shell(self, cmd: str, encoding: str | None = "utf-8", timeout: float | None = None):
        self.calls.append(cmd)
        if cmd.startswith("input keyevent"):
            self.focus = "Window{2 u0 com.launcher/.Home}"
            return ""
        return PNG if cmd == "screencap -p" else ""


@pytest.fixture
def fake(monkeypatch):
    dev = FakeDevice()
    monkeypatch.setattr(
        helper_cmd.device_pool,
        "list_devices",
        lambda: [SimpleNamespace(serial="s1", state="device")],
    )

    def driver(serial):
        from artemis.drivers.android.adb_driver import AndroidAdbDriver

        drv = AndroidAdbDriver(
            device_id=serial, adb_client=SimpleNamespace(device=lambda serial: dev)
        )
        return drv

    monkeypatch.setattr(device_cmd, "_driver", driver)
    return dev


def _invoke(*args: str):
    return CliRunner().invoke(device_cmd.device_app, list(args))


def test_info_reports_model_size_and_focus(fake) -> None:
    result = _invoke("info", "--serial", "s1", "--json")
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert (
        info["model"] == "SM-A155M"
        and "1080x2340" in info["wm_size"]
        and "com.app" in info["focus"]
    )


def test_failed_shell_command_exits_2(fake) -> None:
    fake.fail = "wm size"
    assert _invoke("info", "--serial", "s1").exit_code == 2


def test_timeout_exits_124(fake) -> None:
    fake.slow = 1.0
    assert _invoke("info", "--serial", "s1", "--timeout", "0.1").exit_code == 124


def test_unknown_serial_exits_1(fake) -> None:
    assert _invoke("info", "--serial", "nope").exit_code == 1


def test_screenshot_writes_png_with_hash_and_never_overwrites(fake, tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    result = _invoke("screenshot", "--serial", "s1", "--out", str(out))
    assert result.exit_code == 0, result.output
    meta = json.loads(result.output)
    assert meta["bytes"] == len(PNG) and out.read_bytes() == PNG
    assert _invoke("screenshot", "--serial", "s1", "--out", str(out)).exit_code == 3


def test_key_requires_yes_and_reports_focus_change(fake) -> None:
    assert _invoke("key", "home", "--serial", "s1").exit_code == 3
    assert not any(c.startswith("input") for c in fake.calls)
    result = _invoke("key", "home", "--serial", "s1", "--yes")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["focus_changed"] is True
    assert "input keyevent 3" in fake.calls


def test_device_group_is_registered_in_the_cli() -> None:
    from artemis.interfaces.cli.main import app

    assert "device" in {g.name for g in app.registered_groups}


@pytest.mark.skipif(shutil.which("adb") is None, reason="needs a real adb binary on PATH")
def test_real_adb_unknown_serial_exits_1(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "artemis", "device", "info", "--serial", "does-not-exist-123"],
        capture_output=True, text=True, timeout=120, check=False, cwd=tmp_path,
        env={**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(ROOT)},
    )  # fmt: skip
    assert proc.returncode == 1, proc.stdout + proc.stderr

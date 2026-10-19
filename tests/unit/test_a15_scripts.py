"""Structure tests for scripts/a15_validate.sh and scripts/a15_preflight.sh.

STRUCTURE ONLY: adb and artemis are stub binaries here, so these tests prove the
script's control flow (timeouts, exit codes, confirmation gate, write scope, no
network), never that ARTEMIS controls a phone. That is validated only on the A15.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATE = ROOT / "scripts" / "a15_validate.sh"
PREFLIGHT = ROOT / "scripts" / "a15_preflight.sh"
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="POSIX"
)
NETWORK_TOOLS = ("curl", "wget", "nc", "ssh", "scp", "rsync", "ftp", "telnet")


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _sandbox(
    tmp_path: Path, *, devices: str = "", error_exit: int = 1, hang: bool = False, answer: str = ""
):
    home, stubs, venv = tmp_path / "home", tmp_path / "stubs", tmp_path / "venv"
    log = tmp_path / "calls.log"
    rec = f'echo "$(basename "$0") $*" >> "{log}"'
    _exe(
        stubs / "adb",
        rec
        + f"""
case "$*" in
  "devices -l") printf 'List of devices attached\\n{devices}' ;;
  *getprop*) echo SM-A155M ;;
  *"wm size"*) echo "Physical size: 1080x2340" ;;
  version) echo "Android Debug Bridge version 1.0.41" ;;
esac""",
    )
    for tool in NETWORK_TOOLS:
        _exe(stubs / tool, rec + "\nexit 99")
    _exe(stubs / "getprop", "echo stub")
    _exe(
        venv / "bin" / "python",
        f'case "$1" in *termux_probe_metrics.py) echo metrics-stub;; *) exec {sys.executable} "$@";; esac',
    )
    hang_line = "sleep 30" if hang else "true"
    _exe(
        venv / "bin" / "artemis",
        rec
        + f"""
case "$*" in
  --version) echo "Artemis v1.0" ;;
  --help) {hang_line}; echo usage ;;
  "doctor --json") echo '{{"key": "AIzaSy...abcd"}}' ;;
  *does-not-exist-000*) exit {error_exit} ;;
  "device info"*) echo '{{"model": "SM-A155M"}}' ;;
  "device screenshot"*) out=$(echo "$*" | sed 's/.*--out //'); printf 'PNG' > "$out" ;;
  "device key"*) echo '{{"focus_changed": true}}' ;;
esac""",
    )
    tty = tmp_path / "tty"
    tty.write_text(answer + "\n")
    env = {"HOME": str(home), "PATH": f"{stubs}:/usr/bin:/bin", "ARTEMIS_VENV": str(venv),
           "ARTEMIS_REPO": str(ROOT), "A15_TTY": str(tty), "STEP_TIMEOUT": "5", "LANG": "C.UTF-8"}  # fmt: skip
    home.mkdir()
    return env, log, home


def _run(env, *, netns: bool = False):
    cmd = ["bash", str(VALIDATE)]
    if netns and shutil.which("unshare"):
        cmd = ["unshare", "-rn", *cmd]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)


def _files_outside_validation(home: Path) -> list[str]:
    return [str(p) for p in home.rglob("*") if p.is_file() and "artemis-validation" not in p.parts]


def test_no_device_prints_pairing_steps_and_fails(tmp_path: Path) -> None:
    env, log, home = _sandbox(tmp_path)
    proc = _run(env)
    assert proc.returncode == 1
    assert "adb pair 127.0.0.1:<pairing-port> <code>" in proc.stdout
    assert "adb connect 127.0.0.1:<connect-port>" in proc.stdout
    assert "device key" not in log.read_text()


def test_device_without_confirmation_passes_and_sends_no_input(tmp_path: Path) -> None:
    env, log, home = _sandbox(
        tmp_path, devices="R58X123\\tdevice usb:1 model:SM_A155M\\n", answer="no"
    )
    proc = _run(env, netns=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = log.read_text()
    assert "device key" not in calls and "input" not in calls
    assert (
        "input test (not confirmed)\toptional\tSKIP" in next(home.rglob("summary.tsv")).read_text()
    )
    assert not any(t in calls for t in NETWORK_TOOLS)
    assert _files_outside_validation(home) == []
    assert "AIzaSy...abcd" not in "".join(p.read_text() for p in home.rglob("*.log"))


def test_typed_sim_sends_exactly_one_home_key(tmp_path: Path) -> None:
    env, log, _ = _sandbox(tmp_path, devices="R58X123\\tdevice\\n", answer="SIM")
    proc = _run(env)
    assert proc.returncode == 0, proc.stdout
    keys = [c for c in log.read_text().splitlines() if "device key" in c]
    assert keys == ["artemis device key home --serial R58X123 --yes"]


def test_swallowed_error_makes_the_run_fail(tmp_path: Path) -> None:
    env, _, _ = _sandbox(tmp_path, devices="R58X123\\tdevice\\n", error_exit=0)
    proc = _run(env)
    assert proc.returncode == 1
    assert re.search(r"error propagates.*FAIL", proc.stdout)


def test_hanging_step_times_out_and_is_reported(tmp_path: Path) -> None:
    env, _, _ = _sandbox(tmp_path, devices="R58X123\\tdevice\\n", hang=True)
    proc = _run(env)
    assert proc.returncode == 1
    assert re.search(r"artemis --help\s+mandatory\s+TIMEOUT\s+124", proc.stdout)


def test_validation_script_contains_no_network_or_upload_commands() -> None:
    code = [ln for ln in VALIDATE.read_text().splitlines() if not ln.lstrip().startswith("#")]
    words = re.compile(
        r"\b(curl|wget|nc|ssh|scp|rsync|ftp|telnet|pip install|pkg install)\b|https?://"
    )
    assert [ln for ln in code if words.search(ln)] == []
    # Pairing commands only appear in the printed help text (indented heredoc), never run.
    assert [ln for ln in code if re.match(r"^\s*adb (pair|connect)\b", ln)] == []


def test_preflight_is_read_only(tmp_path: Path) -> None:
    body = PREFLIGHT.read_text()
    for forbidden in ("pkg install", "apt install", "apt-get", "pip install", "rm -", "adb pair", "adb connect",
                      "adb start-server", "mkdir", "curl", "wget"):  # fmt: skip
        assert forbidden not in body
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(["bash", str(PREFLIGHT)], env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True, timeout=120)  # fmt: skip
    assert proc.returncode == 0
    assert "nada foi alterado" in proc.stdout
    assert list(home.rglob("*")) == []


def test_pasted_as_heredoc_falls_back_to_the_clone(tmp_path: Path) -> None:
    env, _, home = _sandbox(tmp_path, devices="R58X123\\tdevice\\n")
    env.pop("ARTEMIS_REPO")
    (home / "google-artemis").symlink_to(ROOT)
    proc = subprocess.run(
        ["bash"], input=VALIDATE.read_text(), env=env, capture_output=True, text=True, timeout=300
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

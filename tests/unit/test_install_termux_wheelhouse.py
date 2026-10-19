"""install_termux.sh --wheelhouse: verify before installing, offline install, safe failure.

All Termux commands are stubs; verify_artifacts.py runs for real. This proves the
installer logic only; the real wheelhouse comes from CI and the real install is on
the A15 (both pending).
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_termux.sh"
spec = importlib.util.spec_from_file_location(
    "tpm_wh", ROOT / "scripts" / "termux_probe_metrics.py"
)
assert spec and spec.loader
tpm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tpm
spec.loader.exec_module(tpm)
spec2 = importlib.util.spec_from_file_location("va_wh", ROOT / "scripts" / "verify_artifacts.py")
assert spec2 and spec2.loader
va = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(va)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="POSIX"
)

PINS = va.read_pins(ROOT / "requirements" / "termux-constraints.txt")
SOURCE_BUILT = va.read_names(ROOT / "requirements" / "termux-source-built.txt")


def make_wheelhouse(
    directory: Path, *, skip: str | None = None, plat: str = "android_24_arm64_v8a"
) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    for name in SOURCE_BUILT:
        if name == skip:
            continue
        dist = name.replace("-", "_")
        (directory / f"{dist}-{PINS[name]}-cp314-cp314-{plat}.whl").write_bytes(
            f"wheel {name}".encode()
        )
    (directory / "artemis-1.0-py3-none-any.whl").write_bytes(b"artemis")
    return (
        tpm.write_wheelhouse_manifest(
            directory,
            source_commit="c" * 40,
            run_id="123",
            python_version="3.14.8",
            termux_packages={"python": "3.14.8"},
        )
        if plat.startswith("android")
        else ""
    )


def _stub(directory: Path, name: str, body: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / name
    exe.write_text(f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\n{body}\nexit 0\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)


def run(tmp_path: Path, *args: str, existing_venv: bool = True):
    stubs, sysbin, home = tmp_path / "stubs", tmp_path / "sysbin", tmp_path / "home"
    sysbin.mkdir()
    for tool in (
        "bash",
        "sh",
        "env",
        "cat",
        "sed",
        "dirname",
        "mkdir",
        "find",
        "wc",
        "du",
        "cut",
        "df",
        "awk",
        "grep",
    ):
        real = shutil.which(tool)
        if real:
            (sysbin / tool).symlink_to(real)
    prefix = tmp_path / "data/data/com.termux/files/usr"
    (prefix / "lib").mkdir(parents=True)
    _stub(stubs, "pkg")
    _stub(stubs, "dpkg-query")
    _stub(
        stubs,
        "python",
        body=f'case "$1" in *verify_artifacts.py) exec {sys.executable} "$@";; -c) echo 24;; esac',
    )
    venv = home / ".artemis-venv"
    if existing_venv:
        _stub(venv / "bin", "python")
        _stub(venv / "bin", "artemis")
        (venv / "user-data.txt").write_text("keep me")
    log = tmp_path / "calls.log"
    env = {"HOME": str(home), "PATH": f"{stubs}:{sysbin}", "STUB_LOG": str(log), "PREFIX": str(prefix),
           "TERMUX_VERSION": "0.118.3", "TMPDIR": str(tmp_path)}  # fmt: skip
    home.mkdir(exist_ok=True)
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=120
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls, venv


def _pip(calls):
    return [c for c in calls if "-m pip install" in c]


def test_valid_wheelhouse_installs_offline_without_toolchain(tmp_path: Path) -> None:
    sums = make_wheelhouse(tmp_path / "wh")
    proc, calls, venv = run(
        tmp_path, "--wheelhouse", str(tmp_path / "wh"), "--expect-sums-sha256", sums
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    pkg = " ".join(c for c in calls if c.startswith("pkg "))
    for tool in ("rust", "clang", "build-essential"):
        assert f" {tool} " not in f" {pkg} "
    assert _pip(calls) and all("--no-index --find-links" in c for c in _pip(calls))
    assert (venv / "user-data.txt").read_text() == "keep me"


@pytest.mark.parametrize("args", [["--wheelhouse", "/does/not/exist", "--expect-sums-sha256", "0" * 64],
                                  ["--wheelhouse", "WH"]])  # fmt: skip
def test_missing_wheelhouse_or_pin_fails_before_any_change(tmp_path: Path, args: list[str]) -> None:
    make_wheelhouse(tmp_path / "wh")
    args = [str(tmp_path / "wh") if a == "WH" else a for a in args]
    proc, calls, venv = run(tmp_path, *args)
    assert proc.returncode == 4
    assert calls == []
    assert (venv / "user-data.txt").read_text() == "keep me"


def test_tampered_wheel_is_rejected_before_venv_and_pip(tmp_path: Path) -> None:
    sums = make_wheelhouse(tmp_path / "wh")
    victim = next((tmp_path / "wh").glob("pydantic_core-*.whl"))
    victim.write_bytes(victim.read_bytes() + b"x")
    proc, calls, venv = run(tmp_path, "--wheelhouse", str(tmp_path / "wh"), "--expect-sums-sha256", sums,
                            existing_venv=False)  # fmt: skip
    assert proc.returncode == 5
    assert "MISMATCH" in proc.stderr
    assert not any("venv" in c for c in calls) and _pip(calls) == []
    assert not venv.exists()


def test_wheelhouse_from_another_run_is_rejected(tmp_path: Path) -> None:
    make_wheelhouse(tmp_path / "wh")
    proc, calls, _ = run(
        tmp_path, "--wheelhouse", str(tmp_path / "wh"), "--expect-sums-sha256", "f" * 64
    )
    assert proc.returncode == 5 and "not the CI run you pinned" in proc.stderr
    assert _pip(calls) == []


def test_missing_source_built_wheel_fails_unless_allow_build(tmp_path: Path) -> None:
    sums = make_wheelhouse(tmp_path / "wh", skip="pydantic-core")
    proc, calls, _ = run(
        tmp_path, "--wheelhouse", str(tmp_path / "wh"), "--expect-sums-sha256", sums
    )
    assert proc.returncode == 5 and "NOT COVERED pydantic-core" in proc.stderr
    assert _pip(calls) == []
    proc, calls, _ = run(tmp_path / "again" if (tmp_path / "again").mkdir() is None else tmp_path,
                         "--wheelhouse", str(tmp_path / "wh"), "--expect-sums-sha256", sums, "--allow-build")  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert any(c == "pkg install -y rust clang build-essential" for c in calls)
    assert all("--prefer-binary --find-links" in c for c in _pip(calls))


def test_generic_linux_aarch64_wheel_is_rejected(tmp_path: Path) -> None:
    sums = make_wheelhouse(tmp_path / "wh")
    bad = tmp_path / "wh" / "evil-1.0-cp314-cp314-linux_aarch64.whl"
    bad.write_bytes(b"x")
    # Re-sign the sums so only the platform rule can catch it.
    lines = (
        tmp_path / "wh" / "SHA256SUMS"
    ).read_text() + f"{hashlib.sha256(b'x').hexdigest()}  {bad.name}\n"
    (tmp_path / "wh" / "SHA256SUMS").write_text(lines)
    sums = hashlib.sha256(lines.encode()).hexdigest()
    proc, _, _ = run(tmp_path, "--wheelhouse", str(tmp_path / "wh"), "--expect-sums-sha256", sums)
    assert proc.returncode == 5
    assert "INCONSISTENT" in proc.stderr or "WRONG PLATFORM" in proc.stderr


def test_dry_run_shows_plan_and_changes_nothing(tmp_path: Path) -> None:
    sums = make_wheelhouse(tmp_path / "wh")
    proc, calls, _ = run(
        tmp_path, "--dry-run", "--wheelhouse", str(tmp_path / "wh"), "--expect-sums-sha256", sums
    )
    assert proc.returncode == 0, proc.stderr
    assert calls == []
    assert "Wheelhouse: 14 wheels" in proc.stdout and "Free space in HOME" in proc.stdout
    assert "skipping build toolchain" in proc.stdout
    assert "--no-index --find-links" in proc.stdout


def test_manifest_writer_refuses_generic_linux_wheels(tmp_path: Path) -> None:
    (tmp_path / "x-1.0-cp314-cp314-linux_aarch64.whl").write_bytes(b"x")
    with pytest.raises(ValueError):
        tpm.write_wheelhouse_manifest(
            tmp_path, source_commit="c", run_id="1", python_version="3.14", termux_packages={}
        )


def test_manifest_and_sums_must_agree(tmp_path: Path) -> None:
    make_wheelhouse(tmp_path / "wh")
    manifest = tmp_path / "wh" / "manifest.json"
    text = manifest.read_text().replace('"run_id": "123"', '"run_id": "999"')
    manifest.write_text(text)  # manifest edited after SHA256SUMS was written
    problems = va.check_wheelhouse(tmp_path / "wh")
    assert any(p.startswith("MISMATCH manifest.json") for p in problems)


def test_probe_builds_and_offline_installs_the_wheelhouse() -> None:
    probe = (ROOT / "scripts" / "termux_ci_probe.sh").read_text()
    assert "wheelhouse-manifest" in probe and "--expect-sums-sha256" in probe
    assert "termux-source-built.txt" in probe
    wf = (ROOT / ".github" / "workflows" / "termux-docker-probe.yml").read_text()
    assert "termux-wheelhouse-cp314-android24-arm64-${{ github.sha }}" in wf
    assert "permissions:\n  contents: read" in wf

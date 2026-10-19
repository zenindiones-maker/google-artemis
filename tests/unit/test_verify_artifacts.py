"""Case 6: artifact integrity. A wheel listed in a SHA256SUMS manifest is accepted;
a tampered, missing or unlisted artifact is rejected.

On 3e8927f no verifier existed (case 6 not executable). scripts/verify_artifacts.py is
a stdlib-only checker; integrity only, authenticity still needs
``gh attestation verify`` (E4, pending).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_artifacts.py"


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    wheel = tmp_path / "artemis-0.0.0-py3-none-any.whl"
    wheel.write_bytes(b"PK\x03\x04 fake wheel bytes")
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n")
    return wheel, manifest


def _verify(manifest: Path, *files: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(manifest), *map(str, files)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_untouched_wheel_is_accepted(tmp_path: Path) -> None:
    wheel, manifest = _setup(tmp_path)
    proc = _verify(manifest, wheel)
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_tampered_wheel_is_rejected(tmp_path: Path) -> None:
    wheel, manifest = _setup(tmp_path)
    wheel.write_bytes(wheel.read_bytes() + b"x")
    proc = _verify(manifest, wheel)
    assert proc.returncode == 1
    assert "MISMATCH" in proc.stderr


def test_unlisted_and_missing_artifacts_are_rejected(tmp_path: Path) -> None:
    _, manifest = _setup(tmp_path)
    other = tmp_path / "other.whl"
    other.write_bytes(b"x")
    assert _verify(manifest, other).returncode == 1
    assert _verify(manifest, tmp_path / "absent.whl").returncode == 1


def test_malformed_manifest_is_rejected(tmp_path: Path) -> None:
    wheel, manifest = _setup(tmp_path)
    manifest.write_text("not-a-hash  " + wheel.name + "\n")
    assert _verify(manifest, wheel).returncode == 2

"""Stubbed regression tests for scripts/termux_probe_metrics.py and its probe wiring."""

from __future__ import annotations

import csv
import importlib.util
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "termux_probe_metrics.py"
PROBE = ROOT / "scripts" / "termux_ci_probe.sh"
CONSTRAINTS = ROOT / "requirements" / "termux-constraints.txt"

spec = importlib.util.spec_from_file_location("termux_probe_metrics", SCRIPT)
assert spec and spec.loader
metrics = importlib.util.module_from_spec(spec)
sys.modules["termux_probe_metrics"] = metrics
spec.loader.exec_module(metrics)


def _fake_python(tmp_path: Path, fail: set[str]) -> Path:
    """A fake interpreter: `<it> -m pip wheel ... name==ver` writes a temp file, fails for `fail`."""
    fake = tmp_path / "fakepy"
    fake.write_text(
        "#!/bin/sh\n"
        'last=""; for a in "$@"; do last="$a"; done\n'
        'head -c 4096 /dev/zero > "$TMPDIR/blob"\n'
        'echo "building $last"\n'
        + "".join(f'case "$last" in {n}==*) exit 3;; esac\n' for n in fail)
        + "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake


def _constraints(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "c.txt"
    path.write_text(text)
    return path


def test_build_each_success_writes_csv_and_markdown(tmp_path: Path) -> None:
    c = _constraints(tmp_path, "orjson==3.11.0\nPyYAML==6.0.3\n")
    py = _fake_python(tmp_path, set())
    out = tmp_path / "out"
    rc = metrics.main(
        ["build-each", "--constraints", str(c), "--out", str(out), "--python", str(py),
         "--interval", "0.01", "orjson", "pyyaml"]
    )  # fmt: skip
    assert rc == 0
    rows = list(csv.DictReader((out / "source-builds.csv").open()))
    assert [(r["package"], r["version"], r["result"]) for r in rows] == [
        ("orjson", "3.11.0", "ok"),
        ("PyYAML", "6.0.3", "ok"),
    ]
    assert all(int(r["peak_build_tmp_bytes"]) >= 4096 for r in rows)
    assert all(float(r["wall_seconds"]) >= 0 for r in rows)
    md = (out / "source-builds.md").read_text()
    assert "| orjson | 3.11.0 |" in md and "ok" in md
    assert (out / "logs" / "build-orjson.log").read_text().startswith("building orjson==3.11.0")


def test_build_each_failure_is_reported_and_exits_nonzero(tmp_path: Path) -> None:
    c = _constraints(tmp_path, "orjson==3.11.0\nregex==2026.1.1\n")
    py = _fake_python(tmp_path, {"regex"})
    out = tmp_path / "out"
    rc = metrics.main(
        ["build-each", "--constraints", str(c), "--out", str(out), "--python", str(py),
         "--interval", "0.01", "orjson", "regex"]
    )  # fmt: skip
    assert rc == 1
    rows = {r["package"]: r["result"] for r in csv.DictReader((out / "source-builds.csv").open())}
    assert rows == {"orjson": "ok", "regex": "fail"}


def test_build_each_unpinned_package_fails(tmp_path: Path) -> None:
    c = _constraints(tmp_path, "orjson==3.11.0\n")
    py = _fake_python(tmp_path, set())
    rc = metrics.main(
        ["build-each", "--constraints", str(c), "--out", str(tmp_path / "o"), "--python",
         str(py), "--interval", "0.01", "orjson", "tornado"]
    )  # fmt: skip
    assert rc == 1


def test_read_pins_rejects_non_exact(tmp_path: Path) -> None:
    with pytest.raises((ValueError, SystemExit)):
        metrics.read_pins(_constraints(tmp_path, "orjson>=3\n"))
    pins = metrics.read_pins(
        _constraints(tmp_path, "# c\n\nPyYAML==6.0.3\npydantic_core==2.50.1\n")
    )
    assert pins["pyyaml"] == ("PyYAML", "6.0.3")
    assert "pydantic-core" in pins


def test_verify_pins_reports_missing_and_mismatch() -> None:
    pins = {"a": ("a", "1.0"), "b": ("b", "2.0"), "c": ("c", "3.0")}
    problems = metrics.verify_pins(pins, {"a": "1.0", "b": "2.1"})
    assert problems == ["b: installed 2.1, pinned 2.0", "c: not installed (pinned 3.0)"]
    assert metrics.verify_pins(pins, {"a": "1.0", "b": "2.0", "c": "3.0"}) == []


def test_verify_command_exit_codes_and_exclude(tmp_path: Path, monkeypatch) -> None:
    c = _constraints(tmp_path, "a==1.0\nb==2.0\n")
    monkeypatch.setattr(metrics, "installed_versions", lambda: {"a": "1.0"})
    assert metrics.main(["verify", "--constraints", str(c)]) == 1
    assert metrics.main(["verify", "--constraints", str(c), "--exclude", "b"]) == 0


def test_sample_and_summarize_peak_and_final(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "f").write_bytes(b"x" * 1000)
    samples = tmp_path / "s.csv"
    stop = tmp_path / "stop"
    rc = metrics.main(
        ["sample", "--out", str(samples), "--stop-file", str(stop), "--interval", "0.01",
         "--max-samples", "2", str(d), str(tmp_path / "missing")]
    )  # fmt: skip
    assert rc == 0
    assert samples.exists()
    # Synthetic samples: peak must be the max, final the last value.
    samples.write_text(
        "timestamp,path,bytes\n1,/h,100\n1,/p,10\n2,/h,500\n2,/p,20\n3,/h,200\n3,/p,30\n"
    )
    summary = metrics.summarize_samples(samples)
    assert summary["/h"] == (500, 200)
    assert summary["/p"] == (30, 30)
    md_out = tmp_path / "disk.md"
    assert metrics.main(["summarize", str(samples), "--out", str(md_out)]) == 0
    assert "TOTAL" in md_out.read_text()


def test_constraints_are_exact_and_without_inert_setuptools_pin() -> None:
    pins = metrics.read_pins(CONSTRAINTS)
    assert "setuptools" not in pins
    for pkg in ("pydantic-core", "jiter", "orjson", "ormsgpack", "uuid-utils", "tiktoken",
                "watchfiles", "zstandard", "regex", "tornado", "httptools", "uvloop", "pyyaml"):  # fmt: skip
        assert pkg in pins, pkg


def test_probe_wires_metrics_as_critical_steps_in_order() -> None:
    text = PROBE.read_text()
    builds = text.index('step critical "probe: per-package source builds"')
    sampler = text.index("sample --out")
    install = text.index('step critical "scripts/install_termux.sh"')
    pip_check = text.index('step critical "pip check"')
    verify = text.index("verify --constraints")
    assert builds < sampler < install < pip_check < verify
    assert 'step optional "pip check"' not in text
    assert 'touch "${STOP_FILE}"' in text
    assert "PIP_NO_CACHE_DIR=1" in text  # real install not served from probe-built wheels
    assert "source-builds.md" in text and "disk-usage.md" in text

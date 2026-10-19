"""Unit tests for the `startup` collector in scripts/termux_probe_metrics.py.

They validate parsing, aggregation and output format only (stub interpreters); they
say nothing about performance in the probe environment.
"""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "termux_probe_metrics.py"
spec = importlib.util.spec_from_file_location("termux_probe_metrics_startup", SCRIPT)
assert spec and spec.loader
metrics = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = metrics
spec.loader.exec_module(metrics)

REC = {
    "seconds": 1.0,
    "modules": 100,
    "rss_kb": 2048,
    "rss_source": "/proc/self/status VmHWM",
    "heavy": [],
}


def test_parse_takes_last_startup_json_line_and_ignores_noise() -> None:
    text = (
        "noise\nSTARTUP_JSON "
        + json.dumps(REC)
        + "\nSTARTUP_JSON "
        + json.dumps({**REC, "modules": 7})
    )
    assert metrics.parse_startup_output(text)["modules"] == 7


@pytest.mark.parametrize("text", ["", "hello", "STARTUP_JSON " + json.dumps({"seconds": 1})])
def test_parse_rejects_missing_or_incomplete_records(text: str) -> None:
    with pytest.raises(ValueError):
        metrics.parse_startup_output(text)


def test_summary_uses_median_and_unions_heavy_modules() -> None:
    runs = [
        {**REC, "seconds": 3.0, "modules": 120, "rss_kb": 4096, "heavy": ["numpy"]},
        {**REC, "seconds": 1.0, "modules": 100, "rss_kb": 1024, "heavy": []},
        {**REC, "seconds": 2.0, "modules": 110, "rss_kb": 2048, "heavy": ["aiohttp"]},
    ]
    summary = metrics.summarize_startup(runs)
    assert summary["runs"] == 3
    assert summary["seconds_median"] == 2.0
    assert (summary["modules_median"], summary["modules_min"], summary["modules_max"]) == (
        110,
        100,
        120,
    )
    assert summary["rss_mb_median"] == 2.0
    assert summary["heavy_loaded"] == ["aiohttp", "numpy"]
    with pytest.raises(ValueError):
        metrics.summarize_startup([])


def test_markdown_states_units_method_and_environment() -> None:
    md = metrics.startup_markdown(metrics.summarize_startup([REC]), "ENV-LABEL", warmup=1)
    for needle in (
        "MiB",
        "VmHWM",
        "len(sys.modules)",
        "median",
        "ENV-LABEL",
        "after 1 warm-up",
        "| none |",
    ):
        assert needle in md


def _stub_python(tmp_path: Path, body: str) -> Path:
    exe = tmp_path / "python"
    exe.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX stub interpreter")
def test_cli_discards_warmup_and_writes_json_and_markdown(tmp_path: Path) -> None:
    rec = json.dumps({**REC, "heavy": ["cv2"]})
    py = _stub_python(
        tmp_path, f"case \"$2\" in *version*) echo 3.14.8;; *) echo 'STARTUP_JSON {rec}';; esac"
    )
    out = tmp_path / "out"
    assert metrics.main(["startup", "--python", str(py), "--out", str(out), "--runs", "3", "--warmup", "2",
                         "--environment", "stub"]) == 0  # fmt: skip
    data = json.loads((out / "startup-metrics.json").read_text())
    assert data["warmup"] == 2 and len(data["runs"]) == 3
    assert data["summary"]["heavy_loaded"] == ["cv2"]
    assert "cv2" in (out / "startup-metrics.md").read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX stub interpreter")
def test_cli_fails_when_the_child_fails(tmp_path: Path) -> None:
    py = _stub_python(tmp_path, "echo boom >&2; exit 3")
    assert (
        metrics.main(["startup", "--python", str(py), "--out", str(tmp_path / "o"), "--runs", "1"])
        == 1
    )


def test_probe_script_runs_the_collector_and_reports_it() -> None:
    probe = (ROOT / "scripts" / "termux_ci_probe.sh").read_text(encoding="utf-8")
    assert '"${METRICS}" startup --out "${OUT}"' in probe
    assert "startup-metrics.md" in probe
    assert "not a device" in probe

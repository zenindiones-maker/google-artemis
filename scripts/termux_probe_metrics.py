#!/usr/bin/env python3
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

"""Measurement helpers for the Termux-in-Docker probe (CI only, stdlib only).

Subcommands:

* ``build-each``: build each source-built package alone (``pip wheel --no-deps``
  at the version pinned in the constraints file), recording wall time, result
  and peak disk usage of its private build temp dir. Exit 1 if any build fails.
* ``sample``: sample disk usage of paths every N seconds until a stop file
  appears; ``summarize`` reports peak and final values.
* ``verify``: check that every pinned package is installed at its exact version
  (``importlib.metadata`` of the interpreter running this script). Exit 1 on
  any mismatch or missing package.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_NAME_RE = re.compile(r"[-_.]+")


def canonical(name: str) -> str:
    return _NAME_RE.sub("-", name).lower()


def read_pins(path: Path) -> dict[str, tuple[str, str]]:
    """Return {canonical name: (original name, version)} for 'name==version' lines."""
    pins: dict[str, tuple[str, str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise ValueError(f"constraint is not an exact pin: {raw!r}")
        name, version = (part.strip() for part in line.split("==", 1))
        pins[canonical(name)] = (name, version)
    return pins


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def human(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


# --- build-each -------------------------------------------------------------


@dataclass
class BuildResult:
    name: str
    version: str
    seconds: float
    ok: bool
    peak_tmp_bytes: int
    detail: str = ""


def build_one(
    pip_cmd: list[str], name: str, version: str, wheel_dir: Path, log_dir: Path, interval: float
) -> BuildResult:
    tmp = Path(tempfile.mkdtemp(prefix=f"build-{canonical(name)}-"))
    peak = 0
    done = threading.Event()

    def sampler() -> None:
        nonlocal peak
        while not done.is_set():
            peak = max(peak, dir_size(tmp))
            done.wait(interval)

    env = dict(os.environ, TMPDIR=str(tmp), TMP=str(tmp), TEMP=str(tmp))
    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()
    start = time.monotonic()
    log_path = log_dir / f"build-{canonical(name)}.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            [
                *pip_cmd,
                "wheel",
                "--no-deps",
                "--no-binary",
                name,
                "-w",
                str(wheel_dir),
                f"{name}=={version}",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
    seconds = time.monotonic() - start
    done.set()
    thread.join()
    peak = max(peak, dir_size(tmp))
    shutil.rmtree(tmp, ignore_errors=True)  # private temp dir created above
    detail = "" if proc.returncode == 0 else f"exit {proc.returncode}, see {log_path.name}"
    return BuildResult(name, version, seconds, proc.returncode == 0, peak, detail)


def sampling_note(interval: float) -> str:
    return (
        f"Sampling interval: {interval:g} s. Peak = largest observed sample; "
        "short spikes between samples may be missed, so the true peak can be higher."
    )


def write_build_reports(
    results: list[BuildResult], out_dir: Path, interval: float | None = None
) -> str:
    with (out_dir / "source-builds.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["package", "version", "wall_seconds", "result", "peak_build_tmp_bytes"])
        for r in results:
            writer.writerow(
                [r.name, r.version, f"{r.seconds:.1f}", "ok" if r.ok else "fail", r.peak_tmp_bytes]
            )
    lines = [
        "| package | version | wall time | result | peak build-temp disk |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        result = "ok" if r.ok else f"FAIL ({r.detail})"
        lines.append(
            f"| {r.name} | {r.version} | {r.seconds:.1f} s | {result} | {human(r.peak_tmp_bytes)} |"
        )
    total = sum(r.seconds for r in results)
    failed = [r.name for r in results if not r.ok]
    lines.append("")
    lines.append(f"Total build time: {total:.1f} s; failed: {', '.join(failed) or 'none'}")
    if interval is not None:
        lines.append("")
        lines.append("Build-temp disk: " + sampling_note(interval))
    markdown = "\n".join(lines) + "\n"
    (out_dir / "source-builds.md").write_text(markdown, encoding="utf-8")
    return markdown


def cmd_build_each(args: argparse.Namespace) -> int:
    pins = read_pins(args.constraints)
    out_dir: Path = args.out
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)
    wheel_dir = out_dir / "wheels"
    wheel_dir.mkdir(exist_ok=True)
    results = []
    for package in args.packages:
        key = canonical(package)
        if key not in pins:
            results.append(BuildResult(package, "?", 0.0, False, 0, "not pinned in constraints"))
            continue
        name, version = pins[key]
        results.append(
            build_one(
                [args.python, "-m", "pip"],
                name,
                version,
                wheel_dir,
                out_dir / "logs",
                args.interval,
            )
        )
    sys.stdout.write(write_build_reports(results, out_dir, args.interval))
    return 0 if all(r.ok for r in results) else 1


# --- disk sampler -------------------------------------------------------------


def cmd_sample(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths]
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "path", "bytes"])
        while True:
            now = f"{time.time():.0f}"
            for path in paths:
                writer.writerow([now, str(path), dir_size(path) if path.exists() else 0])
            fh.flush()
            if args.stop_file.exists() or (args.max_samples and args.max_samples <= 1):
                return 0
            if args.max_samples:
                args.max_samples -= 1
            time.sleep(args.interval)


def summarize_samples(csv_path: Path) -> dict[str, tuple[int, int]]:
    """Return {path: (peak bytes, final bytes)} plus a 'TOTAL' entry per timestamp sum."""
    per_path: dict[str, list[int]] = {}
    totals: dict[str, int] = {}
    with csv_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            size = int(row["bytes"])
            per_path.setdefault(row["path"], []).append(size)
            totals[row["timestamp"]] = totals.get(row["timestamp"], 0) + size
    result = {path: (max(sizes), sizes[-1]) for path, sizes in per_path.items()}
    if totals:
        ordered = [totals[k] for k in sorted(totals, key=float)]
        result["TOTAL"] = (max(ordered), ordered[-1])
    return result


def cmd_summarize(args: argparse.Namespace) -> int:
    summary = summarize_samples(args.samples)
    lines = ["| path | peak | final |", "|---|---|---|"]
    for path, (peak, final) in summary.items():
        lines.append(f"| {path} | {human(peak)} | {human(final)} |")
    lines.append("")
    if args.interval is not None:
        lines.append(sampling_note(args.interval))
    else:
        lines.append("Peak = largest observed sample; short spikes between samples may be missed.")
    markdown = "\n".join(lines) + "\n"
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
    sys.stdout.write(markdown)
    return 0


# --- verify -----------------------------------------------------------------


def verify_pins(pins: dict[str, tuple[str, str]], installed: dict[str, str]) -> list[str]:
    problems = []
    for key, (name, version) in sorted(pins.items()):
        have = installed.get(key)
        if have is None:
            problems.append(f"{name}: not installed (pinned {version})")
        elif have != version:
            problems.append(f"{name}: installed {have}, pinned {version}")
    return problems


def installed_versions() -> dict[str, str]:
    from importlib import metadata

    versions: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            versions.setdefault(canonical(name), dist.version)
    return versions


def unpinned_in_prefix(pins: dict[str, tuple[str, str]], prefix_dists: dict[str, str],
                       allowed: set[str]) -> list[str]:  # fmt: skip
    """Dists installed inside the venv itself that the constraints do not pin."""
    return [
        f"{name}=={version}: installed in the venv but not pinned in constraints"
        for name, version in sorted(prefix_dists.items())
        if name not in pins and name not in allowed
    ]


def venv_versions() -> dict[str, str]:
    """Dists located under sys.prefix (the venv), excluding system-site (pkg) ones."""
    from importlib import metadata

    prefix = Path(sys.prefix).resolve()
    versions: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        location = Path(str(dist.locate_file(""))).resolve()
        if name and location.is_relative_to(prefix):
            versions.setdefault(canonical(name), dist.version)
    return versions


def cmd_verify(args: argparse.Namespace) -> int:
    pins = read_pins(args.constraints)
    for excluded in args.exclude:
        pins.pop(canonical(excluded), None)
    problems = verify_pins(pins, installed_versions())
    if args.require_all_pinned:
        allowed = {canonical(n) for n in args.allow_unpinned}
        problems += unpinned_in_prefix(pins, venv_versions(), allowed)
    if problems:
        print(f"{len(problems)} problem(s) with exact-version pinning:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"All {len(pins)} pinned packages installed at their exact versions.")
    return 0


# --- startup metrics for `artemis --help` ---------------------------------------

HEAVY_MODULES = (
    "cv2", "numpy", "scipy", "matplotlib", "pyarrow", "grpc", "jupyter_client", "zmq",
    "ipykernel", "imageio_ffmpeg", "uvicorn", "starlette", "fastapi", "aiohttp",
    "google.genai", "langchain_openai", "langchain_anthropic", "langchain_google_vertexai",
)  # fmt: skip

# Runs in a fresh interpreter: time = import of the CLI + `--help`; modules = size of
# sys.modules afterwards; RSS = peak resident set (VmHWM, kB) of that process.
STARTUP_CHILD = """
import contextlib, io, json, sys, time
t0 = time.perf_counter()
sys.argv = ["artemis", "--help"]
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    from artemis.interfaces.cli.main import cli
    try:
        cli()
    except SystemExit:
        pass
elapsed = time.perf_counter() - t0
rss_kb, rss_source = None, None
try:
    for line in open("/proc/self/status", encoding="ascii"):
        if line.startswith("VmHWM:"):
            rss_kb, rss_source = int(line.split()[1]), "/proc/self/status VmHWM"
except OSError:
    pass
if rss_kb is None:
    import resource
    rss_kb, rss_source = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "getrusage ru_maxrss"
heavy = sorted(m for m in HEAVY if m in sys.modules)
print("STARTUP_JSON " + json.dumps({"seconds": elapsed, "modules": len(sys.modules),
      "rss_kb": rss_kb, "rss_source": rss_source, "heavy": heavy}), file=sys.__stdout__)
"""


def parse_startup_output(text: str) -> dict:
    """Return the JSON record printed by STARTUP_CHILD (last one wins)."""
    import json

    records = [
        line[len("STARTUP_JSON ") :]
        for line in text.splitlines()
        if line.startswith("STARTUP_JSON ")
    ]
    if not records:
        raise ValueError("no STARTUP_JSON line in child output")
    record = json.loads(records[-1])
    for key in ("seconds", "modules", "rss_kb", "rss_source", "heavy"):
        if key not in record:
            raise ValueError(f"STARTUP_JSON record lacks {key!r}")
    return record


def summarize_startup(runs: list[dict]) -> dict:
    import statistics

    if not runs:
        raise ValueError("no runs to summarize")
    return {
        "runs": len(runs),
        "seconds_median": statistics.median(r["seconds"] for r in runs),
        "seconds_min": min(r["seconds"] for r in runs),
        "seconds_max": max(r["seconds"] for r in runs),
        "modules_median": int(statistics.median(r["modules"] for r in runs)),
        "modules_min": min(r["modules"] for r in runs),
        "modules_max": max(r["modules"] for r in runs),
        "rss_mb_median": round(statistics.median(r["rss_kb"] for r in runs) / 1024, 1),
        "rss_source": runs[0]["rss_source"],
        "heavy_loaded": sorted({m for r in runs for m in r["heavy"]}),
    }


def startup_markdown(summary: dict, environment: str, warmup: int) -> str:
    heavy = ", ".join(summary["heavy_loaded"]) or "none"
    return "\n".join(
        [
            "| metric | value |",
            "|---|---|",
            f"| runs (after {warmup} warm-up) | {summary['runs']} |",
            f"| startup time, median (min-max) | {summary['seconds_median']:.3f} s "
            f"({summary['seconds_min']:.3f}-{summary['seconds_max']:.3f}) |",
            f"| imported modules (len(sys.modules)), median (min-max) | {summary['modules_median']} "
            f"({summary['modules_min']}-{summary['modules_max']}) |",
            f"| peak RSS, median | {summary['rss_mb_median']} MiB ({summary['rss_source']}) |",
            f"| optional/heavy modules loaded | {heavy} |",
            "",
            f"Environment: {environment}. Measured: fresh interpreter per run, in-process "
            "`artemis --help` (import + help), output discarded.",
            "",
        ]
    )


def cmd_startup(args: argparse.Namespace) -> int:
    import json
    import platform

    child = f"HEAVY = {HEAVY_MODULES!r}\n" + STARTUP_CHILD
    runs: list[dict] = []
    neutral_cwd = tempfile.mkdtemp(prefix="artemis-startup-")  # no stray ./artemis on sys.path
    for index in range(args.warmup + args.runs):
        proc = subprocess.run(
            [args.python, "-c", child],
            cwd=neutral_cwd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
        if proc.returncode != 0:
            print(proc.stderr[-2000:], file=sys.stderr)
            return 1
        if index >= args.warmup:
            runs.append(parse_startup_output(proc.stdout))
    summary = summarize_startup(runs)
    version = subprocess.run(
        [args.python, "-c", "import sys; print(sys.version.split()[0])"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    environment = args.environment or f"{platform.system()} {platform.machine()}, Python {version}"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "startup-metrics.json").write_text(
        json.dumps(
            {"environment": environment, "warmup": args.warmup, "summary": summary, "runs": runs},
            indent=1,
        ),
        encoding="utf-8",
    )
    markdown = startup_markdown(summary, environment, args.warmup)
    (args.out / "startup-metrics.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-each")
    build.add_argument("--constraints", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument(
        "--python", default=sys.executable, help="interpreter whose pip builds the wheels"
    )
    build.add_argument("--interval", type=float, default=2.0)
    build.add_argument("packages", nargs="+")
    build.set_defaults(func=cmd_build_each)

    sample = sub.add_parser("sample")
    sample.add_argument("--out", type=Path, required=True)
    sample.add_argument("--stop-file", type=Path, required=True)
    sample.add_argument("--interval", type=float, default=5.0)
    sample.add_argument("--max-samples", type=int, default=0)
    sample.add_argument("paths", nargs="+")
    sample.set_defaults(func=cmd_sample)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("samples", type=Path)
    summarize.add_argument("--out", type=Path)
    summarize.add_argument("--interval", type=float, help="sampling interval used, for the note")
    summarize.set_defaults(func=cmd_summarize)

    verify = sub.add_parser("verify")
    verify.add_argument("--constraints", type=Path, required=True)
    verify.add_argument("--exclude", action="append", default=[])
    verify.add_argument("--require-all-pinned", action="store_true",
                        help="also fail on venv dists missing from the constraints")  # fmt: skip
    verify.add_argument("--allow-unpinned", action="append", default=[],
                        help="venv dist allowed without a pin (e.g. pip, the project itself)")  # fmt: skip
    verify.set_defaults(func=cmd_verify)

    startup = sub.add_parser("startup", help="module count, time and RSS of `artemis --help`")
    startup.add_argument("--out", type=Path, required=True)
    startup.add_argument(
        "--python", default=sys.executable, help="interpreter with artemis installed"
    )
    startup.add_argument("--runs", type=int, default=5)
    startup.add_argument("--warmup", type=int, default=1)
    startup.add_argument("--timeout", type=float, default=300.0)
    startup.add_argument("--environment", help="label, e.g. 'Termux-in-Docker aarch64 (CI)'")
    startup.set_defaults(func=cmd_startup)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

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


def write_build_reports(results: list[BuildResult], out_dir: Path) -> str:
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
    sys.stdout.write(write_build_reports(results, out_dir))
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


def cmd_verify(args: argparse.Namespace) -> int:
    pins = read_pins(args.constraints)
    for excluded in args.exclude:
        pins.pop(canonical(excluded), None)
    problems = verify_pins(pins, installed_versions())
    if problems:
        print(f"{len(problems)} pinned package(s) not installed at the exact version:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"All {len(pins)} pinned packages installed at their exact versions.")
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
    summarize.set_defaults(func=cmd_summarize)

    verify = sub.add_parser("verify")
    verify.add_argument("--constraints", type=Path, required=True)
    verify.add_argument("--exclude", action="append", default=[])
    verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

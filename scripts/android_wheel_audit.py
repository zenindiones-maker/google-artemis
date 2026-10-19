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

"""Audit native dependencies in uv.lock for Android ARM64 / Termux.

For every locked package that ships platform-specific wheels (i.e. has no
``py3-none-any`` wheel) or only an sdist, report:

* whether the *locked version* publishes an Android ARM64 wheel for CPython
  3.13 / 3.14 (PEP 738 tags ``android_<api>_arm64_v8a``; read from uv.lock);
* whether a Termux package provides it (from a list of termux-packages /
  TUR ``build.sh`` and ``*.subpackage.sh`` paths passed with ``--termux-index``).

The result is evidence for triage only: a Termux package or Android wheel is
not proof that ARTEMIS works on a device.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

PYTHON_TAGS = ("cp313", "cp314")
ANDROID_WHEEL = re.compile(
    r"-(?P<py>cp3\d+|py3)-(?P<abi>[^-]+)-(?P<plat>android_\d+_arm64_v8a)\.whl$"
)
# Packages that are only installed on other operating systems.
NOT_APPLICABLE = {"pywin32": "Windows-only"}
# sdists that build without a compiler (optional C speedups) on any platform.
PURE_FALLBACK = {"markupsafe", "pyyaml", "tornado", "google-crc32c"}
# Wheels that only bundle desktop executables; Termux provides native ones.
BUNDLED_BINARIES = {
    "adbutils": "android-tools (adb)",
    "imageio-ffmpeg": "ffmpeg (set IMAGEIO_FFMPEG_EXE)",
}
# Termux package names that do not follow the python-<name> convention.
TERMUX_ALIASES = {
    "opencv-python": ("python-opencv-python", "opencv"),
    "matplotlib": ("matplotlib", "python-matplotlib"),
    "pyarrow": ("python-pyarrow",),
    "google-crc32c": ("python-google-crc32c",),
}


@dataclass
class NativePackage:
    name: str
    version: str
    kind: str  # "platform-wheels" or "sdist-only"
    android_wheels: dict[str, bool] = field(default_factory=dict)
    termux_packages: list[str] = field(default_factory=list)
    status: str = ""


def native_packages(lock: dict) -> list[NativePackage]:
    result = []
    for pkg in lock.get("package", []):
        wheels = [w["url"].rsplit("/", 1)[-1] for w in pkg.get("wheels", [])]
        source = pkg.get("source", {})
        if "registry" not in source:
            continue  # workspace / editable members
        if wheels and any(w.endswith("-none-any.whl") for w in wheels):
            continue
        kind = "platform-wheels" if wheels else "sdist-only"
        android = {tag: False for tag in PYTHON_TAGS}
        for wheel in wheels:
            match = ANDROID_WHEEL.search(wheel)
            if not match:
                continue
            py, abi = match.group("py"), match.group("abi")
            for tag in PYTHON_TAGS:
                if py == tag or (abi == "abi3" and int(py[3:]) <= int(tag[3:])):
                    android[tag] = True
        result.append(NativePackage(pkg["name"], pkg["version"], kind, android))
    return sorted(result, key=lambda p: p.name)


def termux_names(index_lines: list[str]) -> set[str]:
    names = set()
    for line in index_lines:
        path = line.strip()
        if path.endswith("/build.sh"):
            names.add(path.rsplit("/", 2)[-2])
        elif path.endswith(".subpackage.sh"):
            names.add(path.rsplit("/", 1)[-1].removesuffix(".subpackage.sh"))
    return names


def classify(packages: list[NativePackage], termux: set[str] | None) -> None:
    for pkg in packages:
        if pkg.name in NOT_APPLICABLE:
            pkg.status = f"not-applicable ({NOT_APPLICABLE[pkg.name]})"
            continue
        if termux is not None:
            candidates = TERMUX_ALIASES.get(pkg.name, (f"python-{pkg.name}",))
            pkg.termux_packages = [c for c in candidates if c in termux]
        has_wheel = all(pkg.android_wheels.values())
        if has_wheel and pkg.termux_packages:
            pkg.status = "android-wheel+termux-package"
        elif has_wheel:
            pkg.status = "android-wheel"
        elif pkg.termux_packages:
            pkg.status = "termux-package"
        elif pkg.name in BUNDLED_BINARIES:
            pkg.status = f"bundled-binary: use Termux {BUNDLED_BINARIES[pkg.name]}"
        elif pkg.name in PURE_FALLBACK:
            pkg.status = "pure-python fallback from sdist (unverified on device)"
        elif termux is None:
            pkg.status = "no-android-wheel (termux index not provided)"
        else:
            pkg.status = "unresolved: needs source build on device"


def render_markdown(packages: list[NativePackage]) -> str:
    lines = [
        "| package | locked | kind | android cp313 | android cp314 | termux | status |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in packages:
        lines.append(
            f"| {p.name} | {p.version} | {p.kind} | "
            f"{'yes' if p.android_wheels.get('cp313') else 'no'} | "
            f"{'yes' if p.android_wheels.get('cp314') else 'no'} | "
            f"{', '.join(p.termux_packages) or '-'} | {p.status} |"
        )
    unresolved = [p.name for p in packages if p.status.startswith("unresolved")]
    lines.append("")
    lines.append(f"Native packages: {len(packages)}; unresolved: {len(unresolved)}")
    if unresolved:
        lines.append("Unresolved: " + ", ".join(unresolved))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--termux-index", type=Path, action="append", default=[])
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)

    lock = tomllib.loads(args.lock.read_text(encoding="utf-8"))
    packages = native_packages(lock)
    termux = None
    if args.termux_index:
        lines: list[str] = []
        for index in args.termux_index:
            lines += index.read_text(encoding="utf-8").splitlines()
        termux = termux_names(lines)
    classify(packages, termux)

    markdown = render_markdown(packages)
    sys.stdout.write(markdown)
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps([asdict(p) for p in packages], indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
"""Verify artifacts (e.g. wheels, UI bundles) against a SHA256SUMS manifest.

Integrity only: a matching hash proves the bytes are the ones listed in the manifest,
not who produced them. Authenticity needs ``gh attestation verify`` on top.

Exit codes: 0 all OK, 1 mismatch/missing/unlisted artifact, 2 malformed manifest.

``--wheelhouse DIR`` additionally cross-checks a Termux wheelhouse built by CI:
SHA256SUMS covers every file (including manifest.json); manifest.json lists exactly
the wheels in SHA256SUMS with the same hashes; every wheel is Android arm64 or pure
Python (never generic linux_aarch64); versions match the constraints pins; and every
package from the source-built list is present. Optional ``--expect-sums-sha256``
pins SHA256SUMS itself to the value printed by the CI run that produced it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

_LINE = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")


def read_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            raise ValueError(f"{path}:{number}: malformed line: {raw!r}")
        entries[Path(match.group(2)).name] = match.group(1)
    return entries


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_WHEEL = re.compile(
    r"^(?P<name>[^-]+)-(?P<version>[^-]+)(?:-\d[^-]*)?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$"
)
_ANDROID_ARM64 = re.compile(r"^android_\d+_arm64_v8a$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_wheel(filename: str) -> dict[str, str]:
    match = _WHEEL.match(filename)
    if not match:
        raise ValueError(f"not a wheel filename: {filename}")
    return {**match.groupdict(), "canonical": canonical(match.group("name"))}


def wheel_platform_ok(plat: str) -> bool:
    return plat == "any" or all(_ANDROID_ARM64.match(p) for p in plat.split("."))


def read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            pins[canonical(name.split("[")[0].strip())] = version.strip()
    return pins


def read_names(path: Path) -> list[str]:
    return [
        canonical(x.strip())
        for x in path.read_text(encoding="utf-8").splitlines()
        if x.strip() and not x.startswith("#")
    ]


def check_wheelhouse(
    directory: Path,
    constraints: Path | None = None,
    source_built: Path | None = None,
    expect_sums_sha256: str | None = None,
) -> list[str]:
    """Return a list of problems (empty = OK)."""
    import json

    problems: list[str] = []
    sums_path = directory / "SHA256SUMS"
    if not sums_path.is_file():
        return [f"MISSING {sums_path}"]
    if expect_sums_sha256 and sha256(sums_path) != expect_sums_sha256.lower():
        return [
            f"MISMATCH SHA256SUMS: expected {expect_sums_sha256}, got {sha256(sums_path)} (not the CI run you pinned)"
        ]
    try:
        sums = read_manifest(sums_path)
    except ValueError as exc:
        return [f"ERROR {exc}"]
    on_disk = {p.name for p in directory.iterdir() if p.is_file() and p.name != "SHA256SUMS"}
    problems += [f"UNLISTED {n}" for n in sorted(on_disk - set(sums))]
    problems += [f"MISSING {n}" for n in sorted(set(sums) - on_disk)]
    for name in sorted(set(sums) & on_disk):
        if sha256(directory / name) != sums[name]:
            problems.append(f"MISMATCH {name}")
    if "manifest.json" not in sums:
        problems.append("MISSING manifest.json in SHA256SUMS")
        return problems
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return problems + [f"ERROR manifest.json: {exc}"]
    listed = {w["file"]: w for w in manifest.get("wheels", [])}
    wheels = {n for n in sums if n.endswith(".whl")}
    if set(listed) != wheels:
        problems.append(f"INCONSISTENT manifest.json vs SHA256SUMS: {sorted(set(listed) ^ wheels)}")
    for file in sorted(set(listed) & wheels):
        if listed[file].get("sha256") != sums[file]:
            problems.append(f"INCONSISTENT hash for {file} in manifest.json")
    pins = read_pins(constraints) if constraints else {}
    present: set[str] = set()
    for file in sorted(wheels):
        try:
            info = parse_wheel(file)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        present.add(info["canonical"])
        if not wheel_platform_ok(info["plat"]):
            problems.append(
                f"WRONG PLATFORM {file}: {info['plat']} (need android_*_arm64_v8a or any)"
            )
        want = pins.get(info["canonical"])
        if want and want != info["version"]:
            problems.append(f"VERSION {file}: constraints pin {want}")
    if source_built:
        problems += [
            f"NOT COVERED {n} (would be compiled on the device)"
            for n in read_names(source_built)
            if n not in present
        ]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--wheelhouse", type=Path, help="cross-check a CI-built Termux wheelhouse")
    parser.add_argument("--constraints", type=Path)
    parser.add_argument("--source-built", type=Path)
    parser.add_argument("--expect-sums-sha256")
    args = parser.parse_args(argv)
    if args.wheelhouse:
        problems = check_wheelhouse(
            args.wheelhouse, args.constraints, args.source_built, args.expect_sums_sha256
        )
        for problem in problems:
            print(problem, file=sys.stderr)
        if not problems:
            print(f"OK wheelhouse {args.wheelhouse}")
        return 1 if problems else 0
    if not args.manifest or not args.artifacts:
        parser.error("--manifest and artifacts are required without --wheelhouse")
    try:
        expected = read_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    failed = False
    for artifact in args.artifacts:
        want = expected.get(artifact.name)
        if want is None:
            print(f"UNLISTED {artifact.name}", file=sys.stderr)
            failed = True
        elif not artifact.is_file():
            print(f"MISSING {artifact}", file=sys.stderr)
            failed = True
        elif (have := sha256(artifact)) != want:
            print(f"MISMATCH {artifact.name}: expected {want}, got {have}", file=sys.stderr)
            failed = True
        else:
            print(f"OK {artifact.name} {want}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

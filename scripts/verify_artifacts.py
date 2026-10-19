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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args(argv)
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

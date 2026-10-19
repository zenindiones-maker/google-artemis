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

"""Tests for scripts/android_wheel_audit.py (offline, synthetic lock data)."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "android_wheel_audit", ROOT / "scripts" / "android_wheel_audit.py"
)
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(audit)

FILES = "https://files.pythonhosted.org/packages/aa/bb"


def _pkg(name, version, wheels, sdist=True):
    pkg = {"name": name, "version": version, "source": {"registry": "https://pypi.org/simple"}}
    if wheels:
        pkg["wheels"] = [{"url": f"{FILES}/{w}"} for w in wheels]
    if sdist:
        pkg["sdist"] = {"url": f"{FILES}/{name}-{version}.tar.gz"}
    return pkg


LOCK = {
    "package": [
        _pkg("pure", "1.0", ["pure-1.0-py3-none-any.whl"]),
        _pkg(
            "withandroid",
            "2.0",
            [
                "withandroid-2.0-cp313-cp313-android_24_arm64_v8a.whl",
                "withandroid-2.0-cp314-cp314-android_24_arm64_v8a.whl",
                "withandroid-2.0-cp314-cp314-manylinux_2_28_aarch64.whl",
            ],
        ),
        _pkg("abi3pkg", "3.0", ["abi3pkg-3.0-cp313-abi3-android_21_arm64_v8a.whl"]),
        _pkg("linuxonly", "4.0", ["linuxonly-4.0-cp314-cp314-manylinux_2_28_aarch64.whl"]),
        _pkg("numpy", "2.5.2", ["numpy-2.5.2-cp314-cp314-manylinux_2_28_aarch64.whl"]),
        _pkg("opencv-python", "5.0.0.93", ["opencv_python-5.0.0.93-cp37-abi3-win_amd64.whl"]),
        _pkg("sdistonly", "0.1", []),
        _pkg("pywin32", "312", ["pywin32-312-cp314-cp314-win_amd64.whl"], sdist=False),
        {"name": "artemis", "version": "1.0", "source": {"editable": "."}},
    ]
}
TERMUX_INDEX = [
    "packages/python-numpy/build.sh",
    "x11-packages/python-opencv-python/build.sh",
    "packages/libarrow-cpp/python-pyarrow.subpackage.sh",
    "packages/python-withandroid/build.sh",
]


def _by_name(termux_index=TERMUX_INDEX):
    packages = audit.native_packages(LOCK)
    audit.classify(packages, audit.termux_names(termux_index) if termux_index else None)
    return {p.name: p for p in packages}


def test_pure_python_and_workspace_packages_are_ignored():
    names = set(_by_name())
    assert "pure" not in names
    assert "artemis" not in names


def test_android_wheels_detected_per_python_tag_including_abi3():
    pkgs = _by_name()
    assert pkgs["withandroid"].android_wheels == {"cp313": True, "cp314": True}
    assert pkgs["abi3pkg"].android_wheels == {"cp313": True, "cp314": True}
    # A manylinux aarch64 wheel is NOT an Android wheel.
    assert pkgs["linuxonly"].android_wheels == {"cp313": False, "cp314": False}


def test_termux_packages_and_aliases_are_matched():
    pkgs = _by_name()
    assert pkgs["numpy"].termux_packages == ["python-numpy"]
    assert pkgs["numpy"].status == "termux-package"
    assert pkgs["opencv-python"].termux_packages == ["python-opencv-python"]
    assert pkgs["withandroid"].status == "android-wheel+termux-package"
    assert "python-pyarrow" in audit.termux_names(TERMUX_INDEX)


def test_unresolved_and_not_applicable_statuses():
    pkgs = _by_name()
    assert pkgs["linuxonly"].status == "unresolved: needs source build on device"
    assert pkgs["sdistonly"].kind == "sdist-only"
    assert pkgs["sdistonly"].status.startswith("unresolved")
    assert pkgs["pywin32"].status.startswith("not-applicable")


def test_bundled_binaries_and_pure_fallbacks_are_labelled_not_compatible():
    lock = {
        "package": [
            _pkg("adbutils", "2.12.0", ["adbutils-2.12.0-py3-none-manylinux1_x86_64.whl"]),
            _pkg(
                "markupsafe", "3.0.3", ["markupsafe-3.0.3-cp314-cp314-manylinux_2_28_aarch64.whl"]
            ),
            _pkg(
                "uuid-utils", "0.17.0", ["uuid_utils-0.17.0-cp39-abi3-manylinux_2_28_aarch64.whl"]
            ),
        ]
    }
    packages = audit.native_packages(lock)
    # A Termux package that merely shares the bare name must not count.
    audit.classify(packages, {"uuid-utils"})
    by_name = {p.name: p for p in packages}
    assert by_name["adbutils"].status.startswith("bundled-binary")
    assert by_name["markupsafe"].status.startswith("pure-python fallback")
    assert by_name["uuid-utils"].status.startswith("unresolved")


def test_without_termux_index_nothing_is_claimed_compatible():
    pkgs = _by_name(termux_index=None)
    assert pkgs["numpy"].status == "no-android-wheel (termux index not provided)"
    assert pkgs["numpy"].termux_packages == []


def test_cli_writes_reports_for_the_real_lockfile(tmp_path):
    out_json = tmp_path / "audit.json"
    out_md = tmp_path / "audit.md"
    assert (
        audit.main(
            ["--lock", str(ROOT / "uv.lock"), "--json", str(out_json), "--markdown", str(out_md)]
        )
        == 0
    )
    data = json.loads(out_json.read_text())
    names = {p["name"] for p in data}
    assert {"numpy", "opencv-python", "pydantic-core"} <= names
    assert "Native packages:" in out_md.read_text()

#!/usr/bin/env bash
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
#
# Explicit, pinned ARTEMIS install path for Termux (Android, aarch64).
#
#   bash scripts/install_termux.sh [--dry-run]
#
# 1. installs the Termux packages in requirements/termux-pkg.txt (warns when the
#    installed version differs from the one validated in CI),
# 2. creates a virtualenv with --system-site-packages so Termux's numpy, scipy,
#    opencv, pyarrow, ... are reused instead of compiled,
# 3. pip-installs ARTEMIS with requirements/termux-constraints.txt (exact versions
#    that passed in the Termux-in-Docker probe); Rust/C packages without a Termux
#    package are compiled locally (pydantic-core, jiter, orjson, ...),
# 4. verifies 'artemis --help'.
#
# Validated only in a Termux aarch64 container (see docs/termux.md), not on a
# phone. Nothing is deleted; an existing virtualenv is reused.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
PKG_FILE="${REPO}/requirements/termux-pkg.txt"
CONSTRAINTS="${REPO}/requirements/termux-constraints.txt"
VENV="${ARTEMIS_VENV:-${HOME}/.artemis-venv}"
DRY_RUN=false

for arg in "$@"; do
    case "${arg}" in
        --dry-run) DRY_RUN=true ;;
        -h | --help)
            sed -n '16,30p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "Unknown option: ${arg}" >&2
            exit 2
            ;;
    esac
done

run() {
    echo "+ $*"
    if [ "${DRY_RUN}" != true ]; then
        "$@"
    fi
}

if [ -z "${TERMUX_VERSION:-}" ] && [[ "${PREFIX:-}" != *"/com.termux/files/usr" ]]; then
    echo "This installer is for Termux on Android only. On desktop use ./start.sh." >&2
    exit 1
fi

# --- 1. Termux packages ------------------------------------------------------
MAIN_PKGS=()
X11_PKGS=()
declare -A EXPECTED=()
while read -r name version repo _; do
    case "${name}" in "" | \#*) continue ;; esac
    if [ "${version:-}" = "x11" ]; then
        repo="x11"
        version=""
    fi
    EXPECTED["${name}"]="${version:-}"
    if [ "${repo:-}" = "x11" ]; then
        X11_PKGS+=("${name}")
    else
        MAIN_PKGS+=("${name}")
    fi
done < "${PKG_FILE}"

run pkg install -y "${MAIN_PKGS[@]}"
if [ ${#X11_PKGS[@]} -gt 0 ]; then
    run pkg install -y "${X11_PKGS[@]}"
fi

if [ "${DRY_RUN}" != true ]; then
    for name in "${!EXPECTED[@]}"; do
        want="${EXPECTED[${name}]}"
        [ -z "${want}" ] && continue
        have="$(dpkg-query -W -f='${Version}' "${name}" 2>/dev/null || true)"
        if [ "${have}" != "${want}" ]; then
            echo "⚠ ${name}: installed '${have:-none}', validated in CI '${want}'"
        fi
    done
fi

# --- 2. Build environment ---------------------------------------------------
# maturin (pydantic-core, jiter, orjson, ...) needs an explicit API level on Android.
if [ -z "${ANDROID_API_LEVEL:-}" ]; then
    if [ "${DRY_RUN}" = true ]; then
        ANDROID_API_LEVEL="<from python sys.getandroidapilevel()>"
    else
        ANDROID_API_LEVEL="$(python -c 'import sys; print(sys.getandroidapilevel())')"
    fi
fi
export ANDROID_API_LEVEL
echo "ANDROID_API_LEVEL=${ANDROID_API_LEVEL}"
# termux-exec lets './configure' scripts with '#!/bin/sh' run (e.g. uvloop's libuv).
if [ -z "${LD_PRELOAD:-}" ]; then
    for lib in "${PREFIX}/lib/libtermux-exec-ld-preload.so" "${PREFIX}/lib/libtermux-exec.so"; do
        if [ -f "${lib}" ]; then
            export LD_PRELOAD="${lib}"
            break
        fi
    done
fi
echo "LD_PRELOAD=${LD_PRELOAD:-<none>}"

# --- 3. Virtualenv + ARTEMIS ---------------------------------------------------
# Contamination guard: variables from another Python environment must not leak into
# the venv creation or pip install.
for var in PYTHONPATH PYTHONHOME VIRTUAL_ENV PIP_TARGET PIP_PREFIX PIP_USER; do
    if [ -n "${!var:-}" ]; then
        echo "⚠ Ignoring ${var}=${!var} (set by another Python environment)"
        unset "${var}"
    fi
done

py_minor() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true; }

if [ ! -x "${VENV}/bin/python" ]; then
    run python -m venv --system-site-packages "${VENV}"
else
    if [ "${DRY_RUN}" != true ]; then
        venv_minor="$(py_minor "${VENV}/bin/python")"
        system_minor="$(py_minor python)"
        if [[ "${venv_minor}" =~ ^[0-9]+\.[0-9]+$ && "${system_minor}" =~ ^[0-9]+\.[0-9]+$ && "${venv_minor}" != "${system_minor}" ]]; then
            echo "✖ ${VENV} was created with Python ${venv_minor}, but Termux now has Python ${system_minor}." >&2
            echo "  It was left untouched. Move it aside (mv ${VENV} ${VENV}.old) and re-run this installer." >&2
            exit 1
        fi
    fi
    echo "Reusing existing virtualenv ${VENV}"
fi
run "${VENV}/bin/python" -m pip install --prefer-binary -c "${CONSTRAINTS}" "${REPO}/packages/artemis-client"
run "${VENV}/bin/python" -m pip install --prefer-binary -c "${CONSTRAINTS}" "${REPO}"

# --- 4. Verify -----------------------------------------------------------------
run "${VENV}/bin/artemis" --help
echo "✔ ARTEMIS installed in ${VENV}. Start it with: ./start.sh"

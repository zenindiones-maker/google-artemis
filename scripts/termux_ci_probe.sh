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
# Probe ARTEMIS installation inside a real Termux userland (termux-docker,
# aarch64, bionic libc). Intended for CI only. It records every step and its
# exit code; it is NOT evidence that ARTEMIS works on a phone (no Android
# framework, no adb device, no screen).
#
# Usage: termux_ci_probe.sh <repo-dir> <output-dir>
set -u

REPO="${1:?repo dir}"
OUT="${2:?output dir}"
mkdir -p "${OUT}/logs"
REPORT="${OUT}/termux-probe.md"
WORK="${HOME}/artemis"
export DEBIAN_FRONTEND=noninteractive
APT=(apt-get -y -q -o Dpkg::Options::=--force-confnew)

{
    echo "# Termux-in-Docker probe (aarch64)"
    echo
    echo "Not a device test: no Android framework, no adb device, no display."
    echo
    echo "| step | exit code |"
    echo "|---|---|"
} > "${REPORT}"

CRITICAL_FAILED=0

step() {
    local critical="$1" name="$2"
    shift 2
    local slug
    slug="$(printf '%s' "${name}" | tr -c 'a-zA-Z0-9' '_')"
    echo "::group::${name}"
    "$@" > "${OUT}/logs/${slug}.log" 2>&1
    local rc=$?
    tail -n 60 "${OUT}/logs/${slug}.log"
    echo "::endgroup::"
    echo "| ${name} | ${rc} |" >> "${REPORT}"
    if [ "${rc}" -ne 0 ] && [ "${critical}" = critical ]; then
        CRITICAL_FAILED=1
    fi
    return 0
}

platform_info() {
    uname -a
    echo "PREFIX=${PREFIX:-} TERMUX_VERSION=${TERMUX_VERSION:-}"
    python -VV
    python - <<'PY'
import sys, sysconfig, platform
print("sys.platform =", sys.platform)
print("sysconfig.get_platform() =", sysconfig.get_platform())
print("platform.machine() =", platform.machine())
print("android api =", getattr(sys, "getandroidapilevel", lambda: "n/a")())
PY
    python -m pip debug --verbose 2>/dev/null | sed -n '/Compatible tags/,+12p'
}

native_imports() {
    local rc=0
    for mod in numpy scipy PIL cv2 matplotlib lxml cryptography psutil grpc pyarrow \
        pydantic_core jiter orjson aiohttp zmq yaml uiautomator2 adbutils google.genai \
        langgraph langchain_google_genai fastapi uvicorn; do
        if out="$(python -c "import ${mod}; print(getattr(${mod}, '__version__', 'ok'))" 2>&1)"; then
            echo "IMPORT_OK ${mod} ${out}"
        else
            echo "IMPORT_FAIL ${mod}: $(echo "${out}" | tail -n 1)"
            rc=1
        fi
    done
    return "${rc}"
}

step critical "apt update" "${APT[@]}" update

# Copy the checkout (read-only mount) without VCS/virtualenv/node_modules.
mkdir -p "${WORK}"
tar -C "${REPO}" --exclude=.git --exclude=.venv --exclude=node_modules -cf - . | tar -C "${WORK}" -xf -

# Run everything else from a neutral directory: from ${HOME}, the copied
# ./artemis checkout would shadow the installed package as a namespace package.
cd "$(mktemp -d)" || exit 1

# Exercise exactly the documented install path (pinned pkg list + constraints).
# It handles ANDROID_API_LEVEL for maturin, termux-exec for './configure'
# scripts and dbus for python-opencv-python (all observed blockers).
export ARTEMIS_VENV="${HOME}/venv"
# Timestamped pip log (pip reads PIP_LOG as --log) to measure per-package build times.
export PIP_LOG="${OUT}/logs/pip-timestamped.log"
step critical "scripts/install_termux.sh" bash "${WORK}/scripts/install_termux.sh"
# shellcheck disable=SC1091
. "${ARTEMIS_VENV}/bin/activate"
export IMAGEIO_FFMPEG_EXE="${PREFIX}/bin/ffmpeg"
step optional "platform info" platform_info
step optional "installed Termux package versions" bash -c \
    "grep -vE '^(#|\$)' '${WORK}/requirements/termux-pkg.txt' | awk '{print \$1}' | xargs dpkg-query -W -f='\${Package} \${Version} \${Installed-Size}\n'"
step optional "pip check" python -m pip check
step optional "native and core imports" native_imports
step critical "import artemis CLI module" python -c "import artemis.interfaces.cli.main"
step critical "artemis --version" artemis --version
step critical "artemis --help" artemis --help
step optional "host tools" bash -c 'adb version | head -n 1; ffmpeg -version | head -n 1; node -v; uv --version'
step optional "pip freeze" python -m pip freeze
step optional "disk usage" bash -c 'du -sh "${ARTEMIS_VENV}" "${HOME}/.cache/pip" "${PREFIX}" "${HOME}/.cargo" 2>/dev/null; df -h "${HOME}" 2>/dev/null' 

{
    echo
    echo "## Import results"
    grep -h -E '^IMPORT_(OK|FAIL)' "${OUT}"/logs/*.log 2>/dev/null | sed 's/^/- /' || true
    echo
    echo "## Platform"
    echo '```'
    cat "${OUT}/logs/platform_info.log" 2>/dev/null || true
    echo '```'
} >> "${REPORT}"

cat "${REPORT}"
exit "${CRITICAL_FAILED}"

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
step critical "install base packages" "${APT[@]}" install python python-pip uv android-tools ffmpeg nodejs-lts git
step optional "platform info" platform_info
step optional "install rust and build toolchain" "${APT[@]}" install rust build-essential binutils pkg-config
step optional "install Termux python-* packages" "${APT[@]}" install python-numpy python-scipy \
    python-pillow python-cryptography python-lxml python-psutil python-grpcio python-pyarrow \
    matplotlib python-greenlet python-rpds-py python-contourpy python-kiwisolver
step optional "enable x11-repo" "${APT[@]}" install x11-repo
step optional "apt update (x11)" "${APT[@]}" update
# python-opencv-python links libdbus-1.so but does not depend on the dbus package
# (observed: "dlopen failed: library libdbus-1.so not found").
step optional "install python-opencv-python (+dbus)" "${APT[@]}" install python-opencv-python dbus

# Copy the checkout (read-only mount) without VCS/virtualenv/node_modules.
mkdir -p "${WORK}"
tar -C "${REPO}" --exclude=.git --exclude=.venv --exclude=node_modules -cf - . | tar -C "${WORK}" -xf -

# Run everything else from a neutral directory: from ${HOME}, the copied
# ./artemis checkout would shadow the installed package as a namespace package.
cd "$(mktemp -d)" || exit 1

step critical "create venv with system site-packages" python -m venv --system-site-packages "${HOME}/venv"
# shellcheck disable=SC1091
. "${HOME}/venv/bin/activate"
export IMAGEIO_FFMPEG_EXE="${PREFIX}/bin/ffmpeg"
# maturin (Rust extensions such as uuid-utils, pydantic-core, jiter) refuses to
# build for Android without an explicit API level ("Failed to determine Android
# API level"). Use the level the Termux Python was built for.
ANDROID_API_LEVEL="$(python -c 'import sys; print(sys.getandroidapilevel())')"
export ANDROID_API_LEVEL
# sdists that need numpy at build time (bottleneck, numexpr: pulled in by
# langchain-google-vertexai) otherwise download and compile numpy from source in
# an isolated build env, which fails on bionic (observed: undeclared cpowf/cexpl
# in npy_math_complex.c). Build them against the Termux python-numpy instead.
step optional "build tools for no-isolation builds" python -m pip install setuptools wheel "versioneer[toml]" meson-python ninja
step optional "numpy-dependent sdists without build isolation" \
    python -m pip install --no-build-isolation bottleneck numexpr
step critical "pip install ARTEMIS (non-locked, Termux system packages reused)" \
    python -m pip install --prefer-binary "${WORK}"

# DIAGNOSTIC ONLY (the full install above stays critical): langchain-google-vertexai
# requires pyarrow<24 while Termux ships python-pyarrow 26 (built against its
# libarrow-cpp), and building pyarrow 23 needs Arrow C++ 23. Install everything
# else so later blockers are visible. The Vertex AI provider is imported lazily
# (artemis/llm/router.py), so this measures what else would block startup.
diagnostic_install_without_vertexai() {
    python - "${WORK}/pyproject.toml" > "${HOME}/reqs-no-vertexai.txt" <<'PY'
import sys, tomllib
deps = tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]
for dep in deps:
    if dep.startswith(("langchain-google-vertexai", "artemis-client")):
        continue
    print(dep)
PY
    cat "${HOME}/reqs-no-vertexai.txt"
    python -m pip install --prefer-binary -r "${HOME}/reqs-no-vertexai.txt" \
        && python -m pip install --no-deps "${WORK}/packages/artemis-client" \
        && python -m pip install --no-deps "${WORK}"
}
if ! python -c "import artemis.interfaces.cli.main" >/dev/null 2>&1; then
    step optional "DIAGNOSTIC install without langchain-google-vertexai" diagnostic_install_without_vertexai
fi
step optional "pip check" python -m pip check
step optional "native and core imports" native_imports
step critical "import artemis CLI module" python -c "import artemis.interfaces.cli.main"
step critical "artemis --version" artemis --version
step critical "artemis --help" artemis --help
step optional "host tools" bash -c 'adb version | head -n 1; ffmpeg -version | head -n 1; node -v; uv --version'
step optional "pip freeze" python -m pip freeze

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

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
# On-device validation of ARTEMIS on the physical phone (Galaxy A15), in Termux.
# Paste-able: bash <<'EOF' ... EOF, or: bash scripts/a15_validate.sh
#
# Writes ONLY under ~/artemis-validation/<timestamp>/ (override the root with
# ARTEMIS_VALIDATION_ROOT). Makes no network calls itself; every device action goes
# through 'artemis device ...' (Artemis ADB driver, no LLM). The single input event
# (KEYCODE_HOME) is sent only after you type SIM on the terminal; default = skipped.
# Nothing is uploaded anywhere; the screenshot stays in the validation directory.
#
# Inputs (environment, all optional): ARTEMIS_VENV (default ~/.artemis-venv),
# ARTEMIS_REPO (default: this script's repo), ARTEMIS_SERIAL (default: the only
# attached device), STEP_TIMEOUT seconds (default 120), A15_TTY (default /dev/tty).
set -u

VENV="${ARTEMIS_VENV:-${HOME}/.artemis-venv}"
REPO="${ARTEMIS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd)}"
# Pasted as a heredoc there is no script path: fall back to the clone location.
[ -f "${REPO}/scripts/termux_probe_metrics.py" ] || REPO="${HOME}/google-artemis"
ROOT="${ARTEMIS_VALIDATION_ROOT:-${HOME}/artemis-validation}"
OUT="${ROOT}/$(date +%Y%m%d-%H%M%S)"
STEP_TIMEOUT="${STEP_TIMEOUT:-120}"
TTY="${A15_TTY:-/dev/tty}"
ARTEMIS="${VENV}/bin/artemis"
export VENV
mkdir -p "${OUT}/logs" || exit 1
SUMMARY="${OUT}/summary.tsv"
printf 'step\tmandatory\tresult\texit\n' > "${SUMMARY}"
MANDATORY_FAILED=0
N=0

# step <mandatory|optional> <name> <command...>: run with a timeout, log, record.
step() {
    local kind="$1" name="$2"
    shift 2
    N=$((N + 1))
    local log="${OUT}/logs/$(printf '%02d' "${N}")-$(printf '%s' "${name}" | tr -c 'a-zA-Z0-9' '_').log"
    if declare -F "$1" > /dev/null; then
        # Shell functions cannot be exec'd by timeout; run them in a child bash.
        timeout "${STEP_TIMEOUT}" bash -c "$(declare -f "$1"); $*" > "${log}" 2>&1
    else
        timeout "${STEP_TIMEOUT}" "$@" > "${log}" 2>&1
    fi
    local rc=$?
    local result=PASS
    [ "${rc}" -eq 124 ] && result=TIMEOUT
    [ "${rc}" -ne 0 ] && [ "${rc}" -ne 124 ] && result=FAIL
    record "${kind}" "${name}" "${result}" "${rc}"
    LAST_LOG="${log}"
    return "${rc}"
}

# expect_fail <name> <expected-exit> <command...>: the error must propagate.
expect_fail() {
    local name="$1" want="$2"
    shift 2
    N=$((N + 1))
    local log="${OUT}/logs/$(printf '%02d' "${N}")-$(printf '%s' "${name}" | tr -c 'a-zA-Z0-9' '_').log"
    timeout "${STEP_TIMEOUT}" "$@" > "${log}" 2>&1
    local rc=$?
    if [ "${rc}" -eq "${want}" ]; then record mandatory "${name}" PASS "${rc}"; else record mandatory "${name}" FAIL "${rc}"; fi
}

record() {
    printf '%s\t%s\t%s\t%s\n' "$2" "$1" "$3" "$4" >> "${SUMMARY}"
    if [ "$1" = mandatory ] && [ "$3" != PASS ] && [ "$3" != SKIP ]; then MANDATORY_FAILED=1; fi
}


device_and_termux_info() {
    echo "model: $(getprop ro.product.model 2>/dev/null)"
    echo "android: $(getprop ro.build.version.release 2>/dev/null) (sdk $(getprop ro.build.version.sdk 2>/dev/null))"
    echo "abi: $(getprop ro.product.cpu.abi 2>/dev/null)"
    echo "uname: $(uname -srm)"
    echo "termux: ${TERMUX_VERSION:-unknown}  prefix: ${PREFIX:-unset}"
    "${VENV}/bin/python" -c 'import sys, sysconfig; print("python", sys.version.split()[0], sysconfig.get_platform())'
}

if command -v getprop > /dev/null 2>&1 && [ -n "$(getprop ro.product.model 2>/dev/null)" ]; then
    ENV_LABEL="Android $(getprop ro.build.version.release 2>/dev/null), $(getprop ro.product.model 2>/dev/null), Termux ${TERMUX_VERSION:-?}"
else
    ENV_LABEL="non-Android host $(uname -m) (NOT the phone)"
fi
echo "Validation directory: ${OUT}"
step optional "device and Termux info" device_and_termux_info
step mandatory "artemis --version" "${ARTEMIS}" --version
step mandatory "artemis --help" "${ARTEMIS}" --help
step mandatory "startup metrics (artemis --help, 5 runs)" "${VENV}/bin/python" \
    "${REPO}/scripts/termux_probe_metrics.py" startup --python "${VENV}/bin/python" \
    --out "${OUT}" --runs 5 --warmup 1 --environment "${ENV_LABEL}"
step optional "artemis doctor --json (keys redacted)" bash -c '"$1" doctor --json | sed -E "s/[A-Za-z0-9_-]{6}\.\.\.[A-Za-z0-9_-]{4}/<redacted>/g"' _ "${ARTEMIS}"
step mandatory "adb available" adb version
step mandatory "adb devices -l" adb devices -l
DEVICES_LOG="${LAST_LOG}"

SERIAL="${ARTEMIS_SERIAL:-}"
if [ -z "${SERIAL}" ]; then
    SERIAL="$(awk 'NR > 1 && $2 == "device" {print $1}' "${DEVICES_LOG}" | head -n 1)"
fi

if [ -z "${SERIAL}" ]; then
    record mandatory "device attached" FAIL 1
    cat <<'PAIR'

No authorized device. Pair this phone with itself over Wireless debugging (Android 16):
  1. Settings > Developer options > Wireless debugging: turn it on.
  2. Tap "Pair device with pairing code"; note the IP:PORT and the 6-digit code.
  3. In Termux (split screen):  adb pair 127.0.0.1:<pairing-port> <code>
  4. Back on the Wireless debugging screen, note the IP:PORT shown at the top.
  5. In Termux:                 adb connect 127.0.0.1:<connect-port>
  6. Run this validation again.
PAIR
else
    record mandatory "device attached (${SERIAL})" PASS 0
    step mandatory "artemis device info" "${ARTEMIS}" device info --serial "${SERIAL}" --json
    INFO_LOG="${LAST_LOG}"
    step mandatory "adb getprop ro.product.model (cross-check)" adb -s "${SERIAL}" shell getprop ro.product.model
    RAW_MODEL="$(tr -d '\r' < "${LAST_LOG}" | head -n 1)"
    if grep -q "\"model\": \"${RAW_MODEL}\"" "${INFO_LOG}" 2>/dev/null && [ -n "${RAW_MODEL}" ]; then
        record mandatory "model matches (${RAW_MODEL})" PASS 0
    else
        record mandatory "model matches" FAIL 1
    fi
    step optional "adb shell wm size" adb -s "${SERIAL}" shell wm size
    step mandatory "artemis device screenshot" "${ARTEMIS}" device screenshot --serial "${SERIAL}" --out "${OUT}/screen.png"
    if [ -s "${OUT}/screen.png" ]; then
        echo "screenshot: $(wc -c < "${OUT}/screen.png") bytes, sha256 $(sha256sum "${OUT}/screen.png" | cut -d' ' -f1)" | tee "${OUT}/screenshot.txt"
    fi
    expect_fail "error propagates: device info on a nonexistent serial (exit 1)" 1 \
        "${ARTEMIS}" device info --serial does-not-exist-000
    expect_fail "error propagates: helper status on a nonexistent serial (exit 1)" 1 \
        "${ARTEMIS}" helper status --serial does-not-exist-000 --json

    echo
    echo "Optional input test: sends KEYCODE_HOME (goes to the home screen) to ${SERIAL}."
    printf 'Type SIM and press Enter to send it, anything else to skip: '
    ANSWER=""
    read -r ANSWER < "${TTY}" 2>/dev/null || ANSWER=""
    if [ "${ANSWER}" = "SIM" ]; then
        step mandatory "artemis device key home (confirmed)" "${ARTEMIS}" device key home --serial "${SERIAL}" --yes
        cat "${LAST_LOG}"
        if grep -q '"focus_changed": true' "${LAST_LOG}"; then
            record mandatory "focus changed after HOME" PASS 0
        else
            record optional "focus changed after HOME (unchanged: already on home?)" FAIL 0
        fi
    else
        record optional "input test (not confirmed)" SKIP 0
    fi
fi

echo
echo "== Summary (${OUT}) =="
column -t -s "$(printf '\t')" "${SUMMARY}" 2>/dev/null || cat "${SUMMARY}"
if [ "${MANDATORY_FAILED}" -ne 0 ]; then
    echo "RESULT: FAIL (a mandatory step failed; see ${OUT}/logs)"
    exit 1
fi
echo "RESULT: PASS"
exit 0

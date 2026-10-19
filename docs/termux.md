# ARTEMIS on Android with Termux (draft)

> **Status: validated in an ARM64 Termux container only. NOT tested on a phone
> (Samsung Galaxy A15 or any other device).** Do not read anything below as
> proof that ARTEMIS works on Android.

## Evidence levels

| Item | Validated in ARM64 Termux container | Tested on Galaxy A15 |
|---|---|---|
| Termux Python 3.14.8 reports `sys.platform == "android"`, tags `android_24_arm64_v8a` | yes, [run 39182423805](https://github.com/zenindiones-maker/google-artemis/actions/runs/39182423805) | no |
| `pkg install` of the packages in `requirements/termux-pkg.txt` | yes (same run) | no |
| Rust/C packages compiled from source (pydantic-core, jiter, orjson, ormsgpack, uuid-utils, tiktoken, tornado, httptools, watchfiles, zstandard, regex, pyyaml, uvloop) | yes (same run) | no |
| Imports: numpy, scipy, PIL, cv2, matplotlib, lxml, cryptography, psutil, grpc, pyarrow, pydantic_core, jiter, orjson, aiohttp, zmq, yaml, uiautomator2, adbutils, google.genai, langgraph, langchain_google_genai, fastapi, uvicorn | yes (same run) | no |
| `artemis --version`, `artemis --help` | yes (same run) | no |
| `scripts/install_termux.sh` end to end | not yet run in CI (proposal) | no |
| adb to the same phone (Wireless debugging), uiautomator2 helper, screen capture, Showcase UI, an agent run | no (container has no Android framework, no device) | no |

The container run installed everything except Vertex AI. That run used a
diagnostic install without `langchain-google-vertexai`. The proposed
`sys_platform != 'android'` marker makes the default install do the same.

## Limitations

* **Vertex AI provider is not installed on Android.** `langchain-google-vertexai`
  requires `pyarrow<24`, but Termux ships `python-pyarrow` 26 built against its own
  Arrow C++, and pyarrow 23 cannot be built without Arrow C++ 23. Selecting the
  `vertexai` provider raises an error with install instructions. Other providers
  (Gemini API, OpenAI, Anthropic, ...) are unaffected.
* `uv sync` / `uv.lock` are **not** used on Termux. The lock pins wheels that don't
  exist for Android (e.g. opencv-python 5.x; Termux provides 4.14.0).
* Installing compiles about 13 Rust/C packages on the device. That needs several GB
  of free storage and can take a long time. Check first with the read-only
  preflight script.

## Install (proposed, untested on a phone)

```sh
pkg upgrade
pkg install git
git clone https://github.com/zenindiones-maker/google-artemis
cd google-artemis
bash scripts/install_termux.sh --dry-run   # shows every command, changes nothing
bash scripts/install_termux.sh
```

The script installs the Termux packages from `requirements/termux-pkg.txt` and warns
if versions differ from the validated ones. It sets `ANDROID_API_LEVEL` for maturin
and preloads `termux-exec`. It creates `~/.artemis-venv` with
`--system-site-packages`, then installs ARTEMIS with
`requirements/termux-constraints.txt`. It never deletes anything, and an existing
venv is reused.

## Connect adb to the same phone

1. Developer options → Wireless debugging → on.
2. "Pair device with pairing code": `adb pair 127.0.0.1:<pairing-port>` and enter the code.
3. `adb connect 127.0.0.1:<debug-port>` (port from the Wireless debugging screen).
4. `adb devices` should list the phone.

Then run `./start.sh` (it uses `~/.artemis-venv` on Termux). Start with `artemis doctor`.

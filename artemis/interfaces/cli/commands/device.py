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

"""``artemis device``: LLM-free checks and control of an attached Android device.

Everything goes through Artemis's own ADB driver (``AndroidAdbDriver`` over
``adbutils``), the same path tasks use, so a passing ``artemis device`` run shows
that this host can reach and drive the device without any model call.

Exit codes: 0 ok, 1 device not attached/authorized, 2 ADB command failed,
3 refused (an input action without ``--yes``), 124 timeout.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
from typing import Annotated, Any

import typer

from artemis.interfaces.cli.commands.helper import SerialOption, _resolve_serial

device_app = typer.Typer(no_args_is_help=True)

TimeoutOption = Annotated[float, typer.Option("--timeout", help="Seconds per ADB call.")]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _driver(serial: str):
    from adbutils import AdbClient

    from artemis.drivers.android.adb_driver import AndroidAdbDriver
    from artemis.config import settings

    client = AdbClient(host=settings.ADB_HOST or "localhost", port=settings.ADB_PORT or 5037)
    return AndroidAdbDriver(device_id=serial, adb_client=client)


def _call(func, limit: float, *args: Any, **kwargs: Any) -> Any:
    async def runner() -> Any:
        return await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=limit)

    try:
        return asyncio.run(runner())
    except TimeoutError:
        typer.secho(f"ADB call timed out after {limit:g} s.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=124) from None
    except typer.Exit:
        raise
    except Exception as exc:  # adbutils raises AdbError and friends
        typer.secho(f"ADB call failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None


def _shell(device: Any, command: str, timeout: float) -> str:
    result = _call(device.shell2, timeout, command, timeout=timeout)
    if result.returncode != 0:
        typer.secho(
            f"'{command}' exited {result.returncode}: {result.output.strip()}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    return result.output.strip()


def _focus(device: Any, timeout: float) -> str:
    dump = _shell(device, "dumpsys window", timeout)
    match = re.search(r"mCurrentFocus=(.*)", dump)
    return match.group(1).strip() if match else ""


@device_app.command("info")
def device_info(
    serial: SerialOption = None,
    timeout: TimeoutOption = 15.0,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    """Read-only: model, Android version, screen size and focused window."""
    target = _resolve_serial(serial)
    device = _driver(target).device
    info = {
        "serial": target,
        "model": _shell(device, "getprop ro.product.model", timeout),
        "android_release": _shell(device, "getprop ro.build.version.release", timeout),
        "sdk": _shell(device, "getprop ro.build.version.sdk", timeout),
        "wm_size": _shell(device, "wm size", timeout),
        "focus": _focus(device, timeout),
    }
    if as_json:
        typer.echo(json.dumps(info, indent=2))
    else:
        for key, value in info.items():
            typer.echo(f"{key}: {value}")


@device_app.command("screenshot")
def device_screenshot(
    out: Annotated[
        Path, typer.Option("--out", "-o", help="PNG file to write (never overwritten).")
    ],
    serial: SerialOption = None,
    timeout: TimeoutOption = 30.0,
) -> None:
    """Read-only: capture the screen to a local PNG and print its size and sha256."""
    if out.exists():
        typer.secho(f"{out} already exists; refusing to overwrite.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)
    target = _resolve_serial(serial)
    device = _driver(target).device
    data = _call(device.shell, timeout, "screencap -p", encoding=None, timeout=timeout)
    if not isinstance(data, bytes) or not data.startswith(PNG_MAGIC):
        typer.secho("screencap did not return a PNG.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    typer.echo(
        json.dumps(
            {"path": str(out), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    )


@device_app.command("key")
def device_key(
    key: Annotated[str, typer.Argument(help="Key name (home, back, ...) or Android keycode.")],
    serial: SerialOption = None,
    timeout: TimeoutOption = 15.0,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm sending input to the device.")
    ] = False,
) -> None:
    """Send one key event and report the focused window before and after."""
    if not yes:
        typer.secho("Refusing to send input without --yes.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)
    target = _resolve_serial(serial)
    driver = _driver(target)
    before = _focus(driver.device, timeout)
    ok = _call(lambda: asyncio.run(driver.press_key(key)), timeout)
    if not ok:
        typer.secho(f"press_key({key!r}) failed.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    after = _focus(driver.device, timeout)
    typer.echo(json.dumps({"serial": target, "key": key, "focus_before": before, "focus_after": after,
                           "focus_changed": before != after}))  # fmt: skip

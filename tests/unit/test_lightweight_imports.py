"""Regression tests: the CLI must work without the heavy optional extras.

A meta-path finder blocks the optional modules in a fresh interpreter, which is how
the Termux ``core`` profile looks (no cv2/numpy/jupyter_client/zmq installed).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from artemis.utils.optional_deps import LazyModule, OptionalDependencyError, require

ROOT = Path(__file__).resolve().parents[2]
BLOCKED = (
    "cv2",
    "numpy",
    "jupyter_client",
    "zmq",
    "ipykernel",
    "imageio_ffmpeg",
    "scipy",
    "matplotlib",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_google_vertexai",
    "fastapi",
)
# Original 13171cb CLI import loaded 2106 modules on box Linux; lazy imports bring it
# to ~1.9k. The bound catches regressions that pull a heavy stack back in.
MAX_CLI_MODULES = 2000


def _run(
    code: str, tmp_path: Path, *, extra_path: str | None = None
) -> subprocess.CompletedProcess:
    prelude = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        BLOCKED = {BLOCKED!r}
        class _Blocker:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError("blocked optional module: " + name)
                return None
        sys.meta_path.insert(0, _Blocker())
        """
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GITHUB_", "FORCE_COLOR", "PY_COLORS"))
    }
    env.update(
        HOME=str(tmp_path),
        GOOGLE_API_KEY="ci-not-a-real-key",
        GEMINI_API_KEY="ci-not-a-real-key",
        PYTHONDONTWRITEBYTECODE="1",
        TERM="dumb",
        COLUMNS="200",
    )
    if extra_path:
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
        check=False,
    )


def test_cli_help_works_without_optional_extras(tmp_path: Path) -> None:
    proc = _run(
        """
        sys.argv = ["artemis", "--help"]
        from artemis.interfaces.cli.main import cli
        try:
            cli()
        except SystemExit as exc:
            code = exc.code or 0
        heavy = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
        print("HEAVY=" + ",".join(heavy))
        print("MODULES=" + str(len(sys.modules)))
        sys.exit(code)
        """,
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "Usage" in proc.stdout
    assert "HEAVY=\n" in proc.stdout
    modules = int(proc.stdout.rsplit("MODULES=", 1)[1].split()[0])
    assert modules < MAX_CLI_MODULES, modules
    # No import-time side-effect output (was: "Activated local ADB server endpoint").
    assert "Activated" not in proc.stdout + proc.stderr


@pytest.mark.parametrize("system_ffmpeg", [True, False], ids=["ffmpeg-on-path", "no-ffmpeg"])
def test_cli_import_does_not_load_heavy_modules_even_when_installed(
    tmp_path: Path, system_ffmpeg: bool
) -> None:
    # Deterministic PATH: the result no longer depends on whether the host has ffmpeg
    # (the 8c970fa CI failure came from GitHub runners lacking it).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if system_ffmpeg:
        stub = bin_dir / "ffmpeg"
        stub.write_text("#!/bin/sh\necho 'ffmpeg version 0-stub'\n", encoding="utf-8")
        stub.chmod(0o755)
    code = f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        import artemis.interfaces.cli.main  # noqa: F401
        print(",".join(sorted(m for m in {BLOCKED!r} if m in sys.modules)))
    """
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bin_dir),
            "HOME": str(tmp_path),
            "GOOGLE_API_KEY": "ci-not-a-real-key",
        },
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    loaded = set(filter(None, proc.stdout.strip().split(",")))
    if not system_ffmpeg:
        # Toolchain resolution at import (artemis/toolchain/__init__.py) may fall back
        # to the ffmpeg binary shipped by imageio_ffmpeg. Existing desktop behaviour.
        loaded.discard("imageio_ffmpeg")
    assert loaded == set()


def test_doctor_runs_with_stubbed_adb_without_extras(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    adb = fake / "adb"
    adb.write_text(
        "#!/bin/sh\n"
        'case "$*" in *devices*) printf "List of devices attached\\nemulator-5554\\tdevice\\n";;'
        ' *version*) echo "Android Debug Bridge version 1.0.41";; *) echo ok;; esac\n'
    )
    adb.chmod(0o755)
    proc = _run(
        """
        sys.argv = ["artemis", "doctor", "--json"]
        from artemis.interfaces.cli.main import cli
        cli()
        """,
        tmp_path,
        extra_path=str(fake),
    )
    assert proc.returncode in (0, 1), proc.stderr[-2000:]
    doc = json.loads(proc.stdout[proc.stdout.index("{") :])
    ids = {check["id"]: check["status"] for check in doc["checks"]}
    assert ids["python_runtime"] == "pass"
    assert "android_adb" in ids


def test_optional_feature_fails_with_actionable_error_and_others_still_import(
    tmp_path: Path,
) -> None:
    proc = _run(
        """
        import artemis.utils.video as video
        import artemis.utils.image_diff as image_diff
        import artemis.utils.cv_canvas as cv_canvas
        import artemis.utils.python_executor as python_executor
        import artemis.agents.explorer.perception_tools  # noqa: F401
        from artemis.utils.optional_deps import OptionalDependencyError
        try:
            video.cv2.VideoCapture
        except OptionalDependencyError as exc:
            print("EXTRA=" + exc.extra)
            print("MSG=" + str(exc))
        # An independent essential module keeps working after the failure.
        from artemis.core.diagnostics.adb_server_connection import adb_server_connection
        print("ADB=" + adb_server_connection.current_endpoint().host)
        """,
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "EXTRA=vision" in proc.stdout
    # Points to the concrete package (pip extras do not exist yet; E2 decides them).
    assert "pip install opencv-python" in proc.stdout
    assert "pkg install python-opencv-python" in proc.stdout
    assert "artemis[" not in proc.stdout and "--profile" not in proc.stdout
    assert "ADB=" in proc.stdout


def test_lazy_module_error_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    lazy = LazyModule("definitely_missing_mod_xyz", "Test feature", extra="vision")
    with pytest.raises(OptionalDependencyError) as info:
        lazy.anything
    assert info.value.module == "definitely_missing_mod_xyz"
    assert "Test feature" in str(info.value)
    monkeypatch.setitem(sys.modules, "definitely_missing_mod_xyz", type(sys)("x"))
    sys.modules["definitely_missing_mod_xyz"].anything = 42
    assert lazy.anything == 42


def test_require_maps_known_modules_to_extras() -> None:
    with pytest.raises(OptionalDependencyError) as info:
        require("langchain_openai_missing.sub", "OpenAI provider", extra="providers")
    assert info.value.extra == "providers"
    assert isinstance(info.value, ImportError)
    err = OptionalDependencyError("cv2", "Video")
    assert err.extra == "vision"
    assert OptionalDependencyError("unknown_mod", "X").extra == "full"


def test_import_time_adb_sync_is_quiet_but_explicit_activation_announces(caplog) -> None:
    from artemis.core.diagnostics import adb_server_connection as mod

    endpoint = mod.adb_server_connection.current_endpoint()
    caplog.set_level("DEBUG")
    calls: list[tuple[str, str]] = []

    class _Log:
        def info(self, msg: str) -> None:
            calls.append(("info", msg))

        def debug(self, msg: str) -> None:
            calls.append(("debug", msg))

    original = mod.logger
    mod.logger = _Log()
    try:
        mod.adb_server_connection.synchronize_environment(announce=False)
        mod.AdbServerConnectionManager._activate(endpoint)
    finally:
        mod.logger = original
    assert calls[0][0] == "debug" and "Activated" in calls[0][1]
    assert calls[1][0] == "info"
    source = Path(mod.__file__).read_text()
    assert "adb_server_connection.synchronize_environment(announce=False)" in source


def test_lazy_modules_are_still_default_desktop_dependencies() -> None:
    """Lazy loading must not change the desktop install: all stay default deps."""
    import tomllib

    from packaging.requirements import Requirement

    from artemis.utils.optional_deps import MODULE_PACKAGES

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    default = {Requirement(d).name.lower() for d in project["dependencies"]}
    for package_names, _termux in MODULE_PACKAGES.values():
        for name in package_names.split():
            if name == "pyzmq":  # transitive via jupyter-client/ipykernel
                continue
            assert name in default, name
    doc = (ROOT / "docs" / "termux-core-dependencies.md").read_text(encoding="utf-8")
    assert "does not change any install" in doc

"""E1 case 1: the CLI starts and its essential commands work when no Showcase UI
(neither ``apps/showcase_ui/dist`` nor the bundled ``artemis/resources/showcase_ui``)
is present. The UI is hidden by patching path checks; no file is deleted."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[2]

HIDE_UI = """
import pathlib, sys
sys.path.insert(0, {root!r})
_exists, _is_file, _is_dir = pathlib.Path.exists, pathlib.Path.is_file, pathlib.Path.is_dir
def _hidden(self):
    return "showcase_ui" in self.as_posix()
pathlib.Path.exists = lambda self, *a, **k: False if _hidden(self) else _exists(self, *a, **k)
pathlib.Path.is_file = lambda self, *a, **k: False if _hidden(self) else _is_file(self, *a, **k)
pathlib.Path.is_dir = lambda self, *a, **k: False if _hidden(self) else _is_dir(self, *a, **k)
class _NoServer:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("fastapi", "uvicorn", "starlette"):
            raise ImportError("UI/server stack hidden: " + name)
sys.meta_path.insert(0, _NoServer())
from artemis.resources import get_bundled_showcase_dist
assert get_bundled_showcase_dist() is None
"""


def _run(argv: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    code = HIDE_UI.format(root=str(ROOT)) + textwrap.dedent(
        f"""
        sys.argv = ["artemis", *{argv!r}]
        from artemis.interfaces.cli.main import cli
        cli()
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
        PYTHONDONTWRITEBYTECODE="1",
        TERM="dumb",
        COLUMNS="200",
        PATH=os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p),
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("argv", [["--help"], ["--version"], ["run", "--help"]])
def test_cli_starts_without_ui_bundle(tmp_path: Path, argv: list[str]) -> None:
    proc = _run(argv, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "npm" not in proc.stdout + proc.stderr


def test_doctor_reports_missing_ui_without_failing(tmp_path: Path) -> None:
    proc = _run(["doctor", "--json"], tmp_path)
    assert proc.returncode in (0, 1), proc.stderr[-2000:]
    doc = json.loads(proc.stdout[proc.stdout.index("{") :])
    showcase = doc["extras"]["showcase_ui"]
    assert showcase["status"] != "pass"
    assert {c["id"] for c in doc["checks"]} >= {"python_runtime", "android_adb"}

"""Case 5: the Termux path never runs npm/ng, even with a compatible Node.js.

Reproduced on 3e8927f: with Termux detected, a compatible ``node`` and no Showcase UI
dist, start.sh ran ``npm ci`` and ``npm run build`` (Angular build on the phone). The
Termux path now skips the build and points to a prebuilt bundle; desktop is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_start_script_behavior import _common_tools, _make_sandbox, _termux, pytestmark

__all__ = ["pytestmark"]


def _compatible_node(box, where: Path) -> None:
    box.stub("node", body='[ "$1" = "-v" ] && echo v22.23.2', where=where)
    box.stub("npm", body='[ "$1" = "-v" ] && echo 10.9.0', where=where)
    box.stub("ng", where=where)


def test_termux_with_compatible_node_and_no_dist_never_runs_npm_or_ng(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, showcase_built=False)
    prefix_bin = _termux(box, tmp_path)
    _common_tools(box, prefix_bin)
    _compatible_node(box, prefix_bin)
    (box.project / "apps" / "showcase_ui").mkdir(parents=True)

    result = box.run()

    assert result.returncode == 0, result.stderr
    assert [c for c in box.calls("npm") if c != "-v"] == []
    assert box.calls("ng") == []
    assert box.calls("curl") == []
    assert "prebuilt" in result.stdout


def test_desktop_with_compatible_node_and_no_dist_still_builds_ui(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, showcase_built=False)
    _common_tools(box, box.stubs)
    for tool in ("adb", "ffmpeg", "scrcpy"):
        box.stub(tool)
    _compatible_node(box, box.stubs)
    (box.project / "apps" / "showcase_ui").mkdir(parents=True)

    result = box.run()

    assert result.returncode == 0, result.stderr
    npm_calls = box.calls("npm")
    assert "ci --silent" in npm_calls
    assert "run build" in npm_calls

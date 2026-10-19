"""E1: plain CLI startup must not import the MCP/web server stack.

The third-party ``mcp`` package's ``__init__`` imports its server stack (uvicorn,
starlette, sse-starlette), so our own modules must not import ``mcp`` at module
level on the CLI path. The server stack is still loaded when a server starts.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_STACK = ("mcp", "uvicorn", "starlette", "sse_starlette", "fastapi")
HEAVY = ("cv2", "numpy", "jupyter_client", "zmq", "ipykernel", "scipy", "matplotlib")


def _python(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
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
    )
    prelude = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
    return subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    "argv",
    [["--help"], ["--version"], ["run", "--help"], ["mcp", "--help"], ["doctor", "--help"]],
)
def test_cli_commands_do_not_load_server_or_heavy_stack(tmp_path: Path, argv: list[str]) -> None:
    proc = _python(
        f"""
        sys.argv = ["artemis", *{argv!r}]
        from artemis.interfaces.cli.main import cli
        try:
            cli()
        except SystemExit as exc:
            code = exc.code or 0
        else:
            code = 0
        loaded = sorted(
            m for m in {SERVER_STACK + HEAVY!r} if m in sys.modules
        )
        print("LOADED=" + ",".join(loaded))
        sys.exit(code)
        """,
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "LOADED=\n" in proc.stdout, proc.stdout[-500:]


def test_mcp_server_package_still_exposes_server_with_tools(tmp_path: Path) -> None:
    proc = _python(
        """
        import mcp_server
        assert "uvicorn" not in sys.modules
        server = mcp_server.mcp
        assert callable(mcp_server.main)
        import mcp_server.tools  # registered by the lazy accessor
        print(type(server).__name__, "mcp_server.tools" in sys.modules)
        """,
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.split() == ["FastMCP", "True"]


def test_mcp_server_unknown_attribute_raises_attribute_error() -> None:
    import mcp_server

    with pytest.raises(AttributeError):
        mcp_server.not_a_real_attribute  # noqa: B018


def test_wire_handler_keeps_calltoolresult_return_annotation() -> None:
    import inspect
    import typing

    from mcp.types import CallToolResult

    from artemis.mcp.action_specs import ACTION_SPECS, make_wire_handler

    spec = next(s for s in ACTION_SPECS.values() if s.wire is not None)
    handler = make_wire_handler(spec, object(), lambda r: r, lambda n, e: e)
    annotation = inspect.signature(handler).return_annotation
    assert typing.get_origin(annotation) is typing.Annotated
    assert typing.get_args(annotation)[0] is CallToolResult

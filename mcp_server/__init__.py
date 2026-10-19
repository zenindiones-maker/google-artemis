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

"""Universal Model Context Protocol (MCP) Server for ARTEMIS."""

from importlib import import_module
from typing import Any

__all__ = ["mcp", "main"]


def __getattr__(name: str) -> Any:
    """Load the FastMCP server lazily.

    ``mcp`` (with its tools registered) and ``main`` pull in the ``mcp`` package's
    server stack (uvicorn/starlette). Light helpers such as ``mcp_server.utils``
    must stay importable without it, e.g. for ``artemis --help``.
    """
    if name == "mcp":
        import_module("mcp_server.tools")
        return import_module("mcp_server.base").mcp
    if name == "main":
        return import_module("mcp_server.server").main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

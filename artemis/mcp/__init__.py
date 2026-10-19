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

"""Internal MCP servers for ARTEMIS engine (ADB server, XML Fuzzy Search)."""

from importlib import import_module
from typing import Any

__all__ = ["adb_mcp", "xml_mcp"]

# The servers pull in FastMCP (uvicorn/starlette); load them only when used so that
# importing light helpers such as ``artemis.mcp.action_specs`` stays cheap.
_LAZY_SERVERS = {
    "adb_mcp": "artemis.mcp.adb_server",
    "xml_mcp": "artemis.mcp.xml_search_server",
}


def __getattr__(name: str) -> Any:
    module = _LAZY_SERVERS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return import_module(module).mcp

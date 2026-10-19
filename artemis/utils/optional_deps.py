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
"""Lazy loading of optional (heavy) dependencies with actionable errors.

Heavy modules such as ``cv2``, ``numpy`` or ``jupyter_client`` are only needed by
specific features. Importing them lazily keeps ``artemis --help`` and the essential
commands usable on lightweight installs (e.g. the Termux ``core`` profile), while a
feature that really needs them fails with an :class:`OptionalDependencyError` that
names the extra to install.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

# Module -> dependency group (documentation label, see docs/termux-core-dependencies.md).
# These are NOT pip extras yet: every module below is still a default dependency of
# the desktop install, so error messages point to the concrete package to install.
MODULE_EXTRAS: dict[str, str] = {
    "cv2": "vision",
    "numpy": "vision",
    "imageio_ffmpeg": "vision",
    "jupyter_client": "vision",
    "zmq": "vision",
    "langchain_openai": "providers",
    "langchain_anthropic": "providers",
    "langchain_google_vertexai": "vertex",
    "fastapi": "server",
}


# Module -> (pip package, Termux pkg or None when pip is the way on Termux too).
MODULE_PACKAGES: dict[str, tuple[str, str | None]] = {
    "cv2": ("opencv-python", "python-opencv-python"),
    "numpy": ("numpy", "python-numpy"),
    "imageio_ffmpeg": ("imageio-ffmpeg", "ffmpeg"),
    "jupyter_client": ("jupyter-client ipykernel", None),
    "zmq": ("pyzmq", None),
    "langchain_openai": ("langchain-openai", None),
    "langchain_anthropic": ("langchain-anthropic", None),
    "langchain_google_vertexai": ("langchain-google-vertexai", None),
    "fastapi": ("fastapi", None),
}


class OptionalDependencyError(ImportError):
    """Raised when a feature needs an optional dependency that is not installed."""

    def __init__(self, module: str, feature: str, extra: str | None = None) -> None:
        self.module = module
        self.feature = feature
        self.extra = extra or MODULE_EXTRAS.get(module.split(".")[0], "full")
        top = module.split(".")[0]
        package, termux_pkg = MODULE_PACKAGES.get(top, (top, None))
        hint = f"Install it with: pip install {package} (included in the default desktop install: uv sync)"
        if termux_pkg:
            hint += f"; on Termux: pkg install {termux_pkg}"
        super().__init__(
            f"{feature} requires the optional dependency '{module}', which is not installed. "
            f"{hint}."
        )


def require(module: str, feature: str, extra: str | None = None) -> ModuleType:
    """Import ``module`` or raise :class:`OptionalDependencyError`."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise OptionalDependencyError(module, feature, extra) from exc


class LazyModule:
    """Proxy that imports ``module`` on first attribute access.

    Failures are not cached, so installing the extra later in the same process works.
    """

    __slots__ = ("_lazy_module", "_lazy_feature", "_lazy_extra", "_lazy_loaded")

    def __init__(self, module: str, feature: str, extra: str | None = None) -> None:
        object.__setattr__(self, "_lazy_module", module)
        object.__setattr__(self, "_lazy_feature", feature)
        object.__setattr__(self, "_lazy_extra", extra)
        object.__setattr__(self, "_lazy_loaded", None)

    def _load(self) -> ModuleType:
        loaded = object.__getattribute__(self, "_lazy_loaded")
        if loaded is None:
            loaded = require(
                object.__getattribute__(self, "_lazy_module"),
                object.__getattribute__(self, "_lazy_feature"),
                object.__getattribute__(self, "_lazy_extra"),
            )
            object.__setattr__(self, "_lazy_loaded", loaded)
        return loaded

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __repr__(self) -> str:
        return f"<LazyModule {object.__getattribute__(self, '_lazy_module')!r}>"

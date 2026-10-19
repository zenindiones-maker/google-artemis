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

"""Repository-wide pytest fixtures and classification helpers.

The default test paths contain only deterministic tests.  Tests under the
integration and end-to-end trees remain directly runnable, and receive stable
markers here so callers can select them without relying on filename patterns.
"""

import os
from pathlib import Path

# Deterministic tests must not need a real credential. Several unit tests build a
# Gemini client (which validates that a key is present) without mocking the env; give
# them an obvious non-secret placeholder unless the caller already set one. This runs
# before any artemis import, so CI and local runs behave the same with no secrets.
PLACEHOLDER_API_KEY = "test-placeholder-not-a-real-key"
for _var in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
    os.environ.setdefault(_var, PLACEHOLDER_API_KEY)

import pytest  # noqa: E402

from artemis.drivers.mock.mock_driver import MockDeviceDriver  # noqa: E402


@pytest.fixture
def mock_driver():
    """Provide an isolated mock mobile driver."""
    return MockDeviceDriver(device_id="fixture-mock-device", width=1080, height=2400)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Attach test-layer markers according to the owning test directory."""
    for item in items:
        parts = Path(str(item.path)).parts
        if "integration" in parts:
            item.add_marker(pytest.mark.integration)
        if "e2e" in parts:
            item.add_marker(pytest.mark.e2e)

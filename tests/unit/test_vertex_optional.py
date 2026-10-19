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

"""Vertex AI provider stays available on desktop and is optional on Android."""

import enum
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

from artemis.llm.router import (
    VERTEX_AI_MISSING_MESSAGE,
    ModelEndpoint,
    ModelFactory,
    ModelProvider,
    VertexAIUnavailableError,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _real_factory(monkeypatch):
    monkeypatch.delenv("ARTEMIS_FAKE_LLM", raising=False)


def _vertex_endpoint() -> ModelEndpoint:
    return ModelEndpoint(provider="vertexai", model_name="gemini-2.5-flash", temperature=0.2)


def _fake_vertex_module(captured: dict) -> types.ModuleType:
    module = types.ModuleType("langchain_google_vertexai")

    class HarmCategory(enum.Enum):
        HARM_CATEGORY_HATE_SPEECH = 1
        HARM_CATEGORY_HARASSMENT = 2
        HARM_CATEGORY_SEXUALLY_EXPLICIT = 3
        HARM_CATEGORY_DANGEROUS_CONTENT = 4

    class HarmBlockThreshold(enum.Enum):
        BLOCK_NONE = 0

    class ChatVertexAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    module.ChatVertexAI = ChatVertexAI
    module.HarmCategory = HarmCategory
    module.HarmBlockThreshold = HarmBlockThreshold
    return module


def test_vertex_provider_builds_chat_model_when_extra_is_installed(monkeypatch):
    captured: dict = {}
    fake = _fake_vertex_module(captured)
    monkeypatch.setitem(sys.modules, "langchain_google_vertexai", fake)

    model = ModelFactory.create_model(_vertex_endpoint())

    assert isinstance(model, fake.ChatVertexAI)
    assert captured["model_name"] == "gemini-2.5-flash"
    assert captured["temperature"] == 0.2
    assert set(captured["safety_settings"].values()) == {fake.HarmBlockThreshold.BLOCK_NONE}


def test_vertex_provider_without_extra_raises_actionable_error(monkeypatch):
    # A None entry makes "import langchain_google_vertexai" raise ImportError.
    monkeypatch.setitem(sys.modules, "langchain_google_vertexai", None)

    with pytest.raises(VertexAIUnavailableError) as excinfo:
        ModelFactory.create_model(_vertex_endpoint())

    message = str(excinfo.value)
    assert message == VERTEX_AI_MISSING_MESSAGE
    assert "uv sync --extra vertex" in message
    assert "artemis[vertex]" in message
    assert isinstance(excinfo.value, ImportError)  # no silent fallback to another provider
    assert isinstance(excinfo.value.__cause__, ImportError)


def test_vertex_is_not_imported_unless_selected():
    code = (
        "import sys\n"
        "import artemis.llm.router\n"
        "import artemis.interfaces.cli.main\n"
        "assert 'langchain_google_vertexai' not in sys.modules, 'vertex imported eagerly'\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert proc.stdout.strip().endswith("ok")


def _vertex_requirements() -> tuple[list[Requirement], list[Requirement]]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    default = [Requirement(d) for d in project["dependencies"]]
    vertex_default = [r for r in default if r.name == "langchain-google-vertexai"]
    vertex_extra = [Requirement(d) for d in project["optional-dependencies"]["vertex"]]
    return vertex_default, vertex_extra


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_default_desktop_install_still_includes_vertex(platform):
    default, _ = _vertex_requirements()
    assert len(default) == 1
    env = default_environment() | {"sys_platform": platform}
    assert default[0].marker.evaluate(env)


def test_android_default_install_skips_vertex_but_extra_provides_it():
    default, extra = _vertex_requirements()
    env = default_environment() | {"sys_platform": "android"}
    assert not default[0].marker.evaluate(env)
    assert [r.name for r in extra] == ["langchain-google-vertexai"]
    assert extra[0].marker is None


def test_uv_lock_records_the_platform_marker_and_extra():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    artemis = next(p for p in lock["package"] if p["name"] == "artemis")
    deps = {d["name"]: d for d in artemis["dependencies"]}
    assert deps["langchain-google-vertexai"].get("marker") == "sys_platform != 'android'"
    extra = artemis["optional-dependencies"]["vertex"]
    assert [d["name"] for d in extra] == ["langchain-google-vertexai"]


def test_vertex_provider_enum_still_registered():
    assert ModelProvider.from_string("vertex") is ModelProvider.VERTEX_AI

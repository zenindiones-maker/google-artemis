"""Regression: the CI pytest step is deterministic without any real secret.

Run 39270644760 (workflow_dispatch on 3e8927f) failed with 80 failures because the
pytest step had no API key; tests/conftest.py now provides a placeholder.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _pytest_steps(wf: dict) -> list[dict]:
    return [
        step
        for job in wf["jobs"].values()
        for step in job.get("steps", [])
        if "pytest" in str(step.get("run", ""))
    ]


def test_pytest_step_exists_and_uses_no_secrets() -> None:
    steps = _pytest_steps(_workflow())
    assert steps, "ci.yml must run pytest"
    for step in steps:
        assert "secrets." not in yaml.safe_dump(step)


def test_workflow_never_reads_secrets_and_keeps_read_only_permissions() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "secrets." not in text  # also covers pull_request contexts
    assert _workflow()["permissions"] == {"contents": "read"}


def test_conftest_provides_a_non_secret_placeholder_key() -> None:
    from tests import conftest

    assert conftest.PLACEHOLDER_API_KEY == "test-placeholder-not-a-real-key"
    # setdefault: a key exported by the caller is never overwritten.
    source = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "os.environ.setdefault(_var, PLACEHOLDER_API_KEY)" in source
    for var in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        assert os.environ.get(var)


def test_all_actions_are_pinned_to_full_commit_sha() -> None:
    uses = re.findall(r"uses:\s*([^\s#]+)", CI.read_text(encoding="utf-8"))
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), ref

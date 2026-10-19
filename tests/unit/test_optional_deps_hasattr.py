"""Documented contract of ``LazyModule`` when the optional module is missing.

Confirmed on 3e8927f: ``hasattr(video.cv2, "imread")`` with cv2 missing raises
``OptionalDependencyError``, because hasattr only swallows AttributeError. Making the
error also an AttributeError is impossible (CPython: "multiple bases have instance
lay-out conflict"), and there is no current hasattr caller, so the behaviour is kept,
documented, and probing is offered through ``LazyModule.is_available()``.
"""

from __future__ import annotations

import sys

import pytest

from artemis.utils.optional_deps import LazyModule, OptionalDependencyError


def test_hasattr_on_missing_optional_module_raises_clear_error() -> None:
    lazy = LazyModule("definitely_missing_optional_mod", "Test feature")
    with pytest.raises(OptionalDependencyError) as info:
        hasattr(lazy, "anything")
    assert isinstance(info.value, ImportError)
    assert "Test feature" in str(info.value)
    assert "pip install" in str(info.value)


def test_is_available_probes_without_raising(monkeypatch) -> None:
    assert LazyModule("definitely_missing_optional_mod", "X").is_available() is False
    module = type(sys)("present_optional_mod")
    module.real = 1
    monkeypatch.setitem(sys.modules, "present_optional_mod", module)
    lazy = LazyModule("present_optional_mod", "X")
    assert lazy.is_available() is True
    assert hasattr(lazy, "real") is True
    assert hasattr(lazy, "missing_attr") is False


def test_no_production_code_calls_hasattr_on_lazy_modules() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "artemis"
    pattern = re.compile(r"hasattr\((cv2|np|jupyter_client|_zmq)\b")
    offenders = [
        str(p) for p in root.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []

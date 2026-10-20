"""CPU checks of receiver attribution in the compared-replay capability trace."""

from __future__ import annotations

import importlib.util
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def trace() -> Iterator[Any]:
    spec = importlib.util.spec_from_file_location(
        "isolated_capability_trace", Path(__file__).with_name("capability_trace.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    if module.sys.monitoring.get_tool(module.TOOL) is not None:
        module.stop()


def test_private_base_method_credits_receiver_and_real_aliases(trace: Any) -> None:
    class _Fill:
        def get_source(self) -> str:
            return "source"

    class FillLayerNode(_Fill):
        pass

    class FillEffectNode(_Fill):
        pass

    trace._index_class("api.FillLayerNode", FillLayerNode, 0)
    trace._index_class("api.LayerAlias", FillLayerNode, 0)
    trace._index_class("api.FillEffectNode", FillEffectNode, 0)
    trace._drop_shared_code()
    trace.start()
    trace.mark("layer")
    assert FillLayerNode().get_source() == "source"
    trace.mark("effect")
    assert FillEffectNode().get_source() == "source"
    found = trace.stop()
    assert {s for s in found["layer"] if s.endswith(".get_source")} == {
        "api.FillLayerNode.get_source",
        "api.LayerAlias.get_source",
    }
    assert {s for s in found["effect"] if s.endswith(".get_source")} == {
        "api.FillEffectNode.get_source"
    }


def test_properties_classmethods_and_shared_constructors_keep_receiver(trace: Any) -> None:
    class _Base:
        def __init__(self, value: int = 1) -> None:
            self.value = value

        @property
        def amount(self) -> int:
            return self.value

        @classmethod
        def kind(cls) -> str:
            return cls.__name__

    class Left(_Base):
        __init__ = _Base.__init__

    class Right(_Base):
        __init__ = _Base.__init__

    trace._index_class("api.Left", Left, 0)
    trace._index_class("api.LeftAlias", Left, 0)
    trace._index_class("api.Right", Right, 0)
    trace._drop_shared_code()
    trace.start()
    trace.mark("constructor")
    left = Left(3)
    trace.mark("left")
    assert left.amount == 3
    assert Left.kind() == "Left"
    trace.mark("right")
    assert Right(4).amount == 4
    assert Right.kind() == "Right"
    found = trace.stop()
    assert set(found["constructor"]) == {"api.Left", "api.LeftAlias"}
    assert set(found["left"]) == {
        "api.Left",
        "api.Left.amount",
        "api.Left.kind",
        "api.LeftAlias",
        "api.LeftAlias.amount",
        "api.LeftAlias.kind",
    }
    assert set(found["right"]) == {"api.Right", "api.Right.amount", "api.Right.kind"}


def test_module_function_and_refusal_contract_stay_intact(trace: Any) -> None:
    class NotYetSupported(RuntimeError):
        pass

    class _Base:
        def refused(self) -> None:
            raise NotYetSupported("unrecorded")

        def invalid(self) -> None:
            raise ValueError("recorded invalid input")

    class Left(_Base):
        pass

    class Right(_Base):
        pass

    def plain() -> str:
        return "module"

    module = types.ModuleType("api")
    module.plain = plain  # type: ignore[attr-defined]  # Synthetic public module under test.
    trace._index_module("api", module)
    trace._index_class("api.Left", Left, 0)
    trace._index_class("api.Right", Right, 0)
    trace._drop_shared_code()
    instance = Left()
    trace.start()
    trace.mark("module")
    assert plain() == "module"
    trace.mark("refusal")
    with pytest.raises(NotYetSupported):
        instance.refused()
    trace.mark("invalid")
    with pytest.raises(ValueError):
        instance.invalid()
    found = trace.stop()
    assert found["module"] == ["api.plain"]
    assert not found.get("refusal")
    assert "api.Left.invalid" in found["invalid"]
    assert "api.Right.invalid" not in found["invalid"]


def test_public_base_method_keeps_credit_and_ambiguous_factories_do_not(trace: Any) -> None:
    class Base:
        def value(self) -> int:
            return 1

    class Derived(Base):
        pass

    def factory(value: int) -> Any:
        def generated() -> int:
            return value

        return generated

    first, second = factory(1), factory(2)
    trace._index_class("api.Base", Base, 0)
    trace._index_class("api.Derived", Derived, 0)
    trace._index_value("api.first", first, 0)
    trace._index_value("api.second", second, 0)
    trace._drop_shared_code()
    trace.start()
    trace.mark("base")
    assert Derived().value() == 1
    trace.mark("factories")
    assert first() == 1
    assert second() == 2
    found = trace.stop()
    assert set(found["base"]) == {"api.Derived", "api.Base.value"}
    assert not found.get("factories")

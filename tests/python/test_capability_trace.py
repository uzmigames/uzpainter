"""CPU checks of receiver and thread attribution in the compared-replay capability trace."""

from __future__ import annotations

import _thread
import importlib.util
import sys
import threading
import types
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


def test_required_dataclass_fields_trace_real_access_and_restore(trace: Any) -> None:
    class NotYetSupported(Exception):
        pass

    @dataclass
    class Value:
        left: int
        right: int

        def __setattr__(self, name: str, value: Any) -> None:
            if value == "refused":
                raise NotYetSupported("authored refusal")
            if value == "invalid":
                raise ValueError("authored validation error")
            object.__setattr__(self, name, value)

    original = dict(vars(Value))
    trace._index_class("api.Value", Value, 0)
    trace.start()
    value = Value(1, 2)
    trace.mark("instance-only")
    trace._scan(value)
    trace.mark("read")
    assert value.left == 1
    trace.mark("write")
    value.right = 3
    trace.mark("invalid")
    # Deliberately invalid assignments distinguish public errors from unsupported refusals.
    with pytest.raises(ValueError):
        value.left = "invalid"  # type: ignore[assignment]
    trace.mark("refused")
    with pytest.raises(NotYetSupported):
        value.right = "refused"  # type: ignore[assignment]
    trace.mark("delete")
    del value.left
    trace.mark("missing")
    with pytest.raises(AttributeError):
        _ = value.left
    found = trace.stop()
    field_names = {"api.Value.left", "api.Value.right"}
    assert not set(found.get("setup", [])) & field_names
    assert not set(found.get("instance-only", [])) & field_names
    assert set(found["read"]) & field_names == {"api.Value.left"}
    assert set(found["write"]) & field_names == {"api.Value.right"}
    assert set(found["invalid"]) & field_names == {"api.Value.left"}
    assert not set(found.get("refused", [])) & field_names
    assert set(found["missing"]) & field_names == {"api.Value.left"}
    assert vars(Value) == original
    assert vars(value) == {"right": 3}
    del value.right
    assert vars(value) == {}


def test_dataclass_field_ownership_public_private_and_unindexed_child(
    trace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    @dataclass
    class Parent:
        inherited: int

    @dataclass
    class Child(Parent):
        own: int

    class Unindexed(Parent):
        def __init__(self, inherited: int) -> None:
            self.inherited = inherited

    @dataclass
    class _Private:
        hidden_owner: int

    class Public(_Private):
        pass

    originals = {cls: dict(vars(cls)) for cls in (Parent, Child, Public, Unindexed, _Private)}
    for qualified, cls in (
        ("api.Parent", Parent),
        ("api.Child", Child),
        ("api.Public", Public),
        ("api.Alias", Public),
    ):
        trace._index_class(qualified, cls, 0)
    assert "api.Child.inherited" not in trace._names
    notes: list[set[str]] = []
    note = trace._note

    def count(names: set[str]) -> None:
        if any(name.endswith((".inherited", ".own", ".hidden_owner")) for name in names):
            notes.append(set(names))
        note(names)

    monkeypatch.setattr(trace, "_note", count)
    trace.start()
    child, unindexed, public = Child(1, 2), Unindexed(3), Public(4)
    notes.clear()
    trace.mark("inherited")
    assert child.inherited == 1
    assert notes == [{"api.Parent.inherited"}]
    trace.mark("own")
    child.own = 5
    trace.mark("unindexed")
    assert unindexed.inherited == 3
    trace.mark("private")
    assert public.hidden_owner == 4
    found = trace.stop()
    assert not {
        name
        for name in found.get("setup", [])
        if name.endswith((".inherited", ".own", ".hidden_owner"))
    }
    assert "api.Parent.inherited" in found["inherited"]
    assert "api.Child.own" in found["own"]
    assert "api.Parent.inherited" in found["unindexed"]
    assert {name for name in found["private"] if name.endswith(".hidden_owner")} == {
        "api.Public.hidden_owner",
        "api.Alias.hidden_owner",
    }
    assert all(vars(cls) == original for cls, original in originals.items())


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


class _Dispatcher:
    """A dispatcher thread the trace did not start, as UzPainter's native one: `post` queues a
    task, `deliver` runs the queued tasks on a raw thread and waits for them."""

    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def post(self, task: Any) -> None:
        self.tasks.append(task)

    def deliver(self) -> None:
        done = threading.Event()

        def loop() -> None:
            for task in self.tasks:
                task()
            self.tasks.clear()
            done.set()

        _thread.start_new_thread(loop, ())
        assert done.wait(10.0)


@pytest.fixture
def api(trace: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _Dispatcher]:
    """A synthetic public module `api`, and a `uzpainter.event.post` over `_Dispatcher`."""

    def work() -> str:
        return "work"

    def nested() -> str:
        return "nested"

    def delivered() -> str:
        return "delivered"

    def other() -> str:
        return "other"

    module = types.ModuleType("api")
    for function in (work, nested, delivered, other):
        setattr(module, function.__name__, function)
    trace._index_module("api", module)
    trace._drop_shared_code()
    dispatcher = _Dispatcher()
    uzpainter = types.ModuleType("uzpainter")
    uzpainter.event = types.SimpleNamespace(post=dispatcher.post)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uzpainter", uzpainter)
    return module, dispatcher


def test_worker_calls_belong_to_the_output_that_started_it(
    trace: Any, api: tuple[Any, _Dispatcher]
) -> None:
    module, dispatcher = api
    event = sys.modules["uzpainter"].event
    go = threading.Event()

    def worker() -> None:
        go.wait()
        module.work()
        inner = threading.Thread(target=module.nested)
        inner.start()
        inner.join()
        event.post(module.delivered)

    trace.start()
    trace.mark("A")
    thread = threading.Thread(target=worker)
    thread.start()
    trace.mark("B")
    go.set()
    thread.join()
    trace.mark("C")
    dispatcher.deliver()
    trace.mark("D")
    module.other()
    found = trace.stop()
    # The worker ran after B began and its posted task after C: both belong to A, as does the
    # thread it started.
    assert found == {"A": ["api.delivered", "api.nested", "api.work"], "D": ["api.other"]}


def test_an_excluded_starting_output_gives_its_worker_no_credit(
    trace: Any, api: tuple[Any, _Dispatcher]
) -> None:
    module, dispatcher = api
    event = sys.modules["uzpainter"].event
    go = threading.Event()

    def worker() -> None:
        go.wait()
        module.work()
        event.post(module.delivered)

    trace.start()
    trace.mark("s23/reload")
    thread = threading.Thread(target=worker)
    thread.start()
    trace.mark("s23/states")
    go.set()
    thread.join()
    dispatcher.deliver()
    module.other()
    found = trace.stop()
    assert found == {"s23/reload": ["api.delivered", "api.work"], "s23/states": ["api.other"]}
    assert trace.exercised(found, ["s23/reload"]) == ["api.other"]


def test_main_dispatcher_and_service_threads_keep_the_marked_output(
    trace: Any, api: tuple[Any, _Dispatcher]
) -> None:
    module, dispatcher = api
    event = sys.modules["uzpainter"].event
    original_start, original_post = threading.Thread.start, event.post
    request, done, finish = threading.Event(), threading.Event(), threading.Event()

    def service() -> None:
        while True:
            request.wait()
            request.clear()
            if finish.is_set():
                return
            module.work()
            done.set()

    trace.start()
    assert threading.Thread.start is not original_start
    trace.mark("A")
    module.other()
    event.post(module.delivered)  # posted on the main thread, delivered during B
    trace.mark("B")
    dispatcher.deliver()
    thread = threading.Thread(target=service, daemon=True)
    thread.start()  # started during B, still running at stop()
    trace.mark("C")
    request.set()
    assert done.wait(10.0)
    found = trace.stop()
    finish.set()
    request.set()
    thread.join()
    assert found == {"A": ["api.other"], "B": ["api.delivered"], "C": ["api.work"]}
    assert threading.Thread.start is original_start
    assert event.post == original_post

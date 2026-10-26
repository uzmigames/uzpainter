"""Host extension installation and private output preparation, with real local dispatch."""

from __future__ import annotations

from typing import Any

import pytest

from tests.parity.test_painter_filter_context import Session, World
from tools.parity.filter_context_contract import ALLOWED_CALLS, SPEC, ContextRefused
from tools.parity.recorder.filter_context import (
    PAINTER_FILTER_CONTEXT,
    context_outputs,
    context_readback,
    extension_code,
    step_trace,
)
from tools.parity.recorder.provenance import documented_symbols


def test_host_returns_api_leaves_without_modifying_probe_dispatch_or_recipe() -> None:
    world = World()
    session = Session(world)
    outputs = context_outputs(session, "after-create")
    assert outputs and all(row["output_id"].startswith("context/after-create/") for row in outputs)
    assert all(row["kind"] == "api_readback" for row in outputs)
    assert set(session.probes["OPERATIONS"]) == {"filter_context_read"}
    assert not world.setup


def test_second_extension_installation_refuses_dispatch_replacement() -> None:
    session = Session(World())
    operation = session.probes["OPERATIONS"]["filter_context_read"]
    with pytest.raises(ValueError, match="already registered"):
        exec(extension_code(PAINTER_FILTER_CONTEXT.read_text(encoding="utf-8")), session.globals)
    assert session.probes["OPERATIONS"]["filter_context_read"] is operation


def test_dispatch_rejects_unknown_or_mismatched_boundary() -> None:
    session = Session(World())
    for args in (
        {"boundary": "unknown", "condition": "same_session"},
        {"boundary": "after-create", "condition": "after_save_reopen"},
        {"boundary": "after-create", "condition": "same_session", "override": True},
    ):
        with pytest.raises(ValueError):
            session.call("filter_context_read", **args)


def test_host_refuses_wrong_response_boundary() -> None:
    frame = context_readback(Session(World()), "after-create")

    class OtherBoundary:
        def call(self, operation: str, **args: Any) -> Any:
            return frame

    with pytest.raises(ValueError, match="another boundary"):
        context_readback(OtherBoundary(), "after-setup6")
    with pytest.raises(ValueError, match="unknown"):
        context_readback(OtherBoundary(), "missing")


def test_host_refuses_extra_response_member() -> None:
    frame = context_readback(Session(World()), "after-create")
    frame["settings"] = {"mesh_unit_scale": 1}

    class InventedSettings:
        def call(self, operation: str, **args: Any) -> Any:
            return frame

    with pytest.raises(ContextRefused):
        context_readback(InventedSettings(), "after-create")


def test_trace_keeps_expected_setter_refusal() -> None:
    raised = {"type": "ValueError", "message": "not supported for Filter"}
    step = {
        "step": 19,
        "call": "substance_painter.source.SourceSubstance.resolution",
        "args": {"probe": True},
    }
    recorded = step_trace("same_session", step, {"raised": raised})
    assert recorded["outcome"] == {"value": None, "raised": raised}


def test_dynamic_getters_use_documented_spec_and_refuse_caller_dispatch() -> None:
    documented = documented_symbols()
    spec_calls = {call for calls in SPEC.values() for call in calls}
    assert spec_calls <= ALLOWED_CALLS
    assert not (ALLOWED_CALLS - documented.keys())
    allowed_members = {call.rsplit(".", 1)[1] for call in spec_calls}
    observed: list[str] = []

    def checked_getattr(obj: Any, name: str) -> Any:
        # Dynamic lookup in this extension is restricted to the public SPEC vocabulary.
        assert name in allowed_members
        observed.append(name)
        return getattr(obj, name)

    world = World()
    world.setup = True
    session = Session(world)
    session.globals["uzp_filter_context"]["getattr"] = checked_getattr
    context_readback(session, "after-setup6")
    assert observed and "get_geometry_mask" in observed and "get_opacity" in observed
    lookup_count = len(world.lookups)
    observed_count = len(observed)
    arbitrary_args: tuple[dict[str, Any], ...] = (
        {"call": "delete_node"},
        {"selector": {"role": "arbitrary"}},
        {"getter": "delete_node"},
        {"FILTER_CONTEXT_SPEC": {}},
    )
    for extra in arbitrary_args:
        with pytest.raises(ValueError, match="invalid F context boundary"):
            session.call(
                "filter_context_read", boundary="after-setup6", condition="same_session", **extra
            )
    assert len(world.lookups) == lookup_count and len(observed) == observed_count

"""Authored snapshot bridge controls; no Painter resource values or captured pixels."""

from __future__ import annotations

import os
import runpy
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

from python.uzpainter_snapshot import bridge
from tools.parity.recorder.provenance import check_files, recorder_sources

RESOURCE = "resource://authored/test?version=123"


def readback() -> dict[str, Any]:
    source = {
        "resource": RESOURCE,
        "parameters": {"gain": 0.5, "$randomseed": 7},
        "inputs": [],
        "outputs": ["value"],
        "presets": ["authored preset"],
        "properties": {
            "gain": {
                "value": 0.5,
                "name": "gain",
                "short_name": "gain",
                "label": "Authored gain",
                "widget_type": "Slider",
                "enum_values": {},
                "properties": {"min": 0, "max": 1},
            }
        },
        "active_output": "value",
        "resolution": {"mode": "Auto", "value": [1024, 1024], "log2_offset": 0},
        "opacity": 1,
        "blending": "Normal",
    }
    return {
        "channel_formats": {"User0": "L32F", "User1": "RGB32F"},
        "source_mode": "Split",
        "projection_mode": "UV",
        "active_channels": ["User0", "User1"],
        "projection": {
            "filtering": "Nearest",
            "wrapping": "RepeatNone",
            "scale_mode": "Factors",
            "scale": [1, 1],
            "rotation": 0,
            "offset": [0, 0],
        },
        "isolated_tree": {
            "roots": [123],
            "fill": 123,
            "visible": True,
            "mask": False,
            "content_effects": [],
            "mask_effects": [],
        },
        "sets": [{"name": "uzp_plane", "resolution": [128, 128], "has_uv_tiles": False}],
        "sources": [deepcopy(source), deepcopy(source)],
    }


@pytest.mark.parametrize("value", [None, [], [1, 2], {"x": 1}, float("nan"), float("inf"), 1 << 63])
def test_unobserved_parameter_shapes_refuse(value: Any) -> None:
    with pytest.raises(ValueError, match="finite scalar"):
        bridge.scalar_parameters({"x": value})


@pytest.mark.parametrize(
    "resource",
    [
        "resource://authored/test",
        "resource://authored/test?version=",
        "https://example.com/x?version=1",
        RESOURCE + "&version=456",
    ],
)
def test_unpinned_or_ambiguous_resource_refuses(resource: str) -> None:
    with pytest.raises(ValueError):
        bridge.capture_request({"resource": resource, "parameters": {}})


def test_effective_defaults_are_retained_and_overrides_checked() -> None:
    request = bridge.capture_request({"resource": RESOURCE, "parameters": {"gain": 0.5}})
    source = bridge.validate_readback(readback(), request)
    assert source["parameters"] == {"gain": 0.5, "$randomseed": 7}
    request["parameters"]["gain"] = 1
    with pytest.raises(ValueError, match="effective parameters"):
        bridge.validate_readback(readback(), request)


def observed_readback() -> dict[str, Any]:
    observed = readback()
    for source in observed["sources"]:
        source["resource_id"] = {
            "url": RESOURCE,
            "context": "authored",
            "name": "test",
            "version": "123",
        }
        source["parameters"].update({"integer": 1, "double": 1.0, "negative_zero": -0.0})
    return observed


def test_complete_observation_retains_identity_and_scalar_types() -> None:
    observed = observed_readback()
    before = bridge.canonical_state(observed)
    source = bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})
    assert source["resource_id"] == observed["sources"][1]["resource_id"]
    assert bridge.canonical_state(observed) == before
    legacy = bridge.validate_readback(readback(), {"resource": RESOURCE, "parameters": {}})
    assert "resource_id" not in legacy


@pytest.mark.parametrize("field", ["url", "context", "name", "version"])
@pytest.mark.parametrize("value", [None, "", 1, True, [], {}])
def test_invalid_observed_identity_refuses(field: str, value: Any) -> None:
    observed = observed_readback()
    for source in observed["sources"]:
        source["resource_id"][field] = value
    with pytest.raises(ValueError, match="observed ResourceID"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


@pytest.mark.parametrize("field", ["url", "context", "name", "version"])
def test_incomplete_observed_identity_refuses(field: str) -> None:
    observed = observed_readback()
    for source in observed["sources"]:
        del source["resource_id"][field]
    with pytest.raises(ValueError, match="observed ResourceID"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


@pytest.mark.parametrize("field,value", [("extra", "unexpected"), ("url", RESOURCE + "changed")])
def test_closed_observed_identity_and_matching_url_required(field: str, value: str) -> None:
    observed = observed_readback()
    for source in observed["sources"]:
        source["resource_id"][field] = value
    with pytest.raises(ValueError, match="observed ResourceID"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


@pytest.mark.parametrize("left,right", [(1, 1.0), (0.0, -0.0), (True, 1)])
def test_paired_parameter_types_must_match(left: Any, right: Any) -> None:
    observed = observed_readback()
    observed["sources"][0]["parameters"]["gain"] = left
    observed["sources"][1]["parameters"]["gain"] = right
    with pytest.raises(ValueError, match="paired source state differs"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


def test_observed_bool_cannot_be_coerced_to_integer() -> None:
    observed = observed_readback()
    for source in observed["sources"]:
        source["parameters"]["gain"] = True
    with pytest.raises(ValueError, match="retain observed scalar types"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


def test_paired_observed_identities_must_match() -> None:
    observed = observed_readback()
    observed["sources"][1]["resource_id"]["name"] = "other"
    with pytest.raises(ValueError, match="paired source state differs"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


@pytest.mark.parametrize(
    "field,value",
    [
        ("inputs", ["input"]),
        ("outputs", ["value", "other"]),
        ("opacity", 0.5),
        ("blending", "Multiply"),
        ("resource", RESOURCE + "changed"),
        ("resolution", {"mode": "Auto", "value": [1024, 1024], "log2_offset": 1}),
    ],
)
def test_unsupported_source_state_refuses(field: str, value: Any) -> None:
    observed = readback()
    for source in observed["sources"]:
        source[field] = value
    with pytest.raises(ValueError, match="capture domain"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


@pytest.mark.parametrize(
    "field,value",
    [
        ("roots", [123, 456]),
        ("visible", False),
        ("mask", True),
        ("content_effects", [456]),
        ("mask_effects", [456]),
    ],
)
def test_composited_or_hidden_layer_refuses(field: str, value: Any) -> None:
    observed = readback()
    observed["isolated_tree"][field] = value
    with pytest.raises(ValueError, match="tree is not isolated"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


@pytest.mark.parametrize("field", ["presets", "properties"])
def test_paired_sources_with_different_observations_refuse(field: str) -> None:
    """The recorded presets and property descriptions must agree across the paired sources."""
    observed = readback()
    observed["sources"][1][field] = [] if field == "presets" else {}
    with pytest.raises(ValueError, match="paired source state differs"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


def test_lower_precision_channel_refuses() -> None:
    observed = readback()
    observed["channel_formats"]["User0"] = "L8"
    with pytest.raises(ValueError, match="native precision"):
        bridge.validate_readback(observed, {"resource": RESOURCE, "parameters": {}})


def painter_module(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    package = ModuleType("substance_painter")
    monkeypatch.setitem(sys.modules, "substance_painter", package)
    modules: dict[str, Any] = {}
    for name in (
        "application",
        "export",
        "layerstack",
        "project",
        "resource",
        "source",
        "textureset",
    ):
        module = ModuleType("substance_painter." + name)
        monkeypatch.setattr(package, name, module, raising=False)
        monkeypatch.setitem(sys.modules, "substance_painter." + name, module)
        modules[name] = module
    modules["application"].version = lambda: "authored"
    modules["application"].version_info = lambda: (1, 0, 0)
    modules["project"].is_open = lambda: True
    modules["project"].last_imported_mesh_path = lambda: "foreign.obj"
    module_globals = runpy.run_path(str(Path(bridge.__file__).with_name("painter_side.py")))
    return module_globals, modules


@pytest.mark.parametrize("operation", ["configure", "readback", "export", "close", "ready", "idle"])
def test_painter_dispatch_refuses_lost_ownership_before_operation(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    module_globals, _ = painter_module(monkeypatch)
    module_globals["STATE"]["owner"] = {"pid": os.getpid(), "mesh": "owned.obj"}
    with pytest.raises(RuntimeError, match="ownership"):
        module_globals["dispatch"](operation, {})


def test_painter_readback_observes_resource_fields_without_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_globals, modules = painter_module(monkeypatch)
    fill = MagicMock()
    source = fill.get_source.return_value
    identifier = source.resource_id
    identifier.url.return_value = RESOURCE
    identifier.context = "documented context"
    identifier.name = "documented name"
    identifier.version = "documented version"
    parameters = {"integer": 1, "double": 1.0, "negative_zero": -0.0}
    source.get_parameters.return_value = parameters
    source.get_properties.return_value = {}
    channel = MagicMock()
    channel.name = "User0"
    module_globals["STATE"].update(fill=fill, channels=[channel], stack=MagicMock())
    modules["layerstack"].get_root_layer_nodes = lambda stack: []
    modules["textureset"].all_texture_sets = lambda: []
    captured = module_globals["readback"]()["sources"][0]
    assert captured["resource"] == RESOURCE
    assert captured["resource_id"] == {
        "url": RESOURCE,
        "context": "documented context",
        "name": "documented name",
        "version": "documented version",
    }
    assert captured["parameters"] is parameters


class FakeRemote:
    def __init__(self, mesh: str, foreign: bool = False, open_project: bool = False) -> None:
        self.mesh = mesh
        self.foreign = foreign
        self.open_project = open_project
        self.created = False
        self.closed = False
        self.failure = ""

    def wait(self, operation: str, timeout: float = 120) -> None:
        pass

    def call(self, operation: str, args: dict[str, Any] | None = None) -> Any:
        if operation == "identity":
            return {
                "pid": 123,
                "version": "authored",
                "version_info": [1, 0, 0],
                "OCIO": None,
                "PAINTER_ACE_CONFIG": None,
                "project_open": self.created or self.open_project,
                "mesh": "foreign.obj" if self.foreign else self.mesh,
            }
        if operation == "lookup":
            return [{"url": RESOURCE, "type": "SUBSTANCE", "procedural": True}]
        if operation == "create":
            self.created = True
            if self.failure == "create":
                raise OSError("response lost after project creation")
        if operation == "close":
            self.closed = True
        if operation == "readback":
            return readback()
        if operation == "export":
            if self.failure == "export":
                raise RuntimeError("export failed")
            assert args is not None
            root = Path(args["exportPath"])
            files = [root / "user0.exr", root / "user1.exr"]
            for path in files:
                path.write_bytes(b"synthetic bridge test; native decoder tests are separate")
            return {"status": "Success", "message": "", "files": [str(p) for p in files]}
        return None


def test_capture_records_pin_and_closes_only_owned_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    remote = FakeRemote(str(tmp_path / "mesh.obj"))
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    context = {"mesh_path": remote.mesh, "project_uuid": "authored", "revision": 5, "settings": {}}
    report = bridge.record(context, {"resource": RESOURCE, "parameters": {}}, tmp_path)
    assert remote.created and remote.closed
    assert report["signature"]["asset"].startswith("uzasset://snapshot/")
    assert report["signature"]["params"]["$randomseed"] == 7
    assert report["revision"] == 5


def test_foreign_project_is_never_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    remote = FakeRemote(str(tmp_path / "mesh.obj"), foreign=True)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    with pytest.raises(RuntimeError, match="ownership"):
        bridge.record(
            {"mesh_path": remote.mesh}, {"resource": RESOURCE, "parameters": {}}, tmp_path
        )
    assert not remote.closed


@pytest.mark.parametrize("left,right", [(1, 1.0), (0.0, -0.0)])
def test_capture_refuses_parameter_type_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, left: Any, right: Any
) -> None:
    class DriftingRemote(FakeRemote):
        observations = 0

        def call(self, operation: str, args: dict[str, Any] | None = None) -> Any:
            if operation == "readback":
                observed = observed_readback()
                for source in observed["sources"]:
                    source["parameters"]["gain"] = left if self.observations == 0 else right
                self.observations += 1
                return observed
            return super().call(operation, args)

    remote = DriftingRemote(str(tmp_path / "mesh.obj"))
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    with pytest.raises(RuntimeError, match="source state changed"):
        bridge.record(
            {"mesh_path": remote.mesh}, {"resource": RESOURCE, "parameters": {}}, tmp_path
        )
    assert remote.closed


def test_existing_project_refuses_before_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    remote = FakeRemote("user.obj", open_project=True)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    with pytest.raises(RuntimeError, match="already has"):
        bridge.record({}, {"resource": RESOURCE, "parameters": {}}, tmp_path)
    assert not remote.created and not remote.closed


def test_missing_painter_refuses_before_any_project_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class MissingPainter(FakeRemote):
        def call(self, operation: str, args: dict[str, Any] | None = None) -> Any:
            raise ConnectionRefusedError("Painter endpoint unavailable")

    remote = MissingPainter("owned.obj")
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    with pytest.raises(ConnectionRefusedError):
        bridge.record({}, {"resource": RESOURCE, "parameters": {}}, tmp_path)
    assert not remote.created and not remote.closed
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["create", "export"])
def test_owned_project_closes_after_capture_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: str,
) -> None:
    remote = FakeRemote(str(tmp_path / "mesh.obj"))
    remote.failure = operation
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    with pytest.raises((RuntimeError, OSError)):
        bridge.record(
            {"mesh_path": remote.mesh}, {"resource": RESOURCE, "parameters": {}}, tmp_path
        )
    assert remote.closed


def test_shipped_painter_operations_are_in_provenance_scan() -> None:
    paths = [p for p in recorder_sources() if "uzpainter_snapshot" in p.parts]
    assert {p.name for p in paths} == {"__init__.py", "bridge.py", "painter_side.py"}
    assert check_files(paths) == []

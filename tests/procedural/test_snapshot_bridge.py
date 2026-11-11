"""Authored snapshot bridge controls; no Painter resource values or captured pixels."""

from __future__ import annotations

import hashlib
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
        "colormanagement",
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
    modules["colormanagement"].Color = type("Color", (), {})
    module_globals = runpy.run_path(str(Path(bridge.__file__).with_name("painter_side.py")))
    return module_globals, modules


@pytest.mark.parametrize(
    "operation",
    [
        "configure",
        "readback",
        "export",
        "close",
        "ready",
        "idle",
        "set_output",
        "preset_parameters",
        "contexts",
        "mesh_maps",
        "configure_generator",
        "generator_readback",
    ],
)
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
    assert bridge.canonical_state(captured["parameters"]) == bridge.canonical_state(parameters)


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


# ── Multi-output captures (decision 412 §3) ─────────────────────────────────────────────────────

UNPLUGGED = {"raised": {"type": "ValueError", "message": "authored unplugged input"}}
REFUSED = {"raised": {"type": "EditionContextException", "message": "authored refusal"}}


def multi_request(tmp_path: Path, **inputs: Any) -> dict[str, Any]:
    bitmap = tmp_path / "authored.png"
    bitmap.write_bytes(b"authored bitmap bytes")
    plugs = {
        name: {"bitmap": str(bitmap)} if plug == "bitmap" else plug for name, plug in inputs.items()
    }
    return bridge.capture_request(
        {"resource": RESOURCE, "parameters": {}, "preset": "authored preset", "inputs": plugs}
    )


class MultiRemote(FakeRemote):
    """Two outputs, one image input, one preset; every readback is computed from the state."""

    def __init__(self, mesh: str) -> None:
        super().__init__(mesh)
        self.active = "first"
        self.plugs: dict[str, Any] = {}
        self.bitmaps: dict[str, str] = {}
        self.calls: list[str] = []
        self.material_parameters: dict[str, Any] | None = None

    def input_source(self) -> dict[str, Any]:
        plug = self.plugs.get("mask")
        if plug is None:
            return UNPLUGGED
        if "color" in plug:
            return {"class": "SourceUniformColor", "working": plug["color"]}
        if "remove" in plug:
            return {"class": "SourceUniformColor", "working": [0.0, 0.0, 0.0]}
        url = self.bitmaps[plug["bitmap"]]
        return {"class": "SourceBitmap", "resource": url, "colour_space": "Data"}

    def state(self) -> dict[str, Any]:
        observed = observed_readback()
        for source in observed["sources"]:
            source["outputs"] = ["first", "second"]
            source["active_output"] = self.active
            source["inputs"] = ["mask"]
            source["input_sources"] = {"mask": self.input_source()}
        observed["bitmaps"] = dict(self.bitmaps)
        return observed

    def call(self, operation: str, args: dict[str, Any] | None = None) -> Any:
        self.calls.append(operation)
        if operation == "configure":
            assert args is not None
            self.plugs = dict(args["inputs"])
            for plug in self.plugs.values():
                if "bitmap" in plug:
                    self.bitmaps[plug["bitmap"]] = "resource://project1/authored?version=1"
            return None
        if operation == "readback":
            return self.state()
        if operation == "set_output":
            assert args is not None
            self.active = args["output"]
            return None
        if operation == "preset_parameters":
            parameters = {"gain": 0.25, "$randomseed": 7, "integer": 1, "double": 1.0}
            return {"authored preset": [parameters, dict(parameters)]}
        if operation == "contexts":
            source = self.state()["sources"][0]
            return {
                "split": {
                    "output_mapping": REFUSED,
                    "mask_output": REFUSED,
                },
                "material": {
                    "output_mapping": {"Height": "second", "Normal": "first"},
                    "mask_output": "authored_alpha",
                    "active_channels": [],
                    "parameters": self.material_parameters or source["parameters"],
                    "input_sources": source["input_sources"],
                    "active_output": REFUSED,
                },
            }
        return super().call(operation, args)


def test_multi_request_shape_and_refusals(tmp_path: Path) -> None:
    request = multi_request(tmp_path, mask={"color": [0.25, 0.5, 1]})
    assert request["preset"] == "authored preset"
    assert request["inputs"] == {"mask": {"color": [0.25, 0.5, 1.0]}}
    legacy = bridge.capture_request({"resource": RESOURCE, "parameters": {}})
    assert "inputs" not in legacy and "preset" not in legacy
    base: dict[str, Any] = {"resource": RESOURCE, "parameters": {}, "preset": None}
    for plug in (
        {"color": [0, 0]},
        {"color": [0, 0, True]},
        {"color": [0, 0, float("nan")]},
        {"bitmap": "relative.png"},
        {"bitmap": str(tmp_path / "missing.png")},
        {"remove": False},
        {"color": [0, 0, 0], "remove": True},
        {},
    ):
        with pytest.raises(ValueError):
            bridge.capture_request({**base, "inputs": {"mask": plug}})
    with pytest.raises(ValueError, match="no parameter overrides"):
        bridge.capture_request({**base, "parameters": {"gain": 1}, "preset": "p", "inputs": {}})
    with pytest.raises(ValueError, match="preset"):
        bridge.capture_request({**base, "preset": "", "inputs": {}})
    with pytest.raises(ValueError, match="exactly resource"):
        bridge.capture_request({**base, "inputs": {}, "extra": 1})


@pytest.mark.parametrize(
    "plug,expected",
    [
        (None, {}),
        ({"color": [0.25, 0.5, 0.75]}, {"mask": {"working_colour": [0.25, 0.5, 0.75]}}),
        ({"remove": True}, {"mask": {"working_colour": [0.0, 0.0, 0.0]}}),
        ("bitmap", "bitmap"),
    ],
)
def test_multi_capture_records_every_output_through_both_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, plug: Any, expected: Any
) -> None:
    remote = MultiRemote(str(tmp_path / "mesh.obj"))
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    request = multi_request(tmp_path, **({} if plug is None else {"mask": plug}))
    context = {"mesh_path": remote.mesh, "project_uuid": "authored", "revision": 5, "settings": {}}
    work = tmp_path / "work"
    work.mkdir()
    report = bridge.record(context, request, work)
    assert remote.created and remote.closed
    assert report["schema"] == "uzpainter/procedural-capture/2"
    captures = report["captures"]
    assert [(c["output"], c["signature"]["output"]["channels"]) for c in captures] == [
        ("first", 1),
        ("first", 3),
        ("second", 1),
        ("second", 3),
    ]
    assert captures[1]["file"] == "output0-export1/user1.exr"
    assert captures[1]["repeat"] == "output0-export2/user1.exr"
    signature = captures[0]["signature"]
    assert signature["preset"] == "authored preset"
    if expected == "bitmap":
        digest = hashlib.sha256(b"authored bitmap bytes").hexdigest()
        expected = {"mask": {"bitmap_sha256": digest, "colour_space": "Data"}}
        assert report["bitmaps"] == {(work / "inputs" / "0.png").as_posix(): digest}
    assert signature["inputs"] == expected
    assert report["preset_parameters"]["authored preset"]["gain"] == 0.25
    assert report["contexts"]["material"]["mask_output"] == "authored_alpha"
    # The active output is restored before the presets and contexts are read.
    assert remote.active == "first"
    assert remote.calls.index("preset_parameters") > remote.calls.index("export")


def test_multi_capture_refuses_another_material_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    remote = MultiRemote(str(tmp_path / "mesh.obj"))
    remote.material_parameters = {"gain": 1}
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    context = {"mesh_path": remote.mesh, "project_uuid": "authored", "revision": 5, "settings": {}}
    with pytest.raises(ValueError, match="material source"):
        bridge.record(context, multi_request(tmp_path), tmp_path)
    assert remote.closed


def test_multi_capture_refuses_a_plug_painter_did_not_apply(tmp_path: Path) -> None:
    request = multi_request(tmp_path, mask={"color": [0.25, 0.5, 0.75]})
    readback = MultiRemote("mesh.obj").state()
    source = readback["sources"][0]
    with pytest.raises(ValueError, match="does not read back a uniform colour"):
        bridge.signature_inputs(source, request, readback, {})
    source["input_sources"]["mask"] = {"class": "SourceUniformColor", "working": [0.25, 0.5, 0.7]}
    with pytest.raises(ValueError, match="another working colour"):
        bridge.signature_inputs(source, request, readback, {})
    source["input_sources"]["mask"] = {"class": "SourceUniformColor", "working": [0, 0, 0]}
    unplugged = dict(request, inputs={})
    with pytest.raises(ValueError, match="request leaves it unplugged"):
        bridge.signature_inputs(source, unplugged, readback, {})


def test_unplugged_input_reads_back_as_a_bitmap_without_resource(tmp_path: Path) -> None:
    """Painter returns a `SourceBitmap` whose `resource_id` raises for an unplugged input."""
    readback = MultiRemote("mesh.obj").state()
    source = readback["sources"][0]
    source["input_sources"]["mask"] = {
        "class": "SourceBitmap",
        "resource_id": UNPLUGGED,
        "colour_space": "Data",
    }
    assert bridge.signature_inputs(source, multi_request(tmp_path), readback, {}) == {}
    with pytest.raises(ValueError, match="requested bitmap"):
        bridge.signature_inputs(source, multi_request(tmp_path, mask="bitmap"), readback, {})


# ── Captures on the destination's own mesh and resolution (decision 428) ────────────────────────

GENERATOR = "resource://authored/generator?version=456"
SET = "authored_set"
MESH_MAP_URLS = {
    "AO": "resource://project1/ao?version=1",
    "Curvature": "resource://project1/c?version=1",
}
SIGNATURE_INPUTS = {
    usage: {
        "sha256": "ab" * 32,
        "resolution": 256,
        "format": "u16",
        "colour_space": "",
        "channels": 1,
    }
    for usage in MESH_MAP_URLS
}


def usage_context(tmp_path: Path, generator: bool) -> dict[str, Any]:
    files = {u: str(tmp_path / f"{u}.png") for u in MESH_MAP_URLS} if generator else {}
    return {
        "mesh_path": str(tmp_path / "mesh.obj"),
        "project_uuid": "authored",
        "revision": 7,
        "settings": {"workflow": "Default"},
        "texture_set": SET,
        "resolution": 256,
        "mesh_maps": files,
        "signature_inputs": SIGNATURE_INPUTS if generator else {},
    }


def generator_readback(context: dict[str, Any]) -> dict[str, Any]:
    files = {path: MESH_MAP_URLS[usage] for usage, path in context["mesh_maps"].items()}
    bound = {usage: MESH_MAP_URLS.get(usage) for usage in bridge.MESH_MAP_USAGES}

    def layer(uid: int, value: int, masked: bool) -> dict[str, Any]:
        channel = {"value": [value, value, value], "opacity": 1, "blending": "Normal"}
        return {
            "uid": uid,
            "visible": True,
            "mask": masked,
            "content_effects": [],
            "mask_effects": [30] if masked else [],
            "source_mode": "Split",
            "active_channels": ["User0", "User1"],
            "channels": {"User0": dict(channel), "User1": dict(channel)},
        }

    return {
        "channel_formats": {"User0": "L32F", "User1": "RGB32F"},
        "roots": [20, 10],
        "layers": {"fill": layer(20, 1, True), "base": layer(10, 0, False)},
        "effect": {"uid": 30, "visible": True},
        "generator": {
            "resource": GENERATOR,
            "resource_id": {"url": GENERATOR, "context": "authored", "name": "g", "version": "456"},
            "parameters": {"amount": 0.5, "$randomseed": 3},
            "inputs": [],
            "outputs": ["mask"],
            "active_output": {"value": "mask"},
        },
        "mesh_maps": {SET: bound},
        "mesh_map_files": files,
        "sets": [{"name": SET, "resolution": [256, 256], "has_uv_tiles": False}],
    }


class UsageRemote(FakeRemote):
    """A Painter creating the destination texture set; it records the operations it ran."""

    def __init__(self, context: dict[str, Any], generator: bool) -> None:
        super().__init__(context["mesh_path"])
        self.generator = generator
        self.calls: list[tuple[str, Any]] = []
        self.observed = generator_readback(context)

    def call(self, operation: str, args: dict[str, Any] | None = None) -> Any:
        self.calls.append((operation, deepcopy(args)))
        if operation == "lookup":
            return [
                {
                    "url": GENERATOR if self.generator else RESOURCE,
                    "type": "SUBSTANCE",
                    "procedural": not self.generator,
                    "generator": self.generator,
                }
            ]
        if operation == "readback":
            observed = observed_readback()
            observed["sets"] = [{"name": SET, "resolution": [256, 256], "has_uv_tiles": False}]
            return observed
        if operation == "generator_readback":
            return deepcopy(self.observed)
        return super().call(operation, args)


def test_usage_request_shape_and_refusals() -> None:
    request = bridge.capture_request({"resource": RESOURCE, "parameters": {}, "usage": "GENERATOR"})
    assert request == {"resource": RESOURCE, "parameters": {}, "usage": "GENERATOR"}
    with pytest.raises(ValueError, match="PROCEDURAL or GENERATOR"):
        bridge.capture_request({"resource": RESOURCE, "parameters": {}, "usage": "TEXTURE"})
    with pytest.raises(ValueError, match="exactly resource and parameters"):
        bridge.capture_request(
            {"resource": RESOURCE, "parameters": {}, "usage": "PROCEDURAL", "extra": 1}
        )


def test_procedural_usage_capture_records_the_destination_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = usage_context(tmp_path, generator=False)
    remote = UsageRemote(context, generator=False)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    request = bridge.capture_request(
        {"resource": RESOURCE, "parameters": {}, "usage": "PROCEDURAL"}
    )
    report = bridge.record(context, request, tmp_path)
    assert remote.created and remote.closed
    assert report["schema"] == "uzpainter/procedural-capture/3"
    assert report["usage"] == "PROCEDURAL"
    signature = report["signature"]
    assert signature["output"] == {
        "id": "value",
        "resolution": 256,
        "format": "f32",
        "colour_space": "raw",
        "channels": 1,
    }
    assert signature["inputs"] == {} and signature["seed"] == 7
    assert signature["settings"] == context["settings"]
    created = [args for operation, args in remote.calls if operation == "create"]
    assert created == [{"mesh_path": context["mesh_path"], "resolution": 256}]
    exports = [args for operation, args in remote.calls if operation == "export"]
    assert len(exports) == 2
    assert all(e["exportList"] == [{"rootPath": SET}] for e in exports)
    assert "mesh_maps" not in [operation for operation, _ in remote.calls]


def test_procedural_usage_capture_refuses_another_texture_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = usage_context(tmp_path, generator=False)
    context["resolution"] = 512
    remote = UsageRemote(context, generator=False)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    request = bridge.capture_request(
        {"resource": RESOURCE, "parameters": {}, "usage": "PROCEDURAL"}
    )
    with pytest.raises(ValueError, match="texture set or resolution"):
        bridge.record(context, request, tmp_path)
    assert remote.closed


def test_generator_usage_capture_binds_mesh_maps_and_names_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = usage_context(tmp_path, generator=True)
    remote = UsageRemote(context, generator=True)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    request = bridge.capture_request(
        {"resource": GENERATOR, "parameters": {"amount": 0.5}, "usage": "GENERATOR"}
    )
    report = bridge.record(context, request, tmp_path)
    assert remote.closed
    operations = [operation for operation, _ in remote.calls]
    assert operations.index("mesh_maps") < operations.index("configure_generator")
    assert ("mesh_maps", {"paths": context["mesh_maps"]}) in remote.calls
    signature = report["signature"]
    assert signature["inputs"] == SIGNATURE_INPUTS
    assert signature["output"]["id"] == "mask"
    assert signature["output"]["resolution"] == 256
    assert signature["seed"] == 3 and signature["params"]["amount"] == 0.5
    assert report["usage"] == "GENERATOR"


@pytest.mark.parametrize(
    "change",
    [
        "unbound map",
        "extra map",
        "second output",
        "override not applied",
        "base not black",
        "mask on base",
        "foreign effect",
        "low precision",
    ],
)
def test_generator_usage_capture_refuses_another_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str
) -> None:
    context = usage_context(tmp_path, generator=True)
    remote = UsageRemote(context, generator=True)
    observed = remote.observed
    if change == "unbound map":
        observed["mesh_maps"][SET]["AO"] = None
    elif change == "extra map":
        observed["mesh_maps"][SET]["Thickness"] = "resource://project1/t?version=1"
    elif change == "second output":
        observed["generator"]["outputs"] = ["mask", "other"]
    elif change == "override not applied":
        observed["generator"]["parameters"]["amount"] = 0.25
    elif change == "base not black":
        observed["layers"]["base"]["channels"]["User1"]["value"] = [0, 0, 1]
    elif change == "mask on base":
        observed["layers"]["base"]["mask"] = True
    elif change == "foreign effect":
        observed["layers"]["fill"]["mask_effects"] = [30, 31]
    else:
        observed["channel_formats"]["User0"] = "L16F"
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    request = bridge.capture_request(
        {"resource": GENERATOR, "parameters": {"amount": 0.5}, "usage": "GENERATOR"}
    )
    with pytest.raises(ValueError):
        bridge.record(context, request, tmp_path)
    assert remote.closed
    assert "export" not in [operation for operation, _ in remote.calls]


def test_generator_lookup_requires_the_generator_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = usage_context(tmp_path, generator=True)
    remote = UsageRemote(context, generator=False)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    request = bridge.capture_request(
        {"resource": GENERATOR, "parameters": {}, "usage": "GENERATOR"}
    )
    with pytest.raises(ValueError, match="generator ResourceID"):
        bridge.record(context, request, tmp_path)
    assert not remote.created


# Colour parameters (phase3.3_procedural-families item 2.16): the seam's tagged colour, read in Raw
# on the capture's split sources and in sRGB on the material source, matched by its components.
def colour(space: str, *components: float) -> dict[str, Any]:
    return {"type": "color", "working_space": space, "components": list(components), "alpha": None}


def test_colour_parameters_are_tagged_values() -> None:
    parameters = bridge.scalar_parameters({"tint": colour("Raw", 0.25, 1, 0.5)})
    assert parameters == {"tint": colour("Raw", 0.25, 1.0, 0.5)}
    assert isinstance(parameters["tint"]["components"][1], float)


@pytest.mark.parametrize(
    "value",
    [
        {**colour("Raw", 0.25, 0.5, 1.0), "alpha": 1.0},
        colour("Raw", 0.25, 0.5),
        colour("Raw", 0.25, True, 1.0),
        colour("Raw", 0.25, float("nan"), 1.0),
        colour("", 0.25, 0.5, 1.0),
        {**colour("Raw", 0.25, 0.5, 1.0), "type": "vector"},
        {**colour("Raw", 0.25, 0.5, 1.0), "extra": 1},
    ],
)
def test_malformed_colour_parameters_refuse(value: Any) -> None:
    with pytest.raises(ValueError, match="tagged colours"):
        bridge.scalar_parameters({"tint": value})


def test_requested_colour_is_srgb_or_raw() -> None:
    request = {"resource": RESOURCE, "parameters": {"tint": colour("sRGB", 0.25, 0.5, 1.0)}}
    assert bridge.capture_request(request)["parameters"]["tint"]["working_space"] == "sRGB"
    working = {"resource": RESOURCE, "parameters": {"tint": colour("Working", 0.25, 0.5, 1.0)}}
    with pytest.raises(ValueError, match="sRGB or Raw"):
        bridge.capture_request(working)


def test_requested_colour_reads_back_by_its_components() -> None:
    observed = readback()
    for source in observed["sources"]:
        source["parameters"]["tint"] = colour("Raw", 0.25, 0.5, 1.0)
    request = bridge.capture_request(
        {"resource": RESOURCE, "parameters": {"tint": colour("sRGB", 0.25, 0.5, 1.0)}}
    )
    assert bridge.validate_readback(deepcopy(observed), request)["parameters"]["tint"] == colour(
        "Raw", 0.25, 0.5, 1.0
    )
    request["parameters"]["tint"] = colour("sRGB", 0.25, 0.5, 0.75)
    with pytest.raises(ValueError, match="effective parameters"):
        bridge.validate_readback(observed, request)


def colour_contexts(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "split": {"output_mapping": REFUSED, "mask_output": REFUSED},
        "material": {
            "output_mapping": {"Height": "value"},
            "mask_output": "alpha",
            "active_channels": ["Height"],
            "parameters": material,
            "input_sources": {},
            "active_output": REFUSED,
        },
    }


def test_material_context_matches_a_colour_by_its_components() -> None:
    source = {
        "presets": [],
        "outputs": ["value"],
        "input_sources": {},
        "parameters": {"gain": 0.5, "tint": colour("Raw", 0.25, 0.5, 1.0)},
    }
    material = {"gain": 0.5, "tint": colour("sRGB", 0.25, 0.5, 1.0)}
    _, contexts = bridge.check_contexts(colour_contexts(material), source, {})
    assert contexts["material"]["parameters"]["tint"]["working_space"] == "sRGB"
    for other in (
        {"gain": 0.5, "tint": colour("sRGB", 0.25, 0.5, 0.75)},
        {"gain": 0.5, "tint": 0.25},
        {"gain": 0.5},
    ):
        with pytest.raises(ValueError, match="material source"):
            bridge.check_contexts(colour_contexts(other), source, {})


class FakeSpace:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeColor:
    def __init__(self, r: float, g: float, b: float, space: Any) -> None:
        self.value_raw = (r, g, b)
        self.color_space = space


def test_painter_side_tags_a_colour_and_sets_it_back_as_a_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_globals, modules = painter_module(monkeypatch)
    spaces = ModuleType("GenericColorSpace")
    spaces.Raw = FakeSpace("Raw")  # type: ignore[attr-defined]
    spaces.sRGB = FakeSpace("sRGB")  # type: ignore[attr-defined]
    modules["colormanagement"].Color = FakeColor
    modules["colormanagement"].GenericColorSpace = spaces
    source = MagicMock()
    source.get_parameters.return_value = {
        "gain": 0.5,
        "tint": FakeColor(0.25, 0.5, 1.0, spaces.sRGB),
    }
    tagged = module_globals["typed_parameters"](source)
    assert tagged == {"gain": 0.5, "tint": colour("sRGB", 0.25, 0.5, 1.0)}
    back = module_globals["painter_parameters"](tagged)
    assert back["gain"] == 0.5
    assert isinstance(back["tint"], FakeColor)
    assert back["tint"].value_raw == (0.25, 0.5, 1.0) and back["tint"].color_space is spaces.sRGB
    prop = MagicMock()
    prop.value.return_value = FakeColor(0.25, 0.5, 1.0, spaces.Raw)
    prop.name.return_value = "tint"
    prop.enum_values.return_value = {}
    prop.properties.return_value = {}
    assert module_globals["described"](prop)["value"] == colour("Raw", 0.25, 0.5, 1.0)
    unnamed = FakeColor(0.25, 0.5, 1.0, None)
    with pytest.raises(ValueError, match="named colour space"):
        module_globals["typed_value"](unnamed)


class MaterialRemote(MultiRemote):
    """`MultiRemote` on the destination's texture set at 256 px (item 2.16)."""

    def __init__(self, mesh: str, sets: list[dict[str, Any]]) -> None:
        super().__init__(mesh)
        self.sets = sets
        self.created_with: list[Any] = []
        self.exported_sets: list[Any] = []

    def state(self) -> dict[str, Any]:
        observed = super().state()
        observed["sets"] = self.sets
        return observed

    def call(self, operation: str, args: dict[str, Any] | None = None) -> Any:
        if operation == "create":
            self.created_with.append(args)
        if operation == "export":
            assert args is not None
            self.exported_sets.append(args["exportList"])
        return super().call(operation, args)


def material_request(tmp_path: Path) -> dict[str, Any]:
    request = dict(multi_request(tmp_path))
    request["usage"] = "MATERIAL"
    return bridge.capture_request(request)


def test_material_usage_request_shape_and_refusals(tmp_path: Path) -> None:
    request = material_request(tmp_path)
    assert request["usage"] == "MATERIAL" and request["preset"] == "authored preset"
    body: dict[str, Any] = {"resource": RESOURCE, "parameters": {}, "preset": None, "inputs": {}}
    for usage in ("PROCEDURAL", "GENERATOR", "material"):
        with pytest.raises(ValueError, match="MATERIAL"):
            bridge.capture_request({**body, "usage": usage})
    with pytest.raises(ValueError, match="PROCEDURAL or GENERATOR"):
        bridge.capture_request({"resource": RESOURCE, "parameters": {}, "usage": "MATERIAL"})


def test_material_usage_capture_records_the_destination_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sets = [{"name": "destination", "resolution": [256, 256], "has_uv_tiles": False}]
    remote = MaterialRemote(str(tmp_path / "mesh.obj"), sets)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    context = {
        "mesh_path": remote.mesh,
        "project_uuid": "authored",
        "revision": 5,
        "settings": {},
        "texture_set": "destination",
        "resolution": 256,
    }
    work = tmp_path / "work"
    work.mkdir()
    report = bridge.record(context, material_request(tmp_path), work)
    assert report["schema"] == "uzpainter/procedural-capture/2" and report["usage"] == "MATERIAL"
    assert {c["signature"]["output"]["resolution"] for c in report["captures"]} == {256}
    assert remote.created_with == [{"mesh_path": remote.mesh, "resolution": 256}]
    assert remote.exported_sets and all(
        e == [{"rootPath": "destination"}] for e in remote.exported_sets
    )
    assert remote.closed
    remote = MaterialRemote(str(tmp_path / "mesh.obj"), sets)
    monkeypatch.setattr(bridge, "Remote", lambda: remote)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="texture set or resolution"):
        bridge.record({**context, "resolution": 512}, material_request(tmp_path), other)

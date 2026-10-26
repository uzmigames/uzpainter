"""Public input coverage and literal colour-space transport, without Painter or oracle data."""

from __future__ import annotations

import ast
import hashlib
import json
import struct
import zlib
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tools.parity.recorder import probes as recorder
from tools.parity.recorder import texture
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.capture import StorageFormat
from tools.parity.recorder.job import EXPORT, Step
from tools.parity.recorder.output import write_run
from tools.parity.recorder.probes import (
    PAINTER_PROBES,
    check_input_arg,
    manifest_symbol_problems,
    probe_constants,
    probe_job_from_manifest,
)
from tools.parity.recorder.session import PainterIdentity, RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors
from tools.parity.tier0_semantics import ocio16_bitmap_control as control
from tools.parity.tier0_semantics import ocio16_raw_readout_control as raw_control
from tools.parity.tier0_semantics import recording_requests as rr


def png_samples(data: bytes) -> tuple[int, int, list[tuple[int, ...]]]:
    width, height, bits, colour = struct.unpack(">IIBB", data[16:26])
    assert (width, height, colour) == (256, 256, 2)
    packed = bytearray()
    offset = 8
    while offset < len(data):
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        if data[offset + 4 : offset + 8] == b"IDAT":
            packed.extend(data[offset + 8 : offset + 8 + size])
        offset += size + 12
    raw = zlib.decompress(packed)
    stride = 256 * 3 * (bits // 8) + 1
    samples: list[tuple[int, ...]] = []
    for row in range(256):
        assert raw[row * stride] == 0
        values = struct.unpack(
            ">" + ("H" if bits == 16 else "B") * 768, raw[row * stride + 1 : (row + 1) * stride]
        )
        samples.extend(tuple(values[i : i + 3]) for i in range(0, 768, 3))
    return bits, colour, samples


def test_public_inputs_exact_permutations_and_rgb8_control() -> None:
    base = (REPO_ROOT / rr.fixture("field-a")[1]).read_bytes()
    bits, _, samples = png_samples(base)
    assert bits == 16
    for order, full_channel in (("brg", 0), ("gbr", 1)):
        generated = control.permuted_field(order)
        path = REPO_ROOT / f"parity/fixtures/tier0-semantics/bitmaps/field-a-{order}.png"
        assert path.read_bytes() == generated
        bits, _, permuted = png_samples(generated)
        assert bits == 16
        indices = tuple("rgb".index(c) for c in order)
        assert permuted == [tuple(pixel[i] for i in indices) for pixel in samples]
        assert {pixel[full_channel] for pixel in permuted} == set(range(65536))
    assert {pixel[2] for pixel in samples} == set(range(65536))
    bits, _, rgb8 = png_samples((REPO_ROOT / rr.fixture("srgb8-ramp")[1]).read_bytes())
    assert bits == 8 and len(rgb8) == 65536


@pytest.mark.parametrize("source", control.STATES)
def test_request_closed_matrix_and_persisted_identity(source: str) -> None:
    data = control.request(source)
    assert validation_errors(data, Schema.GOLDEN_PUBLIC) == []
    assert manifest_symbol_problems(data) == []
    assert data["private_records"] == data["expectations"] == []
    path = rr.request_root(REPO_ROOT) / "tier0/api-probes" / f"{control.request_name(source)}.json"
    assert json.loads(path.read_text()) == data
    assert {i["input_id"] for i in data["inputs"]} == {
        "plane",
        *([] if source == "uniform" else [source]),
    }
    for item in data["inputs"]:
        assert hashlib.sha256((REPO_ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    job = probe_job_from_manifest(data)
    assert job.create.args["default_texture_resolution"] == 256
    assert len(job.probe_steps) == 1
    getter = job.probe_steps[0]
    assert getter.call == (control.GET_SOURCE if source == "uniform" else control.GET_SPACE)
    if source != "uniform":
        assert getter.args["typed"] is True
    assert next(p.args for p in job.state_steps if p.call == control.SET_PROJECTION) == {
        "node_step": getter.args["node_step"],
        **control.UV,
    }
    setters = [p for p in job.state_steps if p.call == control.SET_SPACE]
    assert len(setters) == (0 if source == "uniform" else 1)
    assert all(
        p.args["color_space_type"] == "str" and p.args["color_space"] == "sRGB" for p in setters
    )
    assert len(job.exports) == 3
    assert job.keyed_export_steps == frozenset(e.step for e in job.exports)
    for export, (fmt, depth) in zip(job.exports, control.FORMATS, strict=True):
        config = export.config(Path("unused"), ["uzp_plane"])
        assert config["exportParameters"] == [
            {
                "parameters": {
                    "fileFormat": fmt,
                    "bitDepth": str(depth),
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ]
        channels = config["exportPresets"][0]["maps"][0]["channels"]
        assert [(c["srcMapType"], c["srcMapName"], c["srcChannel"]) for c in channels] == [
            ("documentMap", "basecolor", c) for c in "RGB"
        ]
    assert [item for item in data["applied_settings"] if item["name"] == "OCIO"] == [
        rr.OCIO_SETTING
    ]


def dispatcher() -> tuple[Any, dict[str, Any]]:
    tree = ast.parse(PAINTER_PROBES.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "edit")
    namespace = {
        **probe_constants(),
        "Any": Any,
        "substance_painter": MagicMock(),
        "fresh": MagicMock(),
        "member": MagicMock(return_value=object()),
        "channel_arg": lambda args: args["channel"],
        "BITMAP_COLOR_SPACES": {},
        "OWN_PROJECT_CREATION": {},
        "P22B_CALLS": (),
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(PAINTER_PROBES), "exec"),
        namespace,
    )
    return namespace["edit"], namespace


@pytest.mark.parametrize("state", raw_control.STATES)
@pytest.mark.parametrize("exports", [False, True])
def test_raw_v2_resolves_actual_probe_enum_table(state: str, exports: bool) -> None:
    class GenericColorSpace(Enum):
        Raw = "authored Raw enum"

    edit, namespace = dispatcher()
    namespace["substance_painter"].colormanagement.GenericColorSpace = GenericColorSpace
    probe_tree = ast.parse(PAINTER_PROBES.read_text())
    table = next(
        node
        for node in probe_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "BITMAP_COLOR_SPACES"
            for target in node.targets
        )
    )
    side = PAINTER_PROBES.with_name("painter_side.py")
    member = next(
        node
        for node in ast.parse(side.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == "member"
    )
    exec(
        compile(ast.Module(body=[table, member], type_ignores=[]), str(PAINTER_PROBES), "exec"),
        namespace,
    )
    job = probe_job_from_manifest(raw_control.request(state, exports=exports))
    step = next(
        step for step in job.state_steps if step.call == raw_control.BITMAP + "set_color_space"
    )
    edit(step.step, step.call, dict(step.args), {})
    setter = namespace["fresh"].return_value.get_source.return_value.set_color_space
    setter.assert_called_once_with(GenericColorSpace.Raw)
    setter.reset_mock()
    with pytest.raises(ValueError, match="color space 'Raw' is not a documented member"):
        edit(step.step, step.call, {**step.args, "color_space": "Raw"}, {})
    setter.assert_not_called()


@pytest.mark.parametrize("literal", [False, True])
def test_dispatcher_preserves_string_and_enum_identity(literal: bool) -> None:
    edit, namespace = dispatcher()
    args = {
        "node_step": 1,
        "channel": "BaseColor",
        "color_space": "sRGB" if literal else "GenericColorSpace.sRGB",
    }
    if literal:
        args["color_space_type"] = "str"
    check_input_arg(Step(2, control.SET_SPACE, args), {})
    edit(2, control.SET_SPACE, args, {})
    setter = namespace["fresh"].return_value.get_source.return_value.set_color_space
    if literal:
        setter.assert_called_once_with("sRGB")
        namespace["member"].assert_not_called()
    else:
        setter.assert_called_once_with(namespace["member"].return_value)
        namespace["member"].assert_called_once_with({}, "color space", "GenericColorSpace.sRGB")


@pytest.mark.parametrize(
    "change",
    [
        {"color_space": "Raw"},
        {"color_space_type": "GenericColorSpace"},
        {"color_space_type": None},
        {"node_step": True},
        {"node_step": 0},
        {"channel": None},
        {"channel": ""},
        {"unexpected": True},
    ],
)
def test_invalid_literal_refuses_before_painter(change: dict[str, Any]) -> None:
    args = {
        "node_step": 1,
        "channel": "BaseColor",
        "color_space": "sRGB",
        "color_space_type": "str",
        **change,
    }
    with pytest.raises(RecorderError):
        check_input_arg(Step(2, control.SET_SPACE, args), {})
    edit, namespace = dispatcher()
    with pytest.raises(ValueError):
        edit(2, control.SET_SPACE, args, {})
    namespace["fresh"].assert_not_called()
    namespace["substance_painter"].assert_not_called()


@pytest.mark.parametrize("flag", [False, 1, "true", None])
def test_export_key_flag_requires_literal_true(flag: Any) -> None:
    data = control.request()
    data["instruction_sequence"]["steps"][-1]["args"]["key_by_step"] = flag
    with pytest.raises(RecorderError, match="key_by_step"):
        probe_job_from_manifest(data)


@pytest.mark.parametrize("position", ["create", "getter", "probe_export"])
def test_export_key_flag_refuses_non_final_positions(position: str) -> None:
    data = control.request()
    steps = data["instruction_sequence"]["steps"]
    if position == "probe_export":
        steps[-3]["args"]["probe"] = True
    else:
        step = (
            steps[0]
            if position == "create"
            else next(s for s in steps if s["call"] == control.GET_SPACE)
        )
        step["args"]["key_by_step"] = True
    with pytest.raises(RecorderError, match="key_by_step"):
        probe_job_from_manifest(data)


@pytest.mark.parametrize("stable_repeats", [False, True])
def test_pipeline_retains_all_formats_across_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stable_repeats: bool,
) -> None:
    """Mock only Painter/file-format inspection; real fences, hashes and inbox copying run."""
    identity = PainterIdentity("12.2.0", (12, 2, 0), "1.1.20", "authored-mock", {"mode": "ocio"})
    counts = {"r1": 0, "r2": 0}
    written: dict[Path, bytes] = {}
    calls: list[str] = []
    context = {"source": "", "recording": "r1"}
    template: dict[str, Any] = {"texture_sets": {"uzp_plane": {"stacks": {"": {}}}}}

    def measured(path: Path) -> StorageFormat:
        _, _, fmt, depth = path.read_text().split("|")
        return StorageFormat(
            fmt, "float" if fmt == "exr" else "uint", int(depth.removesuffix("f")), 3, "linear"
        )

    monkeypatch.setattr(texture, "measure_storage_format", measured)
    for source in control.STATES:
        data = control.request(source)
        job = probe_job_from_manifest(data)
        recordings = []
        blobs = []
        current = "r1"
        context["source"] = source

        def call(operation: str, **args: Any) -> dict[str, Any]:
            calls.append(operation)
            if operation == "template_capture":
                return template
            if operation == "probe_step":
                assert args["call"] == (
                    control.GET_SOURCE if context["source"] == "uniform" else control.GET_SPACE
                )
                return {
                    "value": {"class": "str", "name": "sRGB"}
                    if context["source"] != "uniform"
                    else [0, 0.5, 1]
                }
            assert operation == "export_textures"
            config = args["config"]
            parameters = config["exportParameters"][0]["parameters"]
            fmt, depth = parameters["fileFormat"], parameters["bitDepth"]
            path = Path(config["exportPath"]) / f"uzp_plane_basecolor.{fmt}"
            assert path not in written
            repeat = "stable" if stable_repeats else context["recording"]
            payload = f"{context['source']}|{repeat}|{fmt}|{depth}".encode()
            path.write_bytes(payload)
            written[path] = payload
            counts[context["recording"]] += 1
            return {
                "status": "Success",
                "textures": [{"texture_set": "uzp_plane", "stack": "", "files": [str(path)]}],
            }

        session = MagicMock()
        session.call.side_effect = call
        for current, condition in (("r1", "same_session"), ("r2", "after_save_reopen")):
            context["recording"] = current
            calls.clear()
            recording, files = recorder.record_probes(
                session,
                job,
                identity,
                tmp_path / "work" / source / current,
                current,
                condition,
                {},
                [],
                lambda: datetime(2026, 10, 25, tzinfo=UTC),
                {},
            )
            assert calls == ["template_capture", "probe_step", *(["export_textures"] * 3)]
            outputs = [o for o in recording["outputs"] if o["kind"] == "exported_map"]
            assert len(outputs) == len(files) == 3
            assert len({o["output_id"] for o in outputs}) == 3
            assert len({p.parent for p in files}) == 3
            assert files[0].name == files[1].name
            recordings.append(recording)
            blobs.extend(files)
        assert len(set(blobs)) == 6
        key = recorder.golden_key(job, identity, {}, {"mode": "ocio"})
        record = recorder.private_record(job, key, recordings)
        assert record_problems(record) == []
        run = write_run(tmp_path / "inbox", record, blobs, data, identity.session_id)
        refs = json.loads((run / "manifest.json").read_text())["private_records"]
        assert len(refs) == 7
        assert len({ref["record_id"] for ref in refs}) == 7
        assert len(list((run / "blobs").iterdir())) == (3 if stable_repeats else 6)
        for path in blobs:
            payload = written[path]
            assert path.read_bytes() == payload
            assert (run / "blobs" / hashlib.sha256(payload).hexdigest()).read_bytes() == payload

        # The old no-flag path keeps its original output id, with no new suffix.
        if source == "field-a":
            legacy = replace(job, exports=job.exports[:1], keyed_export_steps=frozenset())
            recording, _ = recorder.record_probes(
                session,
                legacy,
                identity,
                tmp_path / "legacy",
                "legacy",
                "same_session",
                {},
                [],
                lambda: datetime(2026, 10, 25, tzinfo=UTC),
                {},
            )
            assert (
                next(o["output_id"] for o in recording["outputs"] if o["kind"] == "exported_map")
                == "uzp_plane/basecolor"
            )
            counts[current] -= 1
    assert counts == {"r1": 15, "r2": 15}


@pytest.mark.parametrize("marker", ["color_space_type", "key_by_step"])
@pytest.mark.parametrize("location", ["lifecycle", "final_export"])
def test_marker_cannot_bypass_preflight(marker: str, location: str) -> None:
    data = control.request()
    steps = data["instruction_sequence"]["steps"]
    if location == "lifecycle":
        steps[0]["call"] = recorder.EVENT_CONNECT
        step = steps[0]
    else:
        step = steps[-1]
    step["args"][marker] = "str" if marker == "color_space_type" else 1
    with pytest.raises(RecorderError, match=marker):
        probe_job_from_manifest(data)


@pytest.mark.parametrize("source", control.NATIVE_BASELINES)
def test_native_plan_preserves_source_and_authored_request(source: str) -> None:
    authored = control.request(source)
    before = deepcopy(authored)
    plan = control.native_baseline(
        authored, source, configuration_sha256=PAINTER_OCIO_CONFIG_SHA256
    )
    assert authored == before
    assert len(plan.exports) == 3
    steps = plan.manifest["instruction_sequence"]["steps"]
    assert not any(
        s["call"] in (control.SET_SPACE, control.GET_SPACE, control.GET_SOURCE, EXPORT)
        for s in steps
    )
    args = next(s["args"] for s in steps if s["call"] == ps.SET_SOURCE)
    if source == "uniform":
        assert args["color_space"] == "Working"
        assert args["color"] == [0.0, 0.5, 1.0]
    else:
        assert args["color_space"] == "OcioColorSpace.sRGB"


@pytest.mark.parametrize("source", ["field-a", "field-a-brg", "field-a-gbr"])
def test_native_plan_refuses_rgb16(source: str) -> None:
    with pytest.raises(ValueError, match="outside"):
        control.native_baseline(
            control.request(source), source, configuration_sha256=PAINTER_OCIO_CONFIG_SHA256
        )


@pytest.mark.parametrize(
    "field",
    [
        "golden_id",
        "inputs",
        "instruction_sequence",
        "applied_settings",
        "software",
        "private_records",
        "expectations",
    ],
)
def test_native_plan_refuses_contract_tampering(field: str) -> None:
    authored = control.request("uniform")
    authored[field] = None
    with pytest.raises(ValueError):
        control.native_baseline(
            authored, "uniform", configuration_sha256=PAINTER_OCIO_CONFIG_SHA256
        )


def test_native_plan_refuses_profile() -> None:
    with pytest.raises(ValueError, match="outside"):
        control.native_baseline(
            control.request("uniform"), "uniform", configuration_sha256="0" * 64
        )


@pytest.mark.parametrize("source", control.RGB16_CANDIDATES)
def test_rgb16_candidate_keeps_ocio_authored_input(source: str) -> None:
    authored = control.request(source)
    before = deepcopy(authored)
    plan = control.native_rgb16_candidate(
        authored, source, configuration_sha256=PAINTER_OCIO_CONFIG_SHA256
    )
    assert authored == before and len(plan.exports) == 3
    steps = plan.manifest["instruction_sequence"]["steps"]
    bitmap = next(s["args"] for s in steps if s["call"] == ps.SET_SOURCE)
    assert bitmap["color_space"] == "OcioColorSpace.sRGB"
    assert bitmap["resource_step"] > 0 and "color" not in bitmap
    assert png_samples(plan.inputs[source].read_bytes())[0] == 16
    with pytest.raises(ValueError, match="outside"):
        control.native_baseline(authored, source, configuration_sha256=PAINTER_OCIO_CONFIG_SHA256)


@pytest.mark.parametrize("source", control.NATIVE_BASELINES)
def test_rgb16_candidate_refuses_baselines(source: str) -> None:
    with pytest.raises(ValueError, match="outside"):
        control.native_rgb16_candidate(
            control.request(source), source, configuration_sha256=PAINTER_OCIO_CONFIG_SHA256
        )


@pytest.mark.parametrize("change", ["profile", "raw", "depth", "private"])
def test_rgb16_candidate_refuses_changed_contract(change: str) -> None:
    authored = control.request("field-a")
    profile = PAINTER_OCIO_CONFIG_SHA256
    if change == "profile":
        profile = "0" * 64
    elif change == "private":
        authored["private_records"] = [{"unexpected": True}]
    else:
        steps = authored["instruction_sequence"]["steps"]
        if change == "raw":
            next(s for s in steps if s["call"] == control.SET_SPACE)["args"]["color_space"] = "Raw"
        else:
            steps[-1]["args"]["bit_depth"] = "16f"
    with pytest.raises(ValueError):
        control.native_rgb16_candidate(authored, "field-a", configuration_sha256=profile)

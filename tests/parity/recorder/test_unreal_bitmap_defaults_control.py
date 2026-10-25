"""Authored transport controls; fake colour spaces assert no Painter default."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import Step
from tools.parity.recorder.probes import (
    ProbeSession,
    ProbeStep,
    check_input_arg,
    manifest_symbol_problems,
    probe_job_from_manifest,
    record_probe_golden,
    run_step,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics import unreal_preset_control
from tools.parity.tier0_semantics.unreal_bitmap_defaults_control import (
    GET_COLOR_SPACE,
    GET_SOURCE,
    NAME,
    request,
)


@pytest.mark.parametrize("ocio", [False, True])
def test_request_preserves_r322_setup_and_complete_authored_dependencies(ocio: bool) -> None:
    original = unreal_preset_control.request(ocio)
    before = json.dumps(original.sequence.steps, sort_keys=True)
    data = request(ocio)
    assert validation_errors(data, Schema.GOLDEN_PUBLIC) == []
    assert manifest_symbol_problems(data) == []
    steps = data["instruction_sequence"]["steps"]
    boundary = next(
        i for i, step in enumerate(original.sequence.steps) if step["call"] == rr.PREDEFINED_PRESETS
    )
    assert steps[:boundary] == original.sequence.steps[:boundary]
    assert json.dumps(unreal_preset_control.request(ocio).sequence.steps, sort_keys=True) == before
    source_steps = [step for step in steps[:boundary] if step["call"] == ps.SET_SOURCE]
    reads = steps[boundary:]
    assert len(source_steps) == 9
    assert len(reads) == 18
    for source, identity, space in zip(source_steps, reads[::2], reads[1::2], strict=True):
        args = {key: source["args"][key] for key in ("node_step", "channel")}
        assert identity["call"] == GET_SOURCE and identity["args"] == args
        assert space["call"] == GET_COLOR_SPACE and space["args"] == {**args, "typed": True}
    job = probe_job_from_manifest(data)
    assert len(job.probe_steps) == 18
    assert all(step.call in {GET_SOURCE, GET_COLOR_SPACE} for step in job.probe_steps)
    inputs = {source["input_id"]: source for source in data["inputs"]}
    required = {
        step["args"][key]
        for step in steps[:boundary]
        for key in ("mesh", "input")
        if key in step["args"]
    }
    assert set(inputs) == required
    imported = {
        step["step"]: step["args"]["input"] for step in steps if step["call"] == ps.IMPORT_RESOURCE
    }
    for step in steps:
        if "resource_step" in step["args"]:
            assert imported[step["args"]["resource_step"]] in inputs
    assert "normal-b" in inputs
    for source in inputs.values():
        assert (
            hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
            == source["sha256"]
        )
    base = manifest_root(current_envelope())
    r322 = json.loads((base / "tier0/semantics" / f"{original.name}.json").read_text())
    assert {source["input_id"]: source["sha256"] for source in data["inputs"]} == {
        source["input_id"]: source["sha256"]
        for source in r322["inputs"]
        if source["input_id"] in required
    }
    assert steps[:boundary] == r322["instruction_sequence"]["steps"][:boundary]
    path = base.parent / "requests/tier0/api-probes" / f"{NAME}{'ocio' if ocio else 'legacy'}.json"
    assert json.loads(path.read_text()) == data
    assert data["private_records"] == [] and data["expectations"] == []
    assert (
        data["applied_settings"]
        == rr.request_manifest(
            original, {key: "0" * 64 for key in original.inputs}, current_envelope()
        )["applied_settings"]
    )


@pytest.mark.parametrize("typed", [False, True])
@pytest.mark.parametrize("string_space", [False, True])
def test_fresh_typed_and_legacy_getters_survive_reopen(
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    typed: bool,
    string_space: bool,
) -> None:
    monkeypatch.delenv("OCIO", raising=False)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    monkeypatch.setattr(fake.ChannelType, "Opacity", fake.ChannelType.User8, raising=False)
    monkeypatch.setattr(fake.ChannelType, "EmissionColor", fake.ChannelType.Emissive, raising=False)
    name = "uzp_recorder_fake_probe_painter"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name("fake_probe_painter.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    world = sys.modules[name].ProbeWorld()
    world.version, world.version_info = "12.2.0", (12, 2, 0)
    world.texture_set = unreal_preset_control.MATERIAL
    template = tmp_path / rr.ALPHA_BLEND
    template.parent.mkdir(parents=True)
    template.write_text("authored fake template\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[name], "APPLICATION_SHELF_PATH", str(tmp_path))
    world.template_channels[template.stem] = {
        **world.default_channels,
        fake.ChannelType.Opacity: fake.ChannelFormat.L8,
        fake.ChannelType.EmissionColor: fake.ChannelFormat.sRGB8,
    }
    source = world.modules["substance_painter.source"]
    value = "sRGB" if string_space else fake.GenericColorSpace.sRGB
    monkeypatch.setattr(source.SourceBitmap, "get_color_space", lambda self: value)
    layerstack = world.modules["substance_painter.layerstack"]
    original_fresh = layerstack.get_node_by_uid
    handles: list[Any] = []

    def fresh(uid: int) -> Any:
        node = original_fresh(uid)
        handles.append(node)
        return node

    monkeypatch.setattr(layerstack, "get_node_by_uid", fresh)
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda _: world.modules["substance_painter.project"].is_busy(),
        allowed_builds=lambda: frozenset({"12.2.0+js-api.1.1.20"}),
    )
    data = request()
    if not typed:
        for step in data["instruction_sequence"]["steps"]:
            step["args"].pop("typed", None)
    run = record_probe_golden(
        session, probe_job_from_manifest(data), tmp_path / "work", tmp_path / "inbox"
    )
    record = json.loads((run / "record.json").read_text())
    assert record_problems(record) == []
    assert [r["condition"] for r in record["recordings"]] == ["same_session", "after_save_reopen"]
    expected: Any = (
        {"class": "str" if string_space else "GenericColorSpace", "name": "sRGB"}
        if typed
        else "sRGB"
    )
    for recording in record["recordings"]:
        outputs = [
            o
            for o in recording["outputs"]
            if o["kind"] == "api_readback" and o.get("call") in {GET_SOURCE, GET_COLOR_SPACE}
        ]
        assert len(outputs) == 18
        assert not [o for o in outputs if "raised" in o]
        assert [o["value"] for o in outputs if o["call"] == GET_COLOR_SPACE] == [expected] * 9
        assert all("bitmap" in o["value"] for o in outputs if o["call"] == GET_SOURCE)
    assert len(handles) >= 36
    assert len({id(node) for node in handles}) == len(handles)


@pytest.mark.parametrize("key", ["image", "input"])
def test_import_alias_resolves_existing_transport_without_rewriting_args(key: str) -> None:
    args = {key: "authored", "usage": "TEXTURE"}
    path = REPO_ROOT / "parity/fixtures/tier0-semantics/bitmaps/field-a.png"
    check_input_arg(Step(1, ps.IMPORT_RESOURCE, args), {"authored": path})
    session = MagicMock()
    step = ProbeStep(1, ps.IMPORT_RESOURCE, args, False, True)
    run_step(session, step, {"authored": path}, REPO_ROOT)
    session.call.assert_called_once_with(
        "probe_step",
        step=1,
        call=ps.IMPORT_RESOURCE,
        args=args,
        resolved={"image": path.as_posix()},
    )
    assert args == {key: "authored", "usage": "TEXTURE"}


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"image": "x", "input": "x"},
        {"image": "x", "input": "y"},
        {"image": "unknown"},
        {"input": "unknown"},
    ],
)
def test_import_alias_rejects_missing_ambiguous_and_unknown_references(
    args: dict[str, Any],
) -> None:
    with pytest.raises(RecorderError):
        check_input_arg(Step(1, ps.IMPORT_RESOURCE, args), {"x": REPO_ROOT, "y": REPO_ROOT})

"""Texture-job captures and per-set resolutions against a fake Painter (recordings R2, R6, R7):
`set_resolutions` of one named texture set (width and height may differ), and the export-preset
and bitmap colour-space captures, recorded in both recordings like export probes."""

from __future__ import annotations

import copy
import json
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import (
    LIST_COLOR_SPACES,
    LIST_PREDEFINED_PRESETS,
    LIST_RESOURCE_PRESETS,
    PREDEFINED_OUTPUT_MAPS,
    RESOURCE_OUTPUT_MAPS,
    Job,
    job_from_manifest,
)
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import record_texture_golden
from tools.parity.recorder.vocabulary import SET_RESOLUTIONS

MakeSession = Callable[[Any], PainterSession]

SECOND_SET = "uzp_second"
RESOURCE_PRESET = "resource://starter_assets/Fake Engine Preset"


def record_of(run: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((run / "record.json").read_text(encoding="utf-8"))
    return record


def by_id(record: dict[str, Any], index: int) -> dict[str, dict[str, Any]]:
    return {o["output_id"]: o for o in record["recordings"][index]["outputs"]}


def with_steps(
    sample_job: Job, extra: list[dict[str, Any]], keep_export: bool = True
) -> dict[str, Any]:
    """The sample manifest with `extra` steps appended after its state steps; the sample's
    export step stays last when `keep_export`."""
    manifest = copy.deepcopy(sample_job.manifest)
    steps = manifest["instruction_sequence"]["steps"]
    export = steps.pop()
    steps += [copy.deepcopy(item) for item in extra]
    if keep_export:
        steps.append(export)
    for number, item in enumerate(steps, start=1):
        item["step"] = number
    return manifest


def two_set_world(fake: types.ModuleType) -> Any:
    world = fake.FakeWorld()
    world.other_texture_sets = [SECOND_SET]
    return world


def resolutions(record: dict[str, Any], index: int) -> dict[str, Any]:
    template = by_id(record, index)["template/texture-sets"]["values"]["texture_sets"]
    return {name: info["resolution"] for name, info in template.items()}


def test_a_named_texture_set_alone_takes_a_non_square_resolution(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    step = {
        "call": SET_RESOLUTIONS,
        "args": {"width": 256, "height": 128, "texture_set": SECOND_SET},
    }
    job = job_from_manifest(with_steps(sample_job, [step]))
    record = record_of(record_texture_golden(make_session(two_set_world(fake)), job, work, inbox))
    for index in (0, 1):
        assert resolutions(record, index) == {"uzp_plane": [256, 256], SECOND_SET: [256, 128]}
        outputs = by_id(record, index)
        assert outputs[f"readback/get_resolution/{SECOND_SET}"]["value"] == [256, 128]
        assert outputs["readback/get_resolution/uzp_plane"]["value"] == [256, 256]


def test_without_a_texture_set_every_set_takes_the_resolution(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    step = {"call": SET_RESOLUTIONS, "args": {"width": 512, "height": 128}}
    job = job_from_manifest(with_steps(sample_job, [step]))
    record = record_of(record_texture_golden(make_session(two_set_world(fake)), job, work, inbox))
    for index in (0, 1):
        assert resolutions(record, index) == {"uzp_plane": [512, 128], SECOND_SET: [512, 128]}


BITMAP_STEPS = [
    {
        "call": "substance_painter.resource.import_project_resource",
        "args": {"input": "plane", "usage": "TEXTURE"},
    },
    {
        "call": "substance_painter.layerstack.FillLayerNode.set_source",
        "args": {"node_step": 2, "channel": "BaseColor", "resource_step": 10, "color_space": "Raw"},
    },
]

FAKE_MAPS = [
    {
        "fileName": f"$textureSet_{name}",
        "channels": [
            {
                "destChannel": "L",
                "srcChannel": "L",
                "srcMapType": "documentMap",
                "srcMapName": name.lower(),
            }
        ],
    }
    for name in ("BaseColor", "Height", "Metallic", "Normal", "Roughness")
]


def capture_job(sample_job: Job) -> Job:
    """Steps 1-11 set up a bitmap on node 2; captures 12-22 interleave with the export (13)."""
    manifest = with_steps(sample_job, BITMAP_STEPS, keep_export=False)
    steps = manifest["instruction_sequence"]["steps"]
    export = copy.deepcopy(sample_job.manifest["instruction_sequence"]["steps"][-1])
    for item in [
        {"call": LIST_PREDEFINED_PRESETS},
        export,
        {"call": LIST_RESOURCE_PRESETS, "args": {}},
        {
            "call": PREDEFINED_OUTPUT_MAPS,
            "args": {"preset": "PBR Metallic Roughness", "texture_set": "uzp_plane"},
        },
        {"call": RESOURCE_OUTPUT_MAPS, "args": {"preset": RESOURCE_PRESET}},
        {"call": LIST_COLOR_SPACES, "args": {"node_step": 2, "channel": "BaseColor"}},
        {
            "call": PREDEFINED_OUTPUT_MAPS,
            "args": {"preset": "No Such Preset", "texture_set": "uzp_plane"},
        },
        {"call": RESOURCE_OUTPUT_MAPS, "args": {"preset": "resource://starter_assets/Absent"}},
        {"call": LIST_COLOR_SPACES, "args": {"node_step": 5, "channel": "BaseColor"}},
        {
            "call": PREDEFINED_OUTPUT_MAPS,
            "args": {"preset": "PBR Metallic Roughness", "texture_set": "no_such_set"},
        },
        {"call": PREDEFINED_OUTPUT_MAPS, "args": {"texture_set": "uzp_plane"}},
    ]:
        steps.append({**item, "step": len(steps) + 1})
    return job_from_manifest(manifest)


def test_preset_and_colour_space_captures_are_recorded_in_both_recordings(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    job = capture_job(sample_job)
    assert [s.step for s in job.api_captures] == [12, 14, 15, 16, 17, 18, 19, 20, 21, 22]
    assert [e.step for e in job.exports] == [13]
    record = record_of(record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox))
    for index in (0, 1):
        ids = [o["output_id"] for o in record["recordings"][index]["outputs"]]
        captured = [i for i in ids if i.startswith(("presets/", "color-spaces/", "uzp_plane/"))]
        assert captured == [
            "presets/s12",
            "uzp_plane/basecolor",
            "presets/s14",
            "presets/s15",
            "presets/s16",
            "color-spaces/s17",
            "presets/s18",
            "presets/s19",
            "color-spaces/s20",
            "presets/s21",
            "presets/s22",
        ]
        outputs = by_id(record, index)
        assert {outputs[i]["kind"] for i in captured if not i.startswith("uzp_plane/")} == {
            "api_readback"
        }
        assert outputs["presets/s12"]["call"] == LIST_PREDEFINED_PRESETS
        assert outputs["presets/s12"]["args"] == {}
        assert outputs["presets/s12"]["value"] == [
            {"name": "PBR Metallic Roughness", "url": "export-preset-generator://fake-metal-rough"},
            {"name": "Fake Packed", "url": "export-preset-generator://fake-packed"},
        ]
        assert outputs["presets/s14"]["value"] == [
            {
                "resource_id": {
                    "url": RESOURCE_PRESET,
                    "context": "starter_assets",
                    "name": "Fake Engine Preset",
                    "version": None,
                }
            }
        ]
        assert outputs["presets/s15"]["args"] == {
            "preset": "PBR Metallic Roughness",
            "texture_set": "uzp_plane",
        }
        assert outputs["presets/s15"]["value"] == {
            "PBR Metallic Roughness": {
                "url": "export-preset-generator://fake-metal-rough",
                "output_maps": FAKE_MAPS,
            }
        }
        assert outputs["presets/s16"]["value"] == FAKE_MAPS
        # Without `preset`: every predefined preset Painter lists, by name.
        assert outputs["presets/s22"]["args"] == {"texture_set": "uzp_plane"}
        assert outputs["presets/s22"]["value"] == {
            "PBR Metallic Roughness": {
                "url": "export-preset-generator://fake-metal-rough",
                "output_maps": FAKE_MAPS,
            },
            "Fake Packed": {
                "url": "export-preset-generator://fake-packed",
                "output_maps": FAKE_MAPS,
            },
        }
        # A preset whose call raises is recorded with what it raised.
        assert outputs["presets/s21"]["value"] == {
            "PBR Metallic Roughness": {
                "url": "export-preset-generator://fake-metal-rough",
                "raised": {"type": "ValueError", "message": "the given stack is invalid"},
            }
        }
        assert outputs["color-spaces/s17"]["value"] == {
            "available_color_spaces": [
                {"class": "GenericColorSpace", "name": "sRGB"},
                {"class": "GenericColorSpace", "name": "Raw"},
                {"class": "LegacyColorSpace", "name": "Linear"},
                {"class": "DataColorSpace", "name": "Data"},
                {"class": "NormalColorSpace", "name": "OpenGL"},
                {"class": "str", "name": "ACEScg"},
            ],
            "color_space": {"class": "GenericColorSpace", "name": "Raw"},
        }
        # What Painter raises is the observation: recorded, never a refusal.
        for output_id, kind, words in [
            ("presets/s18", "ValueError", "0 predefined export presets are named"),
            ("presets/s19", "ValueError", "the given preset is invalid"),
            ("color-spaces/s20", "TypeError", "not a bitmap"),
        ]:
            output = outputs[output_id]
            assert output["value"] is None
            assert output["raised"]["type"] == kind
            assert words in output["raised"]["message"]


def test_captures_alone_make_a_texture_golden(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    step = {"call": LIST_PREDEFINED_PRESETS, "args": {}}
    job = job_from_manifest(with_steps(sample_job, [step], keep_export=False))
    assert not job.exports and not job.export_probes
    record = record_of(record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox))
    for index in (0, 1):
        outputs = by_id(record, index)
        assert outputs["presets/s10"]["value"][0]["name"] == "PBR Metallic Roughness"
        assert not [o for o in outputs.values() if o["kind"] == "exported_map"]


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"call": LIST_PREDEFINED_PRESETS, "args": {"preset": "x"}}, "takes exactly no arguments"),
        ({"call": LIST_RESOURCE_PRESETS, "args": {"all": True}}, "takes exactly no arguments"),
        (
            {"call": PREDEFINED_OUTPUT_MAPS, "args": {"preset": "PBR Metallic Roughness"}},
            r"takes exactly \['preset \(optional\)', 'texture_set'\]",
        ),
        (
            {"call": PREDEFINED_OUTPUT_MAPS, "args": {"texture_set": "a", "stack": "b"}},
            r"takes exactly \['preset \(optional\)', 'texture_set'\]",
        ),
        (
            {"call": PREDEFINED_OUTPUT_MAPS, "args": {"preset": 3, "texture_set": "uzp_plane"}},
            "`preset` must be a name",
        ),
        (
            {"call": PREDEFINED_OUTPUT_MAPS, "args": {"preset": "P", "texture_set": ""}},
            "`texture_set` must be a name",
        ),
        (
            {"call": RESOURCE_OUTPUT_MAPS, "args": {"preset": RESOURCE_PRESET, "texture_set": "x"}},
            r"takes exactly \['preset'\]",
        ),
        (
            {"call": RESOURCE_OUTPUT_MAPS, "args": {"preset": "Blender"}},
            "must be a resource:// URL",
        ),
        (
            {"call": LIST_COLOR_SPACES, "args": {"node_step": 3, "channel": "BaseColor"}},
            "must name an insert_fill step",
        ),
        (
            {"call": LIST_COLOR_SPACES, "args": {"node_step": True, "channel": "BaseColor"}},
            "must name an insert_fill step",
        ),
        (
            {"call": LIST_COLOR_SPACES, "args": {"node_step": 2, "channel": 5}},
            "must be a channel name or null",
        ),
        ({"call": LIST_COLOR_SPACES, "args": {"node_step": 2}}, "takes exactly"),
        (
            {"call": SET_RESOLUTIONS, "args": {"width": 256, "height": "128"}},
            "positive integers",
        ),
        (
            {"call": SET_RESOLUTIONS, "args": {"width": 256, "height": 128, "texture_set": ""}},
            "optional `texture_set` name",
        ),
        (
            {"call": SET_RESOLUTIONS, "args": {"width": 256, "height": 128, "set": "a"}},
            "optional `texture_set` name",
        ),
    ],
)
def test_a_malformed_step_is_refused_before_painter_is_touched(
    sample_job: Job, step: dict[str, Any], message: str
) -> None:
    """The job is refused while the manifest is read, before any session exists."""
    with pytest.raises(RecorderError, match=message):
        job_from_manifest(with_steps(sample_job, [step]))


def test_a_null_channel_names_a_mask_fill_and_state_steps_precede_captures(
    sample_job: Job,
) -> None:
    capture = {"call": LIST_COLOR_SPACES, "args": {"node_step": 2, "channel": None}}
    job = job_from_manifest(with_steps(sample_job, [capture]))
    assert [s.args for s in job.api_captures] == [{"node_step": 2, "channel": None}]
    fill = copy.deepcopy(sample_job.manifest["instruction_sequence"]["steps"][1])
    with pytest.raises(RecorderError, match="must precede the captures"):
        job_from_manifest(with_steps(sample_job, [capture, fill]))


def ocio_manifest(sample_job: Job) -> Job:
    manifest = copy.deepcopy(sample_job.manifest)
    manifest["applied_settings"].append(
        {
            "name": "OCIO",
            "value": "resources/ocio/substance/config.ocio",
            "applied_by": "environment_variable",
        }
    )
    return job_from_manifest(manifest)


def test_a_manifest_naming_no_ocio_is_refused_in_an_ocio_session(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCIO", "C:/Painter/resources/ocio/substance/config.ocio")
    world = fake.FakeWorld()
    with pytest.raises(RecorderError, match="restart Painter without OCIO"):
        record_texture_golden(make_session(world), sample_job, work, inbox)
    assert not world.project_open and not inbox.exists() and not work.exists()
    monkeypatch.delenv("OCIO")
    monkeypatch.setenv("PAINTER_ACE_CONFIG", "C:/ace/config")
    with pytest.raises(RecorderError, match="restart Painter without OCIO"):
        record_texture_golden(make_session(fake.FakeWorld()), sample_job, work, inbox)


def test_a_manifest_naming_ocio_is_refused_in_a_legacy_session_and_recorded_under_it(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = ocio_manifest(sample_job)
    monkeypatch.delenv("OCIO", raising=False)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    world = fake.FakeWorld()
    with pytest.raises(RecorderError, match="start Painter with OCIO"):
        record_texture_golden(make_session(world), job, work, inbox)
    assert not world.project_open and not inbox.exists() and not work.exists()
    monkeypatch.setenv("OCIO", "C:/Painter/resources/ocio/substance/config.ocio")
    run = record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox)
    assert record_of(run)["key"]["project_settings"]["colour_management"]["mode"] == "ocio"

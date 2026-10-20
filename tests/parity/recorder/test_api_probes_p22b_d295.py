"""P22-B API probes of decision 295 (phase1.24 item 3.4): texture sets, channels, project and
export status. The authored jobs live under the envelope's `requests/` or admitted `manifests/`
root; each must validate, load as a probe job, name the Painter symbols it exercises, and
record `r1` and `r2` end to end against the fake Painter (`fake_probe_painter.py`).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import EXPORT
from tools.parity.recorder.probes import (
    ProbeSession,
    load_probe_job,
    manifest_symbol_problems,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.schemas import REPO_ROOT, load_json, record_problems

ENVELOPE = REPO_ROOT / "parity" / "envelopes" / "painter-12.1.5_js-api.1.1.20"
REQUEST_DIR = ENVELOPE / "requests" / "tier0" / "api-probes"
MANIFEST_DIR = ENVELOPE / "manifests" / "tier0" / "api-probes"
INVENTORY = REPO_ROOT / "tools" / "capabilities" / "painter-api-inventory.json"
STEMS = [
    "p22b-export-error-status",
    "p22b-project-mesh-unit-scale",
    "p22b-project-tangent-per-fragment",
    "p22b-project-tangent-per-vertex",
    "p22b-project-workflow-default",
    "p22b-textureset-channels",
    "p22b-textureset-texture-set",
    "p22b-textureset-user-channels",
]
SOFTWARE = {
    "product": "Adobe Substance 3D Painter",
    "version": "12.1.5",
    "build_id": "12.1.5+js-api.1.1.20",
}
# The modules of decision 295's group, and the symbols it routes to another evidence route.
MODULES = ("textureset", "project", "export", "baking", "source")
ROUTED = {
    # The module is supported since 8fa4f517 (baking-defaults replay); these members still wait
    # for a recorded baking probe, owned by phase3.5_embree-bakers (their inventory notes).
    **{
        f"substance_painter.baking.{name}": "phase3.5_embree-bakers"
        for name in (
            "BakingParameters.from_texture_set_name",
            "BakingParameters.set",
            "BakingParameters.texture_set",
            "CurvatureMethod.FromNormalMap",
        )
    },
    "substance_painter.source.SourceMode.Material": "phase3.2_proc-material-families",
    "substance_painter.export.ExportStatus.Cancelled": "G5 open item",
    "substance_painter.export.ExportStatus.Warning": "observed only",
}
# Decision 188's requests exercise these (decision 189 §2).
REQUESTED_BY_188 = {
    *(
        f"substance_painter.textureset.MeshMapUsage.{name}"
        for name in ("BentNormals", "Height", "ID", "Opacity", "Position", "Thickness")
    ),
    "substance_painter.textureset.MeshMapUsage.WorldSpaceNormal",
    "substance_painter.source.SourceBitmap.reset_color_space",
    "substance_painter.source.SourceUniformColor.set_color",
}
TS = "substance_painter.textureset."
PR = "substance_painter.project."
PROBE_FAKE = "uzp_recorder_fake_probe_painter"


def probe_path(stem: str) -> Path:
    """Resolve the authored job without recreating an already admitted request."""
    request = REQUEST_DIR / f"{stem}.json"
    return request if request.is_file() else MANIFEST_DIR / f"{stem}.json"


def steps_of(stem: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = load_json(probe_path(stem))["instruction_sequence"]["steps"]
    return steps


def exercised() -> dict[str, set[str]]:
    """Each pending symbol of the group a request exercises, with the requests: a call it makes,
    an enum member or a `Settings` field it passes, or what the vocabulary reads for it."""
    found: dict[str, set[str]] = {}

    def note(symbol: str, stem: str) -> None:
        found.setdefault(symbol, set()).add(stem)

    for stem in STEMS:
        for step in steps_of(stem):
            call, args = step["call"], step.get("args", {})
            note(call, stem)
            if "channel" in args:
                note(f"{TS}ChannelType.{args['channel']}", stem)
            if "format" in args:
                note(f"{TS}ChannelFormat.{args['format']}", stem)
            if call == f"{TS}Stack.get_channel":
                note(f"{TS}Channel.type", stem)  # the readback reads type, format and label
            if call in (f"{TS}TextureSet.set_resolution", f"{TS}TextureSet.get_resolution"):
                note(f"{TS}Resolution.width", stem)
                note(f"{TS}Resolution.height", stem)
            if call == f"{PR}create":
                for field, kind in (
                    ("tangent_space_mode", "TangentSpace"),
                    ("project_workflow", "ProjectWorkflow"),
                ):
                    if field in args:
                        note(f"{PR}Settings.{field}", stem)
                        note(f"{PR}{kind}", stem)
                        note(f"{PR}{kind}.{args[field]}", stem)
                if "mesh_unit_scale" in args:
                    note(f"{PR}Settings.mesh_unit_scale", stem)
            if call == EXPORT and args.get("export_path_blocked") is True:
                note("substance_painter.export.ExportStatus.Error", stem)
    return found


def pending_of_the_group() -> set[str]:
    entries = load_json(INVENTORY)["entries"]
    return {
        e["symbol"]
        for e in entries
        if e["status"] == "pending-evidence"
        and e["symbol"].split(".")[0] == "substance_painter"
        and len(e["symbol"].split(".")) > 1
        and e["symbol"].split(".")[1] in MODULES
    }


# --- requests --------------------------------------------------------------------------------


def test_the_authored_jobs_keep_their_admission_state() -> None:
    assert {
        p.stem for root in (REQUEST_DIR, MANIFEST_DIR) for p in root.glob("p22b-*.json")
    } >= set(STEMS)
    for stem in STEMS:
        path = probe_path(stem)
        manifest = load_json(path)
        job = load_probe_job(path)  # validates against golden-public.json first
        assert job.golden_id == f"tier0/api-probes/{stem}"
        assert bool(manifest["private_records"]) == (path.parent == MANIFEST_DIR)
        assert manifest["software"]["painter"] == SOFTWARE
        assert manifest_symbol_problems(manifest) == []
        assert not job.lifecycle and not job.exports
        assert job.observed == (stem == "p22b-export-error-status")


def test_every_pending_symbol_of_the_group_is_requested_or_routed() -> None:
    pending = pending_of_the_group()
    covered = set(exercised())
    assert pending - covered - set(ROUTED) - REQUESTED_BY_188 == set()
    assert set(ROUTED) <= pending and not set(ROUTED) & covered
    # Every enum member a channel request passes is one the recorder resolves. The 52 members
    # p22b-textureset-channels passes were pending until abd94980 promoted them on its replay.
    channel_types = {s for s in covered if ".ChannelType." in s}
    assert len(channel_types) == 52
    assert channel_types <= {e["symbol"] for e in load_json(INVENTORY)["entries"]}


def test_the_requests_name_the_symbols_they_exercise() -> None:
    found = exercised()
    for stem in STEMS:
        description = load_json(probe_path(stem))["description"]
        for symbol, stems in found.items():
            if stem in stems and symbol in pending_of_the_group():
                short = symbol.rsplit(".", 1)[1]
                assert short in description, (stem, symbol)


def test_a_blocked_export_path_is_only_an_export_probe_argument() -> None:
    manifest = load_json(probe_path("p22b-export-error-status"))
    job = probe_job_from_manifest(manifest)
    (export,) = (s for s in job.probe_steps if s.call == EXPORT)
    assert export.args["export_path_blocked"] is True and export.probe


# --- recording against the fake --------------------------------------------------------------


@pytest.fixture
def probe_fake(fake: types.ModuleType) -> types.ModuleType:
    """`fake_probe_painter.py`, loaded by path after `fake_painter.py` (which it extends)."""
    if PROBE_FAKE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PROBE_FAKE, Path(__file__).with_name("fake_probe_painter.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[PROBE_FAKE] = module
        spec.loader.exec_module(module)
    return sys.modules[PROBE_FAKE]


def session_on(probe_fake: types.ModuleType, fake: types.ModuleType) -> ProbeSession:
    """A probe session on a fake Painter of 12.1.5, whose project created without a template
    holds that build's default channels."""
    world = probe_fake.ProbeWorld()
    world.version, world.version_info = SOFTWARE["version"], (12, 1, 5)
    formats = {"BaseColor": "sRGB8", "Height": "L16F", "Normal": "RGB16F"}
    world.default_channels = {
        fake.ChannelType[name]: fake.ChannelFormat[formats.get(name, "L8")]
        for name in ("BaseColor", "BaseMetalness", "Height", "Normal", "SpecularRoughness")
    }
    return ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda s: None,
        allowed_builds=lambda: frozenset({SOFTWARE["build_id"]}),
    )


def record(
    probe_fake: types.ModuleType, fake: types.ModuleType, stem: str, tmp_path: Path
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    session = session_on(probe_fake, fake)
    job = load_probe_job(probe_path(stem))
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    assert [r["condition"] for r in data["recordings"]] == ["same_session", "after_save_reopen"]
    first, second = (
        {o["output_id"]: o for o in recording["outputs"]} for recording in data["recordings"]
    )
    for recording in (first, second):
        assert {s.output_id for s in job.probe_steps} <= set(recording)
    return first, second, run


def output(stem: str, call: str, **args: Any) -> str:
    """The output id of the last step of `stem` that makes `call` with (at least) `args` (a
    readback follows the setter of the same call)."""
    found = [
        f"s{step['step']}/{call.rsplit('.', 1)[1]}"
        for step in steps_of(stem)
        if step["call"] == call and all(step.get("args", {}).get(k) == v for k, v in args.items())
    ]
    if not found:
        raise AssertionError(f"{stem}: no {call} step with {args}")
    return found[-1]


@pytest.mark.parametrize("stem", STEMS)
def test_every_request_records_r1_and_r2(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    stem: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCIO", raising=False)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    record(probe_fake, fake, stem, tmp_path)


def test_channels_are_added_edited_removed_and_read_after_reopen(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    stem = "p22b-textureset-channels"
    first, second, _ = record(probe_fake, fake, stem, tmp_path)
    added = first[output(stem, f"{TS}Stack.add_channel", channel="TransmissionColor")]
    assert added["value"] == {"type": "TransmissionColor", "format": "RGB32F", "label": ""}
    labelled = first[output(stem, f"{TS}Stack.edit_channel", channel="ThinFilmWeight")]
    assert labelled["raised"]["type"] == "ValueError"
    absent = [
        o for o in first.values() if o.get("call") == f"{TS}Stack.remove_channel" and "raised" in o
    ]
    assert len(absent) == 1  # Displacement removed twice
    for recording in (first, second):
        get = recording[output(stem, f"{TS}Stack.get_channel", channel="AO")]
        assert get["value"] == {"type": "AO", "format": "L32F", "label": ""}
        get = recording[output(stem, f"{TS}Stack.get_channel", channel="Reflection")]
        assert get["value"]["format"] == "RGB32F"
        assert (
            recording[output(stem, f"{TS}Stack.has_channel", channel="Displacement")]["value"]
            is False
        )
        gone = recording[output(stem, f"{TS}Stack.get_channel", channel="BlendingMask")]
        assert gone["raised"]["type"] == "ValueError"
        assert recording[output(stem, f"{TS}Stack.has_channel", channel="Metallic")]["value"]


def test_user_channel_labels_survive_save_and_reopen(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    stem = "p22b-textureset-user-channels"
    first, second, _ = record(probe_fake, fake, stem, tmp_path)
    for recording in (first, second):
        get = recording[output(stem, f"{TS}Stack.get_channel", channel="User12")]
        assert get["value"] == {"type": "User12", "format": "L32F", "label": "uzp user 12b"}
        get = recording[output(stem, f"{TS}Stack.get_channel", channel="User14")]
        assert get["value"] == {"type": "User14", "format": "L16", "label": "uzp user 14"}
        get = recording[output(stem, f"{TS}Stack.get_channel", channel="User9")]
        assert get["value"]["label"] == ""
        assert not recording[output(stem, f"{TS}Stack.has_channel", channel="User31")]["value"]


def test_texture_set_description_resolution_and_active_stack_read_back(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    stem = "p22b-textureset-texture-set"
    first, second, _ = record(probe_fake, fake, stem, tmp_path)
    for recording in (first, second):
        assert recording[output(stem, f"{TS}TextureSet.get_resolution")]["value"] == [512, 256]
        invalid = recording[output(stem, f"{TS}TextureSet.set_resolution", width=300)]
        assert invalid["raised"]["type"] == "ValueError"
        found = recording[output(stem, f"{TS}TextureSet.from_name", texture_set="uzp_plane")]
        assert "raised" not in found
        assert found["value"] == {"texture_set": {"value": "uzp_plane", "form": CALLED}}
        missing = recording[output(stem, f"{TS}TextureSet.from_name", texture_set="uzp_missing")]
        assert missing["raised"]["type"] == "ValueError"
        original = recording[output(stem, f"{TS}TextureSet.original_name")]
        assert original["value"] == {"value": "uzp_plane", "form": attribute_form("TypeError")}
        description = recording[output(stem, f"{TS}TextureSet.description")]
        assert description["value"] == {
            "value": "uzp probe texture set",
            "form": attribute_form("TypeError"),
        }
        assert recording[output(stem, f"{TS}TextureSet.is_layered_material")]["value"] is False
        active = recording[output(stem, f"{TS}get_active_stack")]
        assert "raised" not in active
        assert active["value"] == {
            "texture_set": {"value": "uzp_plane", "form": CALLED},
            "stack": "",
        }


# The call form of a TextureSet member the python-doc labels a property (SUP-012): the fake models
# `name` as Painter's examples and pipeline scripts call it, `original_name` and `description` as
# attributes; the probe records the form it met and reads through the form that works, so a caught
# TypeError is never taken as the readback.
CALLED = {"callable": True, "is_str": False}


def attribute_form(error: str) -> dict[str, Any]:
    """A string attribute, whose call raises `error` (Python's own message)."""
    message = "'str' object is not callable"
    return {
        "callable": False,
        "is_str": True,
        "called": {"raised": {"type": error, "message": message}},
    }


def test_project_metadata_uuid_and_mesh_path_read_back(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    stem = "p22b-project-tangent-per-vertex"
    first, second, _ = record(probe_fake, fake, stem, tmp_path)
    uuid_steps = [s for s in steps_of(stem) if s["call"] == f"{PR}get_uuid"]
    for recording in (first, second):
        listed = recording[output(stem, f"{PR}Metadata.list", context="uzp_probe")]
        assert listed["value"] == ["flag", "count", "ratio", "label", "items", "mapping"]
        mapping = recording[output(stem, f"{PR}Metadata.get", key="mapping")]
        assert mapping["value"] == {"a": 1, "b": "x", "c": True}
        assert recording[output(stem, f"{PR}Metadata.get", key="absent")]["value"] is None
        empty = recording[output(stem, f"{PR}Metadata.list", context="uzp_probe_empty")]
        assert empty["value"] == []
        for step in uuid_steps:
            assert recording[f"s{step['step']}/get_uuid"]["value"] == {
                "is_uuid_instance": True,
                "parses_as_uuid": True,
                "version": 4,
                "same_as_first_read": True,
            }
        path = recording[output(stem, f"{PR}last_imported_mesh_path")]["value"]
        assert path == {"run_relative": ["inputs", "plane.obj"]}


def test_a_failing_export_reports_error_through_the_event(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    stem = "p22b-export-error-status"
    first, second, run = record(probe_fake, fake, stem, tmp_path)
    for recording in (first, second):
        exported = recording["s3/export_project_textures"]
        assert exported["value"] is None and exported["raised"]["type"] == "RuntimeError"
        events = recording["s3/events"]["value"]
        assert [e["event"] for e in events] == [
            "ExportTexturesAboutToStart",
            "ExportTexturesEnded",
        ]
        assert events[1]["status_argument"] == "Error"
        assert recording["s3/files"]["value"] == []
    work = tmp_path / "work"
    blocked = list(work.rglob("probe-export-step3"))
    assert len(blocked) == 2 and all(path.is_file() for path in blocked)  # r1 and r2
    assert run.is_dir()

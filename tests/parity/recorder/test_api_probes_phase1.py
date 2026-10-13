"""R10 API probes (recording plan R10; `phase1.22` capability evidence): the request manifests.

The manifests are staged, unrecorded, under the envelope's `requests/` root; once a probe is
admitted, its request is deleted and the store's manifest under `manifests/` replaces it. Each must
validate, load as an observed probe job and record end to end against the fake Painter
(`fake_probe_painter.py`), giving the `r1` and `r2` recordings.
"""

from __future__ import annotations

import importlib.util
import json
import random
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
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, load_json, record_problems

REQUEST_DIR = (
    REPO_ROOT
    / "parity"
    / "envelopes"
    / "painter-12.1.5_js-api.1.1.20"
    / "requests"
    / "tier0"
    / "api-probes"
)
MANIFEST_DIR = REQUEST_DIR.parents[2] / "manifests" / "tier0" / "api-probes"
STEMS = [
    "phase1-create-settings",
    "phase1-delete-node",
    "phase1-engine-computations",
    "phase1-execute-when-not-busy",
    "phase1-fill-channel-defaults",
    "phase1-mesh-map-update",
    "phase1-reload-mesh",
    "phase1-reload-resources",
    "phase1-resource-update",
    "phase1-restored-values",
    "phase1-save-as-existing",
    "phase1-save-modes",
    *(f"phase1-srgb-uniform-decode-part{part}" for part in range(1, 5)),
]


def probe_path(stem: str) -> Path:
    """The request while the probe is unrecorded, else its admitted manifest."""
    request = REQUEST_DIR / f"{stem}.json"
    return request if request.is_file() else MANIFEST_DIR / f"{stem}.json"


PROBES = [probe_path(stem) for stem in STEMS]
# The maps each probe exports: BaseColor, except P20-A, which exports every channel of the default
# project (decision 107).
EVERY_DEFAULT_CHANNEL = ["basecolor", "basemetalness", "height", "normal", "specularroughness"]
EXPORTED_MAPS = {"phase1-fill-channel-defaults": EVERY_DEFAULT_CHANNEL}


def exported_maps(stem: str) -> list[str]:
    return EXPORTED_MAPS.get(stem, ["basecolor"])


PROBE_FAKE = "uzp_recorder_fake_probe_painter"
SOFTWARE = {
    "product": "Adobe Substance 3D Painter",
    "version": "12.1.5",
    "build_id": "12.1.5+js-api.1.1.20",
}


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
    """A probe session on a fake Painter of the manifests' build (12.1.5), whose project created
    without a template holds that build's default channels (`assets/templates/default.json`)."""
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = session_on(probe_fake, fake)
    job = load_probe_job(probe_path(stem))
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    first, second = (
        {o["output_id"]: o for o in recording["outputs"]} for recording in data["recordings"]
    )
    return first, second


def event_names(output: dict[str, Any]) -> list[str]:
    return [entry["event"] for entry in output["value"]]


# --- manifests -----------------------------------------------------------------------------


def test_every_probe_manifest_is_an_observed_probe_job_requested_or_admitted() -> None:
    requested = [p.stem for p in REQUEST_DIR.glob("*.json")]
    admitted = [p.stem for p in MANIFEST_DIR.glob("phase1-*.json")]
    assert sorted(requested + admitted) == STEMS
    for path in PROBES:
        manifest = load_json(path)
        job = load_probe_job(path)  # validates against golden-public.json first
        assert job.golden_id == f"tier0/api-probes/{path.stem}"
        assert (manifest["private_records"] == []) == (path.parent == REQUEST_DIR)
        assert manifest["software"]["painter"] == SOFTWARE
        assert manifest_symbol_problems(manifest) == []
        assert job.observed and not job.lifecycle
        assert [m.name for e in job.exports for m in e.maps] == exported_maps(path.stem)


def edited_steps(stem: str, index: int, **changes: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = load_json(probe_path(stem))
    manifest["instruction_sequence"]["steps"][index]["args"].update(changes)
    return manifest


def test_events_are_connected_by_step_two_only() -> None:
    manifest = load_json(probe_path("phase1-delete-node"))
    steps = manifest["instruction_sequence"]["steps"]
    steps[1], steps[2] = steps[2], steps[1]
    steps[1]["step"], steps[2]["step"] = 2, 3
    steps[3]["args"]["node_step"] = 2  # keep the fill's own steps pointing at it
    with pytest.raises(RecorderError, match="events are connected by state step 2 only"):
        probe_job_from_manifest(manifest)


def test_a_work_file_is_a_plain_file_name() -> None:
    manifest = edited_steps("phase1-save-modes", 8, work_file="../escape.spp")
    with pytest.raises(RecorderError, match="must be a plain file name"):
        probe_job_from_manifest(manifest)


def test_a_rewrite_names_two_inputs() -> None:
    manifest = edited_steps("phase1-reload-resources", 8, with_input="nowhere")
    with pytest.raises(RecorderError, match="must both name inputs"):
        probe_job_from_manifest(manifest)


# --- recording against the fake -----------------------------------------------------------


@pytest.mark.parametrize("path", PROBES, ids=lambda p: p.stem)
def test_every_request_records_r1_and_r2(
    probe_fake: types.ModuleType, fake: types.ModuleType, path: Path, tmp_path: Path
) -> None:
    session = session_on(probe_fake, fake)
    job = load_probe_job(path)
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    assert [r["condition"] for r in data["recordings"]] == ["same_session", "after_save_reopen"]
    for recording in data["recordings"]:
        ids = {o["output_id"] for o in recording["outputs"]}
        assert "start/events" in ids
        for step in job.probe_steps:
            assert step.output_id in ids
            if step.wait:
                assert {f"s{step.step}/events", f"s{step.step}/states"} <= ids
            assert f"s{step.step}/pending" not in ids
            if step.call == EXPORT:
                assert f"s{step.step}/files" in ids
        exported = [o for o in recording["outputs"] if o["kind"] == "exported_map"]
        assert len(exported) == len(exported_maps(path.stem))
    state = {f"s{s.step}/events" for s in job.state_steps[1:]}
    first, second = ({o["output_id"] for o in r["outputs"]} for r in data["recordings"])
    assert state <= first
    assert not state & second
    refs = json.loads((run / "manifest.json").read_text(encoding="utf-8"))["private_records"]
    assert len(refs) == 2 + 2 * len(exported_maps(path.stem))  # record, environment, maps


def test_delete_node_records_the_remaining_structure_and_the_deleted_uids(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-delete-node", tmp_path)
    assert first["s14/delete_node"]["value"] is None and "raised" not in first["s14/delete_node"]
    for recording in (first, second):
        roots = recording["s16/get_root_layer_nodes"]["value"]
        assert [r["name"] for r in roots] == ["uzp fill A"]
        assert recording["s18/get_name"]["value"] == "uzp fill A"
        for gone in ("s19", "s20", "s21"):  # B, the group, and the fill inside the group
            assert recording[f"{gone}/get_node_by_uid"]["raised"]["type"] == "ValueError"
        assert "identity/s3" in recording
        assert not {"identity/s7", "identity/s11", "identity/s12"} & set(recording)
    assert isinstance(first["s17/uid"]["value"], int)
    assert first["s17/uid"]["value"] != second["s17/uid"]["value"]  # the fake renumbers on reopen


def test_resource_update_rebinds_the_mask_fill(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-resource-update", tmp_path)
    replaced = first["s12/update_layer_stack_resource"]["value"]
    assert [r["resource"]["name"] for r in replaced] == ["mask_left_half.image"]
    for recording in (first, second):
        bound = recording["s13/get_source"]["value"]["bitmap"]["resource"]["name"]
        assert bound == "ao_white.image"
        assert isinstance(recording["s14/uid"]["value"], int)


def test_save_modes_record_events_paths_and_work_files(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-save-modes", tmp_path)
    assert first["s7/file_path"]["value"] == {"is_none": True}
    assert second["s7/file_path"]["value"] == {"file_name": "probe.spp"}
    for recording in (first, second):
        assert event_names(recording["s9/events"]) == ["ProjectAboutToSave", "ProjectSaved"]
        assert recording["s9/files"]["value"] == ["copy.spp"]
        assert recording["s12/files"]["value"] == ["copy.spp", "main.spp"]
        assert recording["s13/file_path"]["value"] == {"file_name": "main.spp"}
        assert recording["s14/needs_saving"]["value"] is False
        assert event_names(recording["s18/events"]) == ["ProjectAboutToSave", "ProjectSaved"]
        assert recording["s18/files"]["value"] == ["copy.spp", "main.spp"]
        assert recording["s19/file_path"]["value"] == {"file_name": "main.spp"}


def test_create_settings_read_back_the_resolution(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-create-settings", tmp_path)
    for recording in (first, second):
        assert recording["s7/get_resolution"]["value"] == [512, 512]
        assert recording["s8/all_texture_sets"]["value"] == ["uzp_plane"]


def test_engine_computations_order_and_the_export_request(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-engine-computations", tmp_path)
    for recording in (first, second):
        assert recording["s7/engine_computations_status"]["value"] is True
        disabled = recording["s9/events"]["value"]
        assert [(e["event"], e.get("during_step")) for e in disabled] == [
            ("EngineComputationsStatusChanged", 9)
        ]
        assert disabled[0]["engine_computations_enabled_argument"] is False
        assert recording["s9/states"]["value"][-1]["engine_computations"] is False
        assert recording["s10/engine_computations_status"]["value"] is False
        request = recording["s13/export_project_textures"]["value"]
        assert request["status"] == "Success"
        assert request["textures"] == {"uzp_plane/": ["uzp_plane_basecolor.png"]}
        assert event_names(recording["s13/events"]) == [
            "ExportTexturesAboutToStart",
            "ExportTexturesEnded",
        ]
        files = recording["s13/files"]["value"]
        assert [f["file_name"] for f in files] == ["uzp_plane_basecolor.png"]
        assert recording["s15/engine_computations_status"]["value"] is True
        inside = recording["s16/disable_engine_computations"]["value"]
        assert inside["inside"]["engine_computations"] is False
        assert inside["engine_computations_after"] is True
        assert event_names(recording["s16/events"]) == ["EngineComputationsStatusChanged"] * 2
        source = recording["s18/get_source"]["value"]
        assert source["uniform_color_working"] != [0.1, 0.6, 0.3]
    assert first["identity/s3"]["value"]["present"] is True


def test_reload_mesh_records_the_callback_status_and_its_events(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-reload-mesh", tmp_path)
    for recording in (first, second):
        assert recording["s8/reload_mesh"]["value"] is None
        reloaded = recording["s8/events"]["value"]
        assert [e["event"] for e in reloaded] == [
            "BusyStatusChanged",
            "BusyStatusChanged",
            "reload_mesh.loading_status_cb",
        ]
        assert reloaded[0]["during_step"] == 8 and reloaded[0]["busy_argument"] is True
        assert "during_step" not in reloaded[2]
        assert reloaded[2]["status"] == "SUCCESS"
        missing = recording["s12/events"]["value"]
        assert missing[-1]["status"] == "ERROR"


def test_reload_resources_records_started_and_ended(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-reload-resources", tmp_path)
    staged = sorted((tmp_path / "work").rglob("inputs/mask_left_half.png"))
    checker = REPO_ROOT / "parity" / "fixtures" / "api-probes" / "checker-16.png"
    assert [p.read_bytes() for p in staged] == [checker.read_bytes()]
    for recording in (first, second):
        assert recording["s8/is_reload_modified_resources_running"]["value"] is False
        assert recording["s9/reload_modified_resources_async"]["value"] == {
            "returned": True,
            "running_after_call": True,
        }
        events = recording["s9/events"]["value"]
        assert [e["event"] for e in events] == ["ReloadResourcesStarted", "ReloadResourcesEnded"]
        assert events[0]["filter_argument"] == "ResourcesUsedByProjectFilter"
        assert [r["old"]["resource"]["name"] for r in events[1]["reloaded_resources_argument"]] == [
            "mask_left_half.image"
        ]
        assert recording["s10/is_reload_modified_resources_running"]["value"] is False
        assert recording["s12/events"]["value"][0]["filter_argument"] == "ProjectFilter"


def test_execute_when_not_busy_runs_after_the_busy_period(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    first, second = record(probe_fake, fake, "phase1-execute-when-not-busy", tmp_path)
    for recording in (first, second):
        assert event_names(recording["s8/events"]) == ["execute_when_not_busy.callback"]
        assert "s9/events" not in recording  # `wait: false`: recorded with step 10
        assert event_names(recording["s10/events"]) == [
            "BusyStatusChanged",
            "BusyStatusChanged",
            "reload_mesh.loading_status_cb",
            "execute_when_not_busy.callback",
        ]
        assert recording["s10/events"]["value"][-1]["busy"] is False


def test_dense_srgb_decode_reads_back_every_code_and_the_seeded_floats() -> None:
    """P20-B (decision 107): each set_source probe is followed by its get_source readback; the
    four parts set 80 colours each, in order (decision 180: one request did not fit a window)."""
    sets: list[dict[str, Any]] = []
    for part in range(1, 5):
        path = probe_path(f"phase1-srgb-uniform-decode-part{part}")
        steps = load_json(path)["instruction_sequence"]["steps"]
        part_sets = [s for s in steps if s["call"].endswith("FillLayerNode.set_source")]
        gets = [s for s in steps if s["call"].endswith("FillLayerNode.get_source")]
        assert len(part_sets) == len(gets) == 80
        assert all(g["step"] == s["step"] + 1 for s, g in zip(part_sets, gets, strict=True))
        sets += part_sets
    rng = random.Random(20261012)
    expected = [[c / 255] * 3 for c in range(256)] + [
        [rng.random() for _ in range(3)] for _ in range(64)
    ]
    assert [s["args"]["color"] for s in sets] == expected
    assert {s["args"]["color_space"] for s in sets} == {"sRGB"}


@pytest.mark.parametrize("stem", ["phase1-restored-values", "phase1-save-as-existing"])
def test_every_save_probe_edit_is_followed_by_a_readback(stem: str) -> None:
    """P22-C and P23-A (decisions 111, 113): after each probed edit, a getter reads the result."""
    steps = load_json(probe_path(stem))["instruction_sequence"]["steps"]
    edits = [i for i, s in enumerate(steps) if s["args"].get("probe")]
    assert edits
    for index in edits:
        following = steps[index + 1]["call"]
        assert (
            following.endswith(("needs_saving", "file_path")) or "probe" in steps[index + 1]["args"]
        )


def test_fill_channel_defaults_reads_every_channel_and_exports_it(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """P20-A (decision 107): the fresh fill's source on every default channel, each bitmap's
    colour spaces on every channel and in both masks, and every channel exported."""
    first, second = record(probe_fake, fake, "phase1-fill-channel-defaults", tmp_path)
    for recording in (first, second):
        active = recording["s27/active_channels"]["value"]
        assert [c.lower() for c in active] == EVERY_DEFAULT_CHANNEL
        assert all(
            "uniform_color_working" in recording[f"s{s}/get_source"]["value"] for s in range(28, 33)
        )
        for step in range(33, 69, 3):
            assert "bitmap" in recording[f"s{step}/get_source"]["value"]
            assert {
                f"s{step + 1}/get_color_space",
                f"s{step + 2}/list_available_color_spaces",
            } <= set(recording)
        exported = sorted(
            k.split("/")[-1] for k, o in recording.items() if o["kind"] == "exported_map"
        )
        assert exported == EVERY_DEFAULT_CHANNEL

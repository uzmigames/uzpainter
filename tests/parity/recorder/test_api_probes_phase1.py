"""R10 API probes (recording plan R10; `phase1.22` capability evidence): the request manifests.

The manifests are staged, unrecorded, under the envelope's `requests/` root; once a probe is
admitted, its request is deleted and the store's manifest under `manifests/` replaces it. Each must
validate, load as an observed probe job and record end to end against the fake Painter
(`fake_probe_painter.py`), giving the `r1` and `r2` recordings.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
import types
from collections.abc import Callable
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
# P22-B layer stack, levels and colour requests (decision 296; test_api_probes_p22b_layerstack.py).
P22B_LAYERSTACK_STEMS = [
    "phase1-blending-modes-layer",
    "phase1-blending-modes-mask",
    "phase1-color-srgb-value",
    "phase1-layer-navigation",
    "phase1-layer-node-kinds",
    "phase1-levels-params",
]
STEMS = [
    "phase1-camera-coupling",
    "phase1-close-without-saving",
    "phase1-create-default-paths",
    "phase1-create-mesh-maps",
    "phase1-create-settings",
    "phase1-default-camera-bevelled-cube",
    "phase1-default-camera-plane",
    "phase1-default-camera-sphere",
    "phase1-delete-node",
    "phase1-display-ocio",
    "phase1-engine-computations",
    "phase1-execute-when-not-busy",
    "phase1-export-preset-search",
    "phase1-fill-channel-defaults",
    "phase1-layer-stack-events",
    "phase1-mesh-map-update",
    "phase1-reload-mesh",
    "phase1-reload-resources",
    "phase1-resource-update",
    "phase1-restored-values",
    "phase1-save-as-existing",
    "phase1-save-modes",
    "phase1-shelves",
    *(f"phase1-srgb-uniform-decode-ocio-part{part}" for part in range(1, 5)),
    *(f"phase1-srgb-uniform-decode-part{part}" for part in range(1, 5)),
    "phase1-texture-throttling",
    # P22-B layer stack, levels and colour (decision 296).
    *P22B_LAYERSTACK_STEMS,
]
# The lifecycle procedure timed by a second thread (P21-F, decision 109).
LIFECYCLE_STEMS = ["phase1-create-open-timing"]
# Probes recorded in an OCIO session (R-132-D, decision 132; P20-B's OCIO twin, decision 190).
OCIO_STEMS = frozenset(
    {"phase1-display-ocio", *(f"phase1-srgb-uniform-decode-ocio-part{n}" for n in range(1, 5))}
)
OCIO_CONFIG = "C:/Painter/resources/ocio/substance/config.ocio"


def probe_path(stem: str) -> Path:
    """The request while the probe is unrecorded, else its admitted manifest."""
    request = REQUEST_DIR / f"{stem}.json"
    return request if request.is_file() else MANIFEST_DIR / f"{stem}.json"


PROBES = [probe_path(stem) for stem in STEMS]
# The maps each probe exports: BaseColor, except P20-A, which exports every channel of the default
# project (decision 107).
EVERY_DEFAULT_CHANNEL = ["basecolor", "basemetalness", "height", "normal", "specularroughness"]
EXPORTED_MAPS = {"phase1-fill-channel-defaults": EVERY_DEFAULT_CHANNEL}
# The host-behaviour probes (decisions 095, 109, 110, 132) export nothing as a capture.
HOST_PROBES = frozenset(
    {
        "phase1-camera-coupling",
        "phase1-close-without-saving",
        "phase1-create-default-paths",
        "phase1-create-mesh-maps",
        "phase1-default-camera-bevelled-cube",
        "phase1-default-camera-plane",
        "phase1-default-camera-sphere",
        "phase1-display-ocio",
        "phase1-export-preset-search",
        "phase1-layer-stack-events",
        "phase1-shelves",
        "phase1-texture-throttling",
        *P22B_LAYERSTACK_STEMS,
    }
)


def exported_maps(stem: str) -> list[str]:
    return [] if stem in HOST_PROBES else EXPORTED_MAPS.get(stem, ["basecolor"])


@pytest.fixture
def colour_session(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Start the fake session under OCIO for an OCIO probe, else under Legacy."""

    def start(stem: str) -> None:
        if stem in OCIO_STEMS:
            monkeypatch.setenv("OCIO", OCIO_CONFIG)
        else:
            monkeypatch.delenv("OCIO", raising=False)
        monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)

    return start


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
    if stem not in OCIO_STEMS:
        assert "OCIO" not in os.environ or not os.environ["OCIO"]
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
    requested = [p.stem for p in REQUEST_DIR.glob("phase1-*.json")]
    admitted = [p.stem for p in MANIFEST_DIR.glob("phase1-*.json")]
    assert sorted(requested + admitted) == sorted(STEMS + LIFECYCLE_STEMS)
    for stem in LIFECYCLE_STEMS:
        job = load_probe_job(probe_path(stem))
        assert job.lifecycle and job.timing
        assert manifest_symbol_problems(job.manifest) == []
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


@pytest.mark.parametrize("replacement", ["missing", None, [], 7])
def test_after_reopen_rewrite_requires_a_pinned_input(replacement: Any) -> None:
    manifest = load_json(REQUEST_DIR / "p22b-reload-order-zam.json")
    manifest["instruction_sequence"]["steps"][5]["args"]["with_input_after_reopen"] = replacement
    with pytest.raises(RecorderError, match="requires a reload rewrite and must name an input"):
        probe_job_from_manifest(manifest)


@pytest.mark.parametrize("removed", ["rewrite_input", "with_input"])
def test_after_reopen_rewrite_requires_the_original_rewrite(removed: str) -> None:
    manifest = load_json(REQUEST_DIR / "p22b-reload-order-zam.json")
    del manifest["instruction_sequence"]["steps"][5]["args"][removed]
    with pytest.raises(RecorderError, match="requires a reload rewrite and must name an input"):
        probe_job_from_manifest(manifest)


@pytest.mark.parametrize("all_origins", [False, True])
@pytest.mark.parametrize("order", ["zam", "mza"])
def test_reload_order_requests_copy_distinct_bytes_after_reopen(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    order: str,
    all_origins: bool,
) -> None:
    monkeypatch.delenv("OCIO", raising=False)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    suffix = "-all-origins" if all_origins else ""
    job = load_probe_job(REQUEST_DIR / f"p22b-reload-order-{order}{suffix}.json")
    assert manifest_symbol_problems(job.manifest) == []
    assert job.observed and not job.exports and job.manifest["private_records"] == []
    names = [step.args["image"] for step in job.state_steps[1:]]
    assert names == ({"zam": ["zeta", "alpha", "mu"], "mza": ["mu", "zeta", "alpha"]}[order])
    variants = [job.inputs[f"reload-order-v{i}"].read_bytes() for i in range(1, 5)]
    assert len(set(variants)) == 4
    assert len({job.inputs[name].read_bytes() for name in names}) == 1
    session = session_on(probe_fake, fake)
    original_call = session.call
    roots: list[Path] = []
    copied: list[tuple[str, bytes]] = []

    def call(operation: str, **kwargs: Any) -> Any:
        if operation == "probe_reset":
            roots.append(Path(kwargs["root"]))
        if operation == "probe_step" and "rewrite_input" in kwargs["args"]:
            args = kwargs["args"]
            staged = roots[-1] / "inputs" / f"{args['rewrite_input']}.png"
            copied.append((args["with_input"], staged.read_bytes()))
        return original_call(operation, **kwargs)

    monkeypatch.setattr(session, "call", call)
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    assert [r["condition"] for r in data["recordings"]] == ["same_session", "after_save_reopen"]
    repetitions = 3 if all_origins else 1
    assert copied == [
        (f"reload-order-v{i}", variants[i - 1]) for i in range(1, 5) for _ in range(repetitions)
    ]
    assert [s.args.get("with_input") for s in job.probe_steps] == [
        *(["reload-order-v1"] * repetitions),
        *(["reload-order-v2"] * repetitions),
        None,
    ]
    if all_origins:
        assert [s.args["filter"] for s in job.probe_steps] == [
            "SessionFilter",
            "SessionFilter",
            "ProjectFilter",
            "SessionFilter",
            "SessionFilter",
            "ProjectFilter",
            "ProjectFilter",
        ]
        assert [s.args.get("rewrite_input") for s in job.probe_steps] == [
            *names,
            *names,
            None,
        ]
    for recording in data["recordings"]:
        outputs = {o["output_id"]: o for o in recording["outputs"]}
        for step in range(6, 13 if all_origins else 9):
            assert event_names(outputs[f"s{step}/events"]) == [
                "ReloadResourcesStarted",
                "ReloadResourcesEnded",
            ]


# --- recording against the fake -----------------------------------------------------------


def test_mesh_map_alias_request_distinguishes_names_from_shared_content() -> None:
    job = load_probe_job(REQUEST_DIR / "p22b-mesh-map-alias-update.json")
    assert manifest_symbol_problems(job.manifest) == []
    assert job.observed and not job.exports and job.manifest["private_records"] == []
    assert [s.step for s in job.state_steps] == list(range(2, 10))
    assert [s.step for s in job.probe_steps] == [10, 11]
    inputs = {i["input_id"]: i for i in job.manifest["inputs"]}
    assert inputs["mesh-map-old"]["sha256"] == inputs["mesh-map-alias"]["sha256"]
    assert inputs["mesh-map-old"]["sha256"] != inputs["mesh-map-new"]["sha256"]
    steps = {s.step: s for s in (*job.state_steps, *job.probe_steps)}
    assert [steps[s].args["image"] for s in (3, 4, 5)] == [
        "mesh-map-old",
        "mesh-map-alias",
        "mesh-map-new",
    ]
    assert [(steps[s].args["usage"], steps[s].args["resource_step"]) for s in (6, 7)] == [
        ("AO", 3),
        ("Thickness", 4),
    ]
    assert steps[8].args == {"resource_step": 3, "new_resource_step": 3}
    assert steps[9].args == {"resource_step": 3, "new_resource_step": 5}
    assert [steps[s].args["usage"] for s in (10, 11)] == ["AO", "Thickness"]
    assert all(steps[s].call.endswith("get_mesh_map_resource") for s in (10, 11))


@pytest.mark.parametrize("path", PROBES, ids=lambda p: p.stem)
def test_every_request_records_r1_and_r2(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    path: Path,
    tmp_path: Path,
    colour_session: Callable[[str], None],
) -> None:
    colour_session(path.stem)
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


@pytest.mark.parametrize(
    "family", ["phase1-srgb-uniform-decode", "phase1-srgb-uniform-decode-ocio"]
)
def test_dense_srgb_decode_reads_back_every_code_and_the_seeded_floats(family: str) -> None:
    """P20-B (decision 107) and its OCIO twin (decision 190): each set_source probe is followed by
    its get_source readback; the four parts set 80 colours each, in order (decision 180: one
    request did not fit a window); only the twin names OCIO."""
    sets: list[dict[str, Any]] = []
    for part in range(1, 5):
        manifest = load_json(probe_path(f"{family}-part{part}"))
        ocio = [s for s in manifest["applied_settings"] if s["name"] == "OCIO"]
        assert bool(ocio) == family.endswith("-ocio")
        steps = manifest["instruction_sequence"]["steps"]
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


# --- host behaviour probes (decisions 095, 109, 110, 132) -----------------------------------


def outputs_by_id(run: Path) -> list[dict[str, Any]]:
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    return [{o["output_id"]: o for o in r["outputs"]} for r in data["recordings"]]


def recorded(
    probe_fake: types.ModuleType, fake: types.ModuleType, stem: str, tmp_path: Path
) -> tuple[Any, list[dict[str, Any]], Path]:
    world = probe_fake.ProbeWorld()
    world.version, world.version_info = SOFTWARE["version"], (12, 1, 5)
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda s: None,
        allowed_builds=lambda: frozenset({SOFTWARE["build_id"]}),
    )
    run = record_probe_golden(session, load_probe_job(probe_path(stem)), tmp_path / "w", tmp_path)
    return world, outputs_by_id(run), run


def test_create_binds_the_named_mesh_maps(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """P21-A: the staged files keep the `<texture set>_<name>` stems Painter reads."""
    _, recordings, _ = recorded(probe_fake, fake, "phase1-create-mesh-maps", tmp_path)
    for recording in recordings:
        bound = {
            o["args"]["usage"]: o["value"]
            for o in recording.values()
            if o.get("call", "").endswith("get_mesh_map_resource")
        }
        assert len(bound) == 10
        assert bound["AO"]["resource"]["name"] == "uzp_plane_ambient_occlusion"
        assert {u for u, v in bound.items() if v is None} == {"BentNormals", "Height", "Opacity"}


def test_default_paths_record_where_the_export_went(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """P21-B: the folders are made in the run's work directory; an export without `exportPath`
    reports its files relative to the run, hashed."""
    _, (first, second), _ = recorded(probe_fake, fake, "phase1-create-default-paths", tmp_path)
    for recording in (first, second):
        assert recording["s3/get_default_export_path"]["value"] == {
            "path": probe_fake.DEFAULT_EXPORT_PATH
        }
        located = recording["s6/export_project_textures"]["value"]["locations"]
        assert located == {
            "uzp_plane/": [
                {"run_relative": ["r1", "work-files", "default-export", "uzp_plane_basecolor.png"]}
            ]
        }
        files = recording["s6/files"]["value"]
        assert [f["file_name"] for f in files] == [
            "r1/work-files/default-export/uzp_plane_basecolor.png"
        ]
        assert files[0]["sha256"]
    assert first["s7/save"]["raised"]["type"] == "ProjectError"  # the fake's untitled project
    assert "raised" not in second["s7/save"]


def test_throttling_period_is_read_as_milliseconds(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    _, recordings, _ = recorded(probe_fake, fake, "phase1-texture-throttling", tmp_path)
    for recording in recordings:
        value = recording["s3/cache_key_invalidation_throttling_period"]["value"]
        assert value == {"timedelta_ms": 1000.0}


def test_shelves_follow_the_crawl_and_are_removed_after_closing(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """P21-D: the added shelf's crawl events and states, the shelves listed, and the shelf
    removed once the project is closed."""
    world, (first, second), _ = recorded(probe_fake, fake, "phase1-shelves", tmp_path)
    crawl = first["s3/events"]["value"]
    assert [(e["event"], e["shelf_name_argument"]) for e in crawl] == [
        ("ShelfCrawlingStarted", "uzp_probe_shelf"),
        ("ShelfCrawlingEnded", "uzp_probe_shelf"),
    ]
    states = first["s3/states"]["value"]
    assert states[-1]["shelves_crawling"] == {"uzp_probe_shelf": False}  # the fake's crawl ends
    for recording in (first, second):
        shelves = {s["shelf"]: s["path"] for s in recording["s4/all"]["value"]}
        assert shelves["uzp_probe_shelf"] == {"run_relative": ["r1", "work-files", "probe-shelf"]}
        assert recording["s5/application_shelf"]["value"]["shelf"] == "starter_assets"
        assert recording["s6/user_shelf"]["value"]["shelf"] == "your_assets"
        assert recording["s7/exists"]["value"] is True
        assert event_names(recording["s9/events"]) == ["ShelfCrawlingStarted", "ShelfCrawlingEnded"]
    copied = tmp_path / "w"
    assert sorted(p.name for p in copied.rglob("probe-shelf/*")) == ["checker.png"]
    assert world.shelves == {}


def test_layer_stack_edits_are_each_observed(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """P21-E: every listed edit runs as a probe step in both recordings with its events."""
    _, recordings, _ = recorded(probe_fake, fake, "phase1-layer-stack-events", tmp_path)
    job = load_probe_job(probe_path("phase1-layer-stack-events"))
    edits = [s for s in job.probe_steps if s.probe]
    assert len(edits) == 21
    for recording in recordings:
        for step in edits:
            assert "raised" not in recording[step.output_id], step
            assert f"s{step.step}/events" in recording


def test_timed_lifecycle_polls_from_a_second_thread(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """P21-F: create and open carry the phase marker and the second thread's polls."""
    _, recordings, _ = recorded(probe_fake, fake, "phase1-create-open-timing", tmp_path)
    assert len(recordings) == 4
    for index, recording in enumerate(recordings):
        phase = "create" if index % 2 == 0 else "open"
        polls = recording[f"{phase}/thread_polls"]["value"]
        assert polls["poll_count"] >= 1 and polls["polls"]
        marked = [e for e in recording[f"{phase}/events"]["value"] if "during_step" in e]
        assert marked and all(e["during_step"] == phase for e in marked)


def test_close_without_saving_reopens_the_saved_name(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """P21-G: the rename is lost by the close; the fill is found again after the open."""
    _, recordings, _ = recorded(probe_fake, fake, "phase1-close-without-saving", tmp_path)
    for recording in recordings:
        assert recording["s7/get_name"]["value"] == "uzp fill B"
        assert recording["s10/rebind"]["value"]["found_by"] == {"3": "location"}
        assert recording["s11/get_name"]["value"] == "uzp fill A"
        assert recording["s12/needs_saving"]["value"] is False


@pytest.mark.parametrize("mesh", ["plane", "sphere", "bevelled-cube"])
def test_default_camera_reads_every_property(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path, mesh: str
) -> None:
    _, recordings, _ = recorded(probe_fake, fake, f"phase1-default-camera-{mesh}", tmp_path)
    for recording in recordings:
        camera = recording["s3/get_default_camera"]["value"]
        assert sorted(camera) == sorted(
            [
                "aperture",
                "field_of_view",
                "focal_length",
                "focus_distance",
                "orthographic_height",
                "position",
                "projection_type",
                "rotation",
            ]
        )
        assert set(recording["s4/get_scene_bounding_box"]["value"]) == {
            "center",
            "dimensions",
            "radius",
        }


def test_camera_sweep_reads_back_after_every_set(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    _, recordings, _ = recorded(probe_fake, fake, "phase1-camera-coupling", tmp_path)
    job = load_probe_job(probe_path("phase1-camera-coupling"))
    sets = [s for s in job.probe_steps if "value" in s.args]
    for recording in recordings:
        for step in sets:
            prop = step.call.rsplit(".", 1)[1]
            readback = recording[f"s{step.step + 1}/get_default_camera"]["value"]
            if prop != "projection_type":
                assert readback[prop] == step.args["value"]  # the fake neither clamps nor couples


def test_ocio_probes_need_an_ocio_session(
    probe_fake: types.ModuleType,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-132-D names OCIO: a Legacy session refuses it; an OCIO one records the display."""
    monkeypatch.delenv("OCIO", raising=False)
    with pytest.raises(RecorderError, match="start Painter with OCIO"):
        recorded(probe_fake, fake, "phase1-display-ocio", tmp_path / "legacy")
    monkeypatch.setenv("OCIO", OCIO_CONFIG)
    _, recordings, run = recorded(probe_fake, fake, "phase1-display-ocio", tmp_path / "ocio")
    record = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record["key"]["project_settings"]["colour_management"]["mode"] == "ocio"
    for recording in recordings:
        environment = recording["s11/get_environment_resource"]["value"]
        assert environment["resource"]["name"] == "sky-patch"
        assert recording["s15/get_color_lut_resource"]["value"] is None


def test_export_preset_search_records_identifiers(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    """R-095 P7: each found preset's identifier, GUI name and usages."""
    _, recordings, _ = recorded(probe_fake, fake, "phase1-export-preset-search", tmp_path)
    for recording in recordings:
        for step in ("s3", "s4"):
            (found,) = recording[f"{step}/search"]["value"]
            assert found["identifier"]["resource"]["name"] == "Fake Engine Preset"
            assert found["gui_name"] == "Fake Engine Preset"

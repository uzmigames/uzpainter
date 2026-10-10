"""Baking jobs against a fake Painter (phase0.9_normal-convention-fixture): bake parameters from
the documented `BakingParameters.set`, the enabled bakers, `bake_async` with the wait for
`BakingProcessEnded`, the readbacks of both recordings, and baked mesh-map exports."""

from __future__ import annotations

import copy
import json
import shutil
import types
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pytest

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import STATE_CALLS, Job, job_from_manifest, load_job, sha256_file
from tools.parity.recorder.provenance import documented_symbols
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import file_url, record_texture_golden
from tools.parity.schemas import REPO_ROOT

MakeSession = Callable[[Any], PainterSession]

PLANE = REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj"
BAKING_SET = "substance_painter.baking.BakingParameters.set"
SET_ENABLED = "substance_painter.baking.BakingParameters.set_enabled_bakers"
BAKE = "substance_painter.baking.bake_async"
EXPORT = "substance_painter.export.export_project_textures"


def authored_input(input_id: str, path: str, root: Path) -> dict[str, Any]:
    return {
        "input_id": input_id,
        "kind": "mesh",
        "path": path,
        "sha256": sha256_file(root / path),
        "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository root holding the low-poly plane and a distinct "high-poly" mesh."""
    root = tmp_path / "repo"
    meshes = root / "parity" / "fixtures" / "meshes"
    meshes.mkdir(parents=True)
    shutil.copyfile(PLANE, meshes / "plane.obj")
    (meshes / "plane-high.obj").write_bytes(PLANE.read_bytes() + b"# high\n")
    return root


def bake_steps() -> list[dict[str, Any]]:
    return [
        {"call": "substance_painter.project.create", "args": {"mesh": "plane"}},
        {"call": BAKING_SET, "args": {"parameter": "fake_size", "value": [9, 9]}},
        {"call": BAKING_SET, "args": {"parameter": "fake_mode", "enum_label": "Second"}},
        {
            "call": BAKING_SET,
            "args": {"parameter": "fake_filter", "usage": "AO", "enum_label": "On"},
        },
        {"call": BAKING_SET, "args": {"parameter": "HipolyMesh", "input": "plane-high"}},
        {"call": SET_ENABLED, "args": {"usages": ["Normal"]}},
        {"call": BAKE, "args": {}},
        {
            "call": EXPORT,
            "args": {
                "maps": ["meshMap/normal_base:RGB"],
                "file_format": "png",
                "bit_depth": 16,
                "padding": "infinite",
            },
        },
    ]


def bake_manifest(sample: Job, repo: Path, steps: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = copy.deepcopy(sample.manifest)
    manifest["golden_id"] = "tier0/recorder-sample/bake-normal"
    manifest["inputs"] = [
        authored_input("plane", "parity/fixtures/meshes/plane.obj", repo),
        authored_input("plane-high", "parity/fixtures/meshes/plane-high.obj", repo),
    ]
    manifest["instruction_sequence"]["steps"] = [
        {"step": number, **step} for number, step in enumerate(steps, start=1)
    ]
    manifest["private_records"] = []
    return manifest


@pytest.fixture
def bake_job(sample_job: Job, repo: Path, tmp_path: Path) -> Job:
    """The baking job, loaded through `load_job` so that it validates as a public manifest."""
    path = tmp_path / "bake-normal.json"
    path.write_text(json.dumps(bake_manifest(sample_job, repo, bake_steps())), encoding="utf-8")
    return load_job(path, repo_root=repo)


def refused(sample: Job, repo: Path, steps: list[dict[str, Any]], match: str) -> None:
    with pytest.raises(RecorderError, match=match):
        job_from_manifest(bake_manifest(sample, repo, steps), repo_root=repo)


def with_step(index: int, step: dict[str, Any]) -> list[dict[str, Any]]:
    steps = bake_steps()
    steps.insert(index, step)
    return steps


def record_of(run: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((run / "record.json").read_text(encoding="utf-8"))
    return record


def readbacks(recording: dict[str, Any]) -> dict[str, Any]:
    return {o["output_id"]: o for o in recording["outputs"] if o["kind"] == "api_readback"}


class Clock:
    """Monotonic time that advances only when the session sleeps between polls."""

    def __init__(self, step_s: float) -> None:
        self.now = 0.0
        self.step_s = step_s

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += self.step_s


# --- job validation -------------------------------------------------------------------------


def test_bake_steps_are_state_steps_of_the_documented_vocabulary(bake_job: Job) -> None:
    symbols = documented_symbols()
    for call in (BAKING_SET, SET_ENABLED, BAKE, ps.GET_PROPERTY_VALUE, ps.BAKING_ENABLED_BAKERS):
        assert call in symbols
    assert {BAKING_SET, SET_ENABLED, BAKE} <= STATE_CALLS
    assert [s.call for s in bake_job.state_steps][-3:] == [BAKING_SET, SET_ENABLED, BAKE]
    assert [m.map_type for m in bake_job.exports[0].maps] == ["meshMap"]


def test_input_must_name_an_input_with_a_path(sample_job: Job, repo: Path) -> None:
    steps = bake_steps()
    steps[4]["args"]["input"] = "missing"
    refused(sample_job, repo, steps, "`input` must name an input with a path")
    manifest = bake_manifest(sample_job, repo, bake_steps())
    del manifest["inputs"][1]["path"]
    with pytest.raises(RecorderError, match="`input` must name an input with a path"):
        job_from_manifest(manifest, repo_root=repo)


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ({"parameter": "fake_size", "value": 1, "enum_label": "Second"}, "exactly one of"),
        ({"parameter": "fake_size"}, "exactly one of"),
        ({"value": 1}, "needs a `parameter` name"),
        ({"parameter": "fake_size", "value": None}, "cannot be null"),
        ({"parameter": "fake_mode", "enum_label": 2}, "label string"),
        ({"parameter": "fake_size", "value": 1, "usage": "Albedo"}, "not a MeshMapUsage member"),
        ({"parameter": "fake_size", "value": 1, "channel": "x"}, "does not take"),
        ({"parameter": "HipolyMesh", "value": "C:/meshes/high.obj"}, "only from an `input`"),
    ],
)
def test_malformed_baking_parameter_steps_are_refused(
    sample_job: Job, repo: Path, args: dict[str, Any], match: str
) -> None:
    refused(sample_job, repo, with_step(1, {"call": BAKING_SET, "args": args}), match)


def test_malformed_enabled_bakers_and_bake_steps_are_refused(sample_job: Job, repo: Path) -> None:
    bad_usage = {"call": SET_ENABLED, "args": {"usages": ["Normal", "Albedo"]}}
    refused(sample_job, repo, with_step(1, bad_usage), r"\['Albedo'\] are not MeshMapUsage")
    no_list = {"call": SET_ENABLED, "args": {"usages": "Normal"}}
    refused(sample_job, repo, with_step(1, no_list), "takes `usages`")
    refused(sample_job, repo, with_step(6, {"call": BAKE, "args": {"usage": "Normal"}}), "only an")


def test_bake_ordering_rules(sample_job: Job, repo: Path) -> None:
    # Baking settings after the last bake would not describe the baked maps.
    late = {"call": BAKING_SET, "args": {"parameter": "fake_size", "value": [4, 4]}}
    refused(sample_job, repo, with_step(7, late), "must precede the last bake_async")
    refused(
        sample_job,
        repo,
        with_step(7, {"call": SET_ENABLED, "args": {"usages": ["AO"]}}),
        "must precede the last bake_async",
    )
    # A bake is a state step: it cannot follow an export.
    refused(sample_job, repo, [*bake_steps(), {"call": BAKE, "args": {}}], "precede the captures")
    # The sequence still starts with project.create.
    steps = bake_steps()
    steps[0], steps[1] = steps[1], steps[0]
    refused(sample_job, repo, steps, "must start with project.create")


# --- file URL ---------------------------------------------------------------------------------


def test_file_url_matches_the_documented_qurl_form() -> None:
    windows = PureWindowsPath("C:/oracle-work/run_1/inputs/plane-high.obj")
    assert file_url(windows) == "file:///C:/oracle-work/run_1/inputs/plane-high.obj"
    posix = PurePosixPath("/srv/oracle-work/inputs/plane-high.obj")
    assert file_url(posix) == "file:///srv/oracle-work/inputs/plane-high.obj"


@pytest.mark.parametrize(
    "path",
    [
        PureWindowsPath("C:/Users/A B/work/plane-high.obj"),
        PureWindowsPath("C:/work/100%/plane-high.obj"),
        PureWindowsPath("C:/work/a#b/plane-high.obj"),
        PureWindowsPath("C:/work/caf\u00e9/plane-high.obj"),
        PureWindowsPath("work/plane-high.obj"),
    ],
)
def test_paths_needing_percent_encoding_are_refused(path: PureWindowsPath) -> None:
    with pytest.raises(RecorderError, match="percent-encoding"):
        file_url(path)


# --- recording --------------------------------------------------------------------------------


def test_bake_golden_is_recorded_with_readbacks_in_both_recordings(
    fake: types.ModuleType, make_session: MakeSession, bake_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    record = record_of(record_texture_golden(make_session(world), bake_job, work, inbox))
    key = record["key"]
    assert key["bake_backend"] is None
    assert key["effective_defaults"]["bakes"] == {
        "7": {
            "status": "Success",
            "texture_sets": [{"texture_set": "uzp_plane", "status": "Success"}],
            "enabled_bakers": {"uzp_plane": ["Normal"]},
        }
    }
    assert world.bakes == ["uzp_plane"]
    # The BakingProcessEnded handler was disconnected once the bake ended.
    assert world.event_handlers[fake.BakingProcessEnded] == []
    for recording in record["recordings"]:
        found = readbacks(recording)
        assert found["readback/value/fake_size"]["value"] == {"uzp_plane": [9, 9]}
        assert found["readback/value/fake_size"]["call"] == ps.GET_PROPERTY_VALUE
        # Enumeration labels are converted with the documented Property.enum_value.
        assert found["readback/value/fake_mode"]["value"] == {"uzp_plane": 1}
        assert found["readback/value/fake_filter/AO"]["value"] == {"uzp_plane": 1}
        assert found["readback/value/fake_filter/AO"]["args"] == {
            "parameter": "fake_filter",
            "usage": "AO",
        }
        (hipoly,) = found["readback/value/HipolyMesh"]["value"].values()
        assert hipoly.startswith("file:///") and hipoly.endswith("/inputs/plane-high.obj")
        assert found["readback/get_enabled_bakers"]["value"] == {"uzp_plane": ["Normal"]}
        assert found["readback/get_mesh_map_resource/Normal"]["value"] == {
            "uzp_plane": "resource://project0/baked_Normal"
        }
        (exported,) = [o for o in recording["outputs"] if o["kind"] == "exported_map"]
        assert exported["map"] == "normal_base"
        assert exported["storage_format"]["encoding"] == "linear"
        assert exported["export_settings"]["encoding_basis"] == "baked_mesh_map"
        assert exported["export_settings"]["map_type"] == "meshMap"
    assert not world.project_open


def test_unknown_enum_label_refuses_the_golden(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    repo: Path,
    work: Path,
    inbox: Path,
) -> None:
    steps = bake_steps()
    steps[2]["args"]["enum_label"] = "Third"
    job = job_from_manifest(bake_manifest(sample_job, repo, steps), repo_root=repo)
    world = fake.FakeWorld()
    with pytest.raises(RecorderError, match="apply_step"):
        record_texture_golden(make_session(world), job, work, inbox)
    assert not inbox.exists() and not world.project_open


def test_failed_bake_refuses_the_golden_and_names_the_status(
    fake: types.ModuleType, make_session: MakeSession, bake_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    world.bake_status = fake.BakingStatus.Fail
    with pytest.raises(RecorderError, match="step 7: the bake ended with status Fail"):
        record_texture_golden(make_session(world), bake_job, work, inbox)
    assert not inbox.exists() and not world.project_open
    assert world.event_handlers[fake.BakingProcessEnded] == []


def test_bake_that_never_ends_times_out(
    fake: types.ModuleType, bake_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    world.bake_polls = 10**9
    clock = Clock(step_s=120.0)
    session = PainterSession(
        fake.LocalTransport(world), sleep=clock.sleep, monotonic=clock.monotonic
    )
    with pytest.raises(RecorderError, match="timed out after 1800 s waiting for BakingProce"):
        record_texture_golden(session, bake_job, work, inbox)
    assert 1800.0 <= clock.now <= 1800.0 + 120.0
    assert not inbox.exists() and not world.project_open
    # Closing the throwaway project also disconnects the handler.
    assert world.event_handlers[fake.BakingProcessEnded] == []

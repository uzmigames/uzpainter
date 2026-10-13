"""Tier 0 API probes (`phase0.6_tier0-api-probes`): jobs, recording, provenance, admission, guard.

The recording tests run the probe recorder against the fake Painter (`fake_probe_painter.py`).
The admission test checks the recorded goldens in this machine's private store and skips with an
explicit reason where there is no store (decision 028).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tools.parity.guard.guard import load_index, run_guard, worktree_snapshot
from tools.parity.recorder.probes import (
    PAINTER_PROBES,
    ProbeJob,
    ProbeSession,
    load_probe_job,
    manifest_symbol_problems,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.recorder.provenance import check_files, recorder_sources
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, load_json, record_problems
from tools.parity.store.store import Status, locate, resolve_oracle

PROBE_DIR = REPO_ROOT / "parity" / "manifests" / "tier0" / "api-probes"
FIXTURE_DIR = REPO_ROOT / "parity" / "fixtures" / "api-probes"
MANIFESTS = sorted(PROBE_DIR.glob("*.json"))
LIFECYCLE = PROBE_DIR / "lifecycle-events.json"
API_MANIFESTS = [p for p in MANIFESTS if p != LIFECYCLE]
PROBE_FAKE = "uzp_recorder_fake_probe_painter"


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


def record_with_fake(
    probe_fake: types.ModuleType, fake: types.ModuleType, manifest: Path, tmp_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    world = probe_fake.ProbeWorld()
    session = ProbeSession(fake.LocalTransport(world), sleep=lambda seconds: None)
    run = record_probe_golden(
        session, load_probe_job(manifest), tmp_path / "work", tmp_path / "inbox"
    )
    record = json.loads((run / "record.json").read_text(encoding="utf-8"))
    run_manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    return record, run_manifest


def outputs_by_id(recording: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {output["output_id"]: output for output in recording["outputs"]}


def probe_output_ids(job: ProbeJob) -> list[str]:
    return [step.output_id for step in job.probe_steps]


# --- jobs ----------------------------------------------------------------------------------


def test_every_probe_manifest_is_a_valid_probe_job() -> None:
    assert len(MANIFESTS) == 9
    for path in MANIFESTS:
        job = load_probe_job(path)
        assert job.golden_id == f"tier0/api-probes/{path.stem}"
        assert job.lifecycle == (path == LIFECYCLE)
        assert job.lifecycle or job.probe_steps


def test_probe_ids_cover_the_required_quirks() -> None:
    names = {path.stem for path in MANIFESTS}
    assert {
        "fill-layer-readback",
        "mask-stack",
        "set-source-none-multichannel",
        "active-channel-reset",
        "active-channel-reset-superset",
        "active-channel-order-control",
        "insert-positions",
        "textureset-project-readback",
        "lifecycle-events",
    } == names


def edited(manifest: dict[str, Any], index: int, **changes: Any) -> dict[str, Any]:
    copy: dict[str, Any] = json.loads(json.dumps(manifest))
    copy["instruction_sequence"]["steps"][index].update(changes)
    return copy


def test_a_state_step_after_a_probe_step_is_refused() -> None:
    manifest = load_json(PROBE_DIR / "set-source-none-multichannel.json")
    steps = manifest["instruction_sequence"]["steps"]
    last = steps[-1]
    steps.append(
        {
            "step": last["step"] + 1,
            "call": "substance_painter.layerstack.Node.set_name",
            "args": {"node_step": 2, "name": "late"},
        }
    )
    with pytest.raises(RecorderError, match="state steps must precede the probe steps"):
        probe_job_from_manifest(manifest)


def test_a_call_outside_the_probe_vocabulary_is_refused() -> None:
    manifest = edited(
        load_json(PROBE_DIR / "mask-stack.json"), 1, call="substance_painter.project.secret"
    )
    with pytest.raises(RecorderError, match="not in the probe vocabulary"):
        probe_job_from_manifest(manifest)


def test_a_changed_lifecycle_procedure_is_refused() -> None:
    manifest = edited(load_json(LIFECYCLE), 3, call="substance_painter.project.save")
    with pytest.raises(RecorderError, match="lifecycle probe must be exactly"):
        probe_job_from_manifest(manifest)


def test_a_changed_fixture_is_refused(tmp_path: Path) -> None:
    manifest = load_json(PROBE_DIR / "mask-stack.json")
    for item in manifest["inputs"]:
        item["sha256"] = "0" * 64
    with pytest.raises(RecorderError, match="differs from the manifest"):
        probe_job_from_manifest(manifest)


# --- recording against the fake ----------------------------------------------------------


@pytest.mark.parametrize("manifest", API_MANIFESTS, ids=lambda p: p.stem)
def test_every_probe_is_recorded_twice(
    probe_fake: types.ModuleType, fake: types.ModuleType, manifest: Path, tmp_path: Path
) -> None:
    record, run_manifest = record_with_fake(probe_fake, fake, manifest, tmp_path)
    job = load_probe_job(manifest)
    assert record_problems(record) == []
    first, second = record["recordings"]
    assert (first["condition"], second["condition"]) == ("same_session", "after_save_reopen")
    for recording in (first, second):
        ids = outputs_by_id(recording)
        assert set(probe_output_ids(job)) <= set(ids)
        assert {f"identity/s{s}" for s in record["key"]["effective_defaults"]["inserted"]} <= set(
            ids
        )
        exported = [o for o in recording["outputs"] if o["kind"] == "exported_map"]
        assert len(exported) == sum(len(e.maps) for e in job.exports)
    state_ids = {step.output_id for step in job.state_steps}
    assert state_ids <= set(outputs_by_id(first))
    assert not state_ids & set(outputs_by_id(second))
    refs = run_manifest["private_records"]
    assert refs[0]["record_id"] == "golden-record"
    assert refs[-1]["kind"] == "oracle_environment_record"
    assert len(refs) == 2 + sum(len(e.maps) for e in job.exports) * 2


def test_reopened_nodes_are_found_again_and_uid_changes_are_recorded(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    record, _ = record_with_fake(probe_fake, fake, PROBE_DIR / "fill-layer-readback.json", tmp_path)
    first, second = (outputs_by_id(r) for r in record["recordings"])
    assert first["identity/s2"]["value"] == {
        "present": True,
        "uid_same_as_recorded": True,
        "uid_resolves_to_node": True,
    }
    # The fake gives every node a new uid on reopen; the probe still finds the node by place.
    assert second["identity/s2"]["value"] == {
        "present": True,
        "uid_same_as_recorded": False,
        "uid_resolves_to_node": True,
    }
    assert set(second["identity/reopen"]["value"]["found_by"].values()) == {"location"}
    assert first["s22/get_name"]["value"] == second["s22/get_name"]["value"] == "uzp fill A"
    assert second["s25/is_visible"]["value"] is True
    assert second["s26/is_visible"]["value"] is False
    parameters = first["s45/get_projection_parameters"]["value"]
    assert parameters["class"] == "UVProjectionParams"
    assert parameters["filtering_mode"] == "BilinearHQ"


def test_raised_exceptions_are_recorded_with_their_class(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    record, _ = record_with_fake(
        probe_fake, fake, PROBE_DIR / "set-source-none-multichannel.json", tmp_path
    )
    for recording in record["recordings"]:
        outputs = outputs_by_id(recording)
        assert outputs["s8/set_source"]["value"] is None
        assert outputs["s8/set_source"]["raised"]["type"] == "EditionContextException"
        assert outputs["s9/set_source"]["raised"]["type"] == "EditionContextException"
        assert outputs["s15/get_source"]["value"] == {"uniform_color_working": [0.2, 0.4, 0.6]}


def test_mask_stack_rules_are_recorded(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    record, _ = record_with_fake(probe_fake, fake, PROBE_DIR / "mask-stack.json", tmp_path)
    first = outputs_by_id(record["recordings"][0])
    defaults = record["key"]["effective_defaults"]["inserted"]
    assert defaults["6"]["source_mode"] is None
    assert defaults["13"]["levels"]["class"] == "LevelsParamsMono"
    assert "raised" not in first["s8/set_source"]
    assert first["s15/set_source"]["raised"]["type"] == "EditionContextException"
    assert first["s18/set_blending_mode"]["raised"]["type"] == "ValueError"
    assert first["s19/get_blending_mode"]["value"] == "Screen"
    assert first["s22/get_opacity"]["value"] == 0.75
    assert first["s31/get_blending_mode"]["raised"]["type"] == "ValueError"
    assert first["s37/add_mask"]["raised"]["type"] == "ValueError"
    assert first["s38/get_parameters"]["value"]["gamma"] == 1.2


def test_active_channel_assignment_after_set_source_is_recorded(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    reset, _ = record_with_fake(probe_fake, fake, PROBE_DIR / "active-channel-reset.json", tmp_path)
    control, _ = record_with_fake(
        probe_fake, fake, PROBE_DIR / "active-channel-order-control.json", tmp_path
    )
    # The fake clears sources on assignment (its authored rule); the recorder must show it.
    after_reset = outputs_by_id(reset["recordings"][1])["s8/get_source"]["value"]
    after_control = outputs_by_id(control["recordings"][1])["s7/get_source"]["value"]
    assert after_reset == {"uniform_color_working": [1.0, 1.0, 1.0]}
    assert after_control == {"uniform_color_working": [0.8, 0.3, 0.2]}
    reset_maps = [o["blob"]["sha256"] for o in reset["recordings"][0]["outputs"] if "blob" in o]
    control_maps = [o["blob"]["sha256"] for o in control["recordings"][0]["outputs"] if "blob" in o]
    assert reset_maps[0] != control_maps[0]


def test_insertion_errors_are_recorded_in_every_recording(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    record, _ = record_with_fake(probe_fake, fake, PROBE_DIR / "insert-positions.json", tmp_path)
    job = load_probe_job(PROBE_DIR / "insert-positions.json")
    inserts = [
        s.output_id for s in job.probe_steps if s.call.rsplit(".", 1)[1].startswith("insert")
    ]
    assert len(inserts) == 11
    for recording in record["recordings"]:
        outputs = outputs_by_id(recording)
        for output_id in inserts:
            assert outputs[output_id]["raised"]["type"] == "ValueError", output_id
    first, second = (outputs_by_id(r) for r in record["recordings"])
    root = "s24/get_root_layer_nodes"
    assert first[root]["value"] == second[root]["value"]


def test_a_node_missing_after_reopen_is_recorded_not_refused(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    class DroppingWorld(probe_fake.ProbeWorld):  # type: ignore[misc,name-defined]
        """Reopens without the content effects of groups (a node the project does not keep)."""

        def restore(self, data: dict[str, Any]) -> None:
            super().restore(data)
            for item in self.roots:
                if item.kind == probe_fake.NodeType.GroupLayer:
                    item.children["Content"] = []

    session = ProbeSession(fake.LocalTransport(DroppingWorld()), sleep=lambda seconds: None)
    manifest = PROBE_DIR / "insert-positions.json"
    run = record_probe_golden(
        session, load_probe_job(manifest), tmp_path / "work", tmp_path / "inbox"
    )
    record = json.loads((run / "record.json").read_text(encoding="utf-8"))
    second = outputs_by_id(record["recordings"][1])
    assert second["identity/reopen"]["value"]["found_by"]["12"] == "missing"
    assert second["identity/s12"]["value"] == {"present": False}
    assert second["identity/s2"]["value"]["present"] is True


def test_lifecycle_event_order_is_recorded_in_four_recordings(
    probe_fake: types.ModuleType, fake: types.ModuleType, tmp_path: Path
) -> None:
    record, _ = record_with_fake(probe_fake, fake, LIFECYCLE, tmp_path)
    assert record_problems(record) == []
    conditions = [r["condition"] for r in record["recordings"]]
    assert conditions == ["same_session", "after_save_reopen"] * 2
    for created, reopened in (record["recordings"][0:2], record["recordings"][2:4]):
        first, second = outputs_by_id(created), outputs_by_id(reopened)
        events = [e["event"] for e in first["create/events"]["value"]]
        assert events == ["ProjectCreated", "ProjectEditionEntered"]
        assert [e["event"] for e in second["open/events"]["value"]] == [
            "ProjectOpened",
            "ProjectEditionEntered",
        ]
        for phase in (first["save_as/events"], second["save/events"]):
            assert [e["event"] for e in phase["value"]] == ["ProjectAboutToSave", "ProjectSaved"]
        for phase in (first["close/events"], second["close/events"]):
            assert [e["event"] for e in phase["value"]] == [
                "ProjectAboutToClose",
                "ProjectEditionLeft",
                "ProjectClosed",
            ]
        states = first["create/states"]["value"]
        assert states[-1] == {"is_open": True, "in_edition": True, "busy": False}


# --- provenance (task 3.2) ---------------------------------------------------------------


def test_every_probe_call_is_a_documented_symbol() -> None:
    for path in MANIFESTS:
        assert manifest_symbol_problems(load_json(path)) == [], path.name


def test_probe_code_uses_documented_symbols_only() -> None:
    sources = [p for p in recorder_sources() if p.name in ("painter_probes.py", "probes.py")]
    assert [p.name for p in sources] == ["painter_probes.py", "probes.py"]
    assert PAINTER_PROBES in sources
    assert [str(problem) for problem in check_files(sources)] == []


# --- admission (task 3.1) and guard (task 3.3) -------------------------------------------


def test_every_probe_golden_is_admitted_with_two_recordings() -> None:
    """Each manifest names its private record, which resolves in the store and holds every probe
    in at least two recordings (same session; after save/reopen)."""
    for path in MANIFESTS:
        refs = load_json(path)["private_records"]
        assert refs and refs[0]["record_id"] == "golden-record", f"{path.name} is not admitted"
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (decision 028)")
    for path in MANIFESTS:
        manifest = load_json(path)
        for ref in manifest["private_records"]:
            assert resolve_oracle(store, ref).status == Status.AVAILABLE, (path.name, ref)
        data = store.load(manifest["private_records"][0]["sha256"])
        assert data is not None
        record = json.loads(data)
        assert record_problems(record) == []
        assert record["golden_id"] == manifest["golden_id"]
        recordings = record["recordings"]
        conditions = {r["condition"] for r in recordings}
        assert {"same_session", "after_save_reopen"} <= conditions
        job = load_probe_job(path)
        if job.lifecycle:
            for phase in ("create", "save_as", "close", "open", "save"):
                count = sum(f"{phase}/events" in outputs_by_id(r) for r in recordings)
                assert count >= 2, (path.name, phase)
            continue
        for output_id in probe_output_ids(job):
            count = sum(output_id in outputs_by_id(r) for r in recordings)
            assert count >= 2, (path.name, output_id)


def test_guard_passes_the_probe_manifests_and_fixtures() -> None:
    snapshot = worktree_snapshot(
        REPO_ROOT, ["parity/manifests/tier0/api-probes", "parity/fixtures/api-probes"]
    )
    assert len(snapshot.checked) == len(MANIFESTS) + len(list(FIXTURE_DIR.glob("*.png")))
    store = locate()
    index = None if store is None else load_index(store.root / "index.json")
    assert [str(f) for f in run_guard(REPO_ROOT, snapshot, index)] == []

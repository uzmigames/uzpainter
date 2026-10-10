"""Tier 0 baking-defaults and template captures (task phase0.6_tier0-defaults-templates).

Runs the recorder against the fake Painter (`fake_painter.py`, authored stand-in values): the
completeness of both captures (3.1), the public manifests (3.2), the store round trip with
`verify` and, on the owner's machine, `verify` of the committed manifests (3.3), and the guard
on a captured defaults JSON staged for commit (3.4).
"""

from __future__ import annotations

import copy
import json
import subprocess
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.guard.guard import run_guard, staged_snapshot
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.defaults import (
    capture_problems,
    check_template_job,
    record_baking_defaults,
    record_project_templates,
)
from tools.parity.recorder.job import Job, job_from_manifest, load_job
from tools.parity.recorder.session import PainterCallError, PainterSession, RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, load_json, record_problems, validation_errors
from tools.parity.store.cli import main as store_main
from tools.parity.store.store import STORE_ENV, OracleStore, default_root

MANIFESTS = REPO_ROOT / "parity" / "manifests" / "tier0" / "defaults-templates"
BAKING_MANIFEST = MANIFESTS / "baking-defaults.json"
TEMPLATES_MANIFEST = MANIFESTS / "project-templates.json"
MeshMapUsageNames = (
    "Normal",
    "WorldSpaceNormal",
    "ID",
    "AO",
    "Curvature",
    "Position",
    "Thickness",
    "Height",
    "BentNormals",
    "Opacity",
)
SHIPPED = ["templates/alpha.spt", "templates/beta/gamma.spt", "templates/refused.spt"]


@pytest.fixture
def baking_job() -> Job:
    return load_job(BAKING_MANIFEST)


@pytest.fixture
def shelf(tmp_path: Path) -> Path:
    """An authored application shelf: three templates and a file that is not one."""
    root = tmp_path / "shelf"
    for name in [*SHIPPED, "templates/readme.txt"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("authored stand-in\n", encoding="utf-8")
    return root


@pytest.fixture
def world(fake: types.ModuleType, shelf: Path) -> Any:
    world = fake.FakeWorld()
    world.shelf_path = shelf
    world.template_channels = {
        "alpha": {fake.ChannelType.BaseColor: fake.ChannelFormat.sRGB8},
        "gamma": {
            fake.ChannelType.BaseColor: fake.ChannelFormat.sRGB8,
            fake.ChannelType.Normal: fake.ChannelFormat.RGB16F,
        },
    }
    return world


def template_manifest(baking_job: Job, templates: list[str]) -> dict[str, Any]:
    manifest = copy.deepcopy(baking_job.manifest)
    manifest["golden_id"] = "tier0/defaults-templates/test-templates"
    manifest["instruction_sequence"]["steps"] = [
        {
            "step": i,
            "call": "substance_painter.project.create",
            "args": {"mesh": "plane", "template": t},
        }
        for i, t in enumerate(templates, start=1)
    ]
    return manifest


def read_run(run: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return load_json(run / "record.json"), load_json(run / "manifest.json")


def outputs_by_id(recording: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {o["output_id"]: o for o in recording["outputs"]}


def record_defaults(
    make_session: Callable[[Any], PainterSession], world: Any, job: Job, work: Path, inbox: Path
) -> Path:
    return record_baking_defaults(make_session(world), job, work, inbox)


# --- 2.1 / 3.1 baking defaults --------------------------------------------------------------


def test_vocabulary_names_the_ten_bakers() -> None:
    assert MeshMapUsageNames == ps.BAKER_USAGES


def test_committed_baking_job_captures_common_and_all_ten_bakers(baking_job: Job) -> None:
    (create,) = baking_job.state_steps
    assert create.call == ps.CREATE and create.args == {"mesh": "plane"}
    bakers = [s.args["usage"] for s in baking_job.captures if s.call == ps.BAKING_BAKER]
    assert sorted(bakers) == sorted(MeshMapUsageNames)
    assert [s.call for s in baking_job.captures].count(ps.BAKING_COMMON) == 1


def test_defaults_capture_holds_every_key_of_common_and_every_baker(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    run = record_defaults(make_session, world, baking_job, work, inbox)
    record, manifest = read_run(run)
    assert record_problems(record) == []
    assert [(r["recording_id"], r["condition"]) for r in record["recordings"]] == [
        ("r1", "same_session"),
        ("r2", "after_save_reopen"),
        ("r3", "same_session"),
    ]
    for recording in record["recordings"]:
        outputs = outputs_by_id(recording)
        groups = {"baking/common": "common"} | {f"baking/baker/{u}": u for u in MeshMapUsageNames}
        for output_id, group in groups.items():
            output = outputs[output_id]
            assert output["kind"] == "effective_default_capture"
            (captured,) = output["values"]["texture_sets"].values()
            assert captured["keys"] == sorted(world.baking[group])
            for key, described in captured["properties"].items():
                prop = world.baking[group][key]
                assert described["value"] == json.loads(json.dumps(described["value"]))
                assert described["short_name"] == prop.short_name()
                assert described["widget_type"] == prop.widget_type()
                assert {"name", "label", "properties", "enum_values"} <= set(described)
        assert outputs["baking/get_curvature_method"]["values"]["texture_sets"] == {
            world.texture_set: "FromMesh"
        }
        assert outputs["baking/get_enabled_bakers"]["values"]["texture_sets"] == {
            world.texture_set: ["AO", "Normal"]
        }
    assert [r["record_id"] for r in manifest["private_records"]] == ["golden-record"]


def test_enumeration_records_labels_with_their_enum_value(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    record, _ = read_run(record_defaults(make_session, world, baking_job, work, inbox))
    common = outputs_by_id(record["recordings"][0])["baking/common"]
    (captured,) = common["values"]["texture_sets"].values()
    mode = captured["properties"]["fake_mode"]
    assert mode["widget_type"] == "Combobox"
    assert mode["value"] == 1
    assert mode["enum_values"] == {"First": 0, "Second": 1}
    assert mode["enum_value"] == {"First": 0, "Second": 1}
    tint = captured["properties"]["fake_tint"]
    assert tint["value"] == {"working": [0.25, 0.5, 0.75]}


def test_a_raising_getter_is_recorded_not_dropped(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    def refuse() -> dict[str, Any]:
        raise RuntimeError("no meta properties")

    world.baking["AO"]["fake_strength"].properties = refuse
    record, _ = read_run(record_defaults(make_session, world, baking_job, work, inbox))
    ao = outputs_by_id(record["recordings"][1])["baking/baker/AO"]
    (captured,) = ao["values"]["texture_sets"].values()
    described = captured["properties"]["fake_strength"]
    assert "properties" not in described
    assert described["raised"]["properties"] == {
        "type": "RuntimeError",
        "message": "no meta properties",
    }


def test_incomplete_capture_is_refused() -> None:
    complete: dict[str, Any] = {
        "texture_sets": {
            "ts": {
                "keys": ["mode"],
                "properties": {
                    "mode": {
                        "value": 0,
                        "name": "n",
                        "short_name": "mode",
                        "label": "Mode",
                        "widget_type": "Combobox",
                        "enum_values": {"A": 0, "B": 1},
                        "enum_value": {"A": 0, "B": 1},
                        "properties": {},
                    }
                },
            }
        }
    }
    assert capture_problems("baking/common", complete) == []
    missing_key = copy.deepcopy(complete)
    missing_key["texture_sets"]["ts"]["keys"].append("size")
    assert capture_problems("baking/common", missing_key) == [
        "baking/common/ts: described keys differ from keys()"
    ]
    guessed = copy.deepcopy(complete)
    del guessed["texture_sets"]["ts"]["properties"]["mode"]["enum_value"]["B"]
    assert capture_problems("baking/common", guessed) == [
        "baking/common/ts/mode: enum_value() not read for ['B']"
    ]
    # Observed facts are recorded, not refused: an enumeration without labels, a baker
    # without parameters.
    unlabelled = copy.deepcopy(complete)
    unlabelled["texture_sets"]["ts"]["properties"]["mode"]["enum_values"] = {}
    del unlabelled["texture_sets"]["ts"]["properties"]["mode"]["enum_value"]
    assert capture_problems("x", unlabelled) == []
    assert capture_problems("x", {"texture_sets": {"ts": {"keys": [], "properties": {}}}}) == []
    unread = copy.deepcopy(complete)
    del unread["texture_sets"]["ts"]["properties"]["mode"]["label"]
    assert capture_problems("x", unread) == ["x/ts/mode: `label` neither read nor raised"]
    assert capture_problems("x", {"texture_sets": {}}) == ["x: no texture set captured"]


def test_job_missing_a_baker_is_refused_before_painter_is_touched(
    make_session: Callable[[Any], PainterSession],
    fake: types.ModuleType,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    manifest = copy.deepcopy(baking_job.manifest)
    steps = [
        s for s in manifest["instruction_sequence"]["steps"] if s.get("args") != {"usage": "AO"}
    ]
    for number, step in enumerate(steps, start=1):
        step["step"] = number
    manifest["instruction_sequence"]["steps"] = steps
    transport = fake.LocalTransport(fake.FakeWorld())
    with pytest.raises(RecorderError, match="baking/baker/AO"):
        record_baking_defaults(PainterSession(transport), job_from_manifest(manifest), work, inbox)
    assert transport.sent == []


def test_defaults_need_a_fresh_project(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    manifest = copy.deepcopy(baking_job.manifest)
    manifest["instruction_sequence"]["steps"][0]["args"]["normal_map_format"] = "DirectX"
    with pytest.raises(RecorderError, match="fresh project"):
        record_baking_defaults(make_session(world), job_from_manifest(manifest), work, inbox)


def test_texture_command_refuses_a_baking_job(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    from tools.parity.recorder.texture import record_texture_golden

    with pytest.raises(RecorderError):
        record_texture_golden(make_session(world), baking_job, work, inbox)


# --- 2.2 / 3.1 templates --------------------------------------------------------------------


def test_shipped_templates_are_the_spt_files_of_the_application_shelf(
    make_session: Callable[[Any], PainterSession], world: Any
) -> None:
    session = make_session(world)
    session.connect()
    assert session.call("shipped_templates") == {"templates": SHIPPED}


def test_template_capture_lists_every_shipped_template_twice(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    job = job_from_manifest(template_manifest(baking_job, SHIPPED))
    run = record_project_templates(make_session(world), job, work, inbox)
    record, manifest = read_run(run)
    assert record_problems(record) == []
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert [(r["recording_id"], r["condition"]) for r in record["recordings"]] == [
        ("r1", "same_session"),
        ("r2", "after_save_reopen"),
    ]
    for recording in record["recordings"]:
        outputs = outputs_by_id(recording)
        assert outputs["templates/shipped"]["values"] == {"templates": SHIPPED}
        assert set(outputs) == {
            "templates/shipped",
            *(f"templates/{t.replace('/', '-')}" for t in SHIPPED),
        }
        alpha = outputs["templates/templates-alpha.spt"]["values"]
        stacks = alpha["texture_sets"][world.texture_set]["stacks"]
        assert {k: v["format"] for k, v in stacks[""].items()} == {"BaseColor": "sRGB8"}
        gamma = outputs["templates/templates-beta-gamma.spt"]["values"]
        stacks = gamma["texture_sets"][world.texture_set]["stacks"]
        assert {k: v["format"] for k, v in stacks[""].items()} == {
            "BaseColor": "sRGB8",
            "Normal": "RGB16F",
        }
        refused = outputs["templates/templates-refused.spt"]["values"]
        assert refused["accepted"] is False
        assert refused["raised"]["type"] == "ValueError"
    assert world.project_open is False


def test_template_job_must_name_exactly_the_shipped_templates(
    fake: types.ModuleType, world: Any, baking_job: Job, work: Path, inbox: Path
) -> None:
    job = job_from_manifest(template_manifest(baking_job, SHIPPED[:2]))
    transport = fake.LocalTransport(world)
    with pytest.raises(RecorderError, match=r"templates/refused.spt"):
        record_project_templates(PainterSession(transport), job, work, inbox)
    assert not any("apply_step" in code for code in transport.sent)


def test_template_job_shape_is_checked(baking_job: Job) -> None:
    with pytest.raises(RecorderError, match="exports nothing"):
        check_template_job(baking_job)
    with_setting = template_manifest(baking_job, SHIPPED[:1])
    with_setting["instruction_sequence"]["steps"][0]["args"]["normal_map_format"] = "OpenGL"
    with pytest.raises(RecorderError, match="`mesh` and `template`"):
        check_template_job(job_from_manifest(with_setting))
    twice = template_manifest(baking_job, [SHIPPED[0], SHIPPED[0]])
    with pytest.raises(RecorderError, match="named twice"):
        check_template_job(job_from_manifest(twice))


@pytest.mark.parametrize(
    "identifier", ["../outside.spt", "/abs/x.spt", "templates/alpha.txt", "C:/x.spt", "a//b.spt"]
)
def test_template_identifier_outside_the_shelf_is_refused(
    make_session: Callable[[Any], PainterSession], world: Any, shelf: Path, identifier: str
) -> None:
    (shelf.parent / "outside.spt").write_text("authored\n", encoding="utf-8")
    session = make_session(world)
    session.connect()
    with pytest.raises(PainterCallError, match="ValueError"):
        session.call(
            "apply_step",
            step=1,
            call=ps.CREATE,
            args={"mesh": "plane", "template": identifier},
            resolved={"mesh": str(REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj")},
        )
    assert world.project_open is False


# --- 3.2 public manifests -------------------------------------------------------------------


@pytest.mark.parametrize("path", [BAKING_MANIFEST, TEMPLATES_MANIFEST], ids=lambda p: p.name)
def test_public_manifest_validates_and_holds_no_captured_value(path: Path) -> None:
    manifest = load_json(path)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["software"]["painter"]["build_id"] == "12.1.0+js-api.1.1.20"
    assert manifest["applied_settings"] == [] and manifest["expectations"] == []
    for ref in manifest["private_records"]:
        assert set(ref) == {"record_id", "kind", "sha256", "size_bytes"}
    job = load_job(path)
    if path == TEMPLATES_MANIFEST:
        assert check_template_job(job)
    for step in manifest["instruction_sequence"]["steps"]:
        assert set(step.get("args", {})) <= {"mesh", "usage", "template"}


def test_recorded_manifest_carries_hashes_but_no_captured_value(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    run = record_defaults(make_session, world, baking_job, work, inbox)
    text = (run / "manifest.json").read_text(encoding="utf-8")
    for captured in ("fake_size", "fake_mode", "Combobox", "FromMesh", "working"):
        assert captured not in text
    manifest = json.loads(text)
    stripped = {k: v for k, v in manifest.items() if k != "private_records"}
    assert stripped == {k: v for k, v in baking_job.manifest.items() if k != "private_records"}


# --- 3.3 store ------------------------------------------------------------------------------


def test_store_admits_the_run_and_verify_passes(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
) -> None:
    run = record_defaults(make_session, world, baking_job, work, inbox)
    store = OracleStore.init(tmp_path / "store")
    target = tmp_path / "manifests" / "baking-defaults.json"
    assert store_main(["--store", str(store.root), "record", str(target), "--run", str(run)]) == 0
    assert store_main(["--store", str(store.root), "verify", str(target)]) == 0
    manifest = load_json(target)
    (ref,) = manifest["private_records"]
    assert ref["kind"] == "private_oracle_record"
    assert ref["sha256"] in store.index()


def test_committed_manifests_verify_against_the_owners_store() -> None:
    """Owner's machine only (decision 028): every committed hash resolves in the real store."""
    root = default_root()
    if root is None or not (root / "store.json").is_file():
        pytest.skip("no private oracle store on this machine (hosted CI): oracle_unavailable")
    assert store_main(["--store", str(root), "verify", str(MANIFESTS)]) == 0


# --- 3.4 guard ------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def test_captured_defaults_json_staged_for_commit_is_rejected(
    make_session: Callable[[Any], PainterSession],
    world: Any,
    baking_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))
    run = record_defaults(make_session, world, baking_job, work, inbox)
    store = OracleStore.init(tmp_path / "store")
    target = tmp_path / "manifests" / "baking-defaults.json"
    assert store_main(["--store", str(store.root), "record", str(target), "--run", str(run)]) == 0
    record = (run / "record.json").read_bytes()
    capture = outputs_by_id(json.loads(record)["recordings"][0])["baking/common"]
    repo = tmp_path / "repo"
    repo.mkdir()
    assert git(repo, "init", "-q").returncode == 0
    staged = {
        "parity/manifests/tier0/defaults-templates/baking-defaults-record.json": record,
        "notes/baking-defaults.json": json.dumps(json.loads(record), indent=2).encode(),
        "parity/fixtures/defaults/common.json": json.dumps(capture["values"]).encode(),
    }
    for path, data in staged.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
        assert git(repo, "add", "--", path).returncode == 0
    found: dict[str, set[str]] = {}
    for finding in run_guard(repo, staged_snapshot(repo), frozenset(store.index())):
        found.setdefault(finding.path, set()).add(finding.rule)
    paths = list(staged)
    assert {"store-hash", "private-record"} <= found[paths[0]]
    assert "private-record" in found[paths[1]]
    assert "public-schema" in found[paths[2]]

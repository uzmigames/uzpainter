"""The recording-batch compiler (`tools/parity/recorder/batch.py`, decision 367 front C): pending
requests, offline validation, deduplication, priority, sessions and resume, on a small repository
tree under `tmp_path`. No Painter, no GPU, no private store."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import batch
from tools.parity.recorder.job import ASSETS3D_LICENCE
from tools.parity.schemas import REPO_ROOT

SAMPLE = REPO_ROOT / "parity/manifests/tier0/recorder-sample/blend-multiply-plane.json"
MESH = "parity/fixtures/meshes/plane.obj"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A repository with the real registry, the plane mesh and two rulebook tasks."""
    for relative in ("parity/envelopes/registry.json", MESH):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, tmp_path / relative)
    for task, open_items in (("phase1.25_pilot-wand", 2), ("phase3.4_baker-ao", 5)):
        path = tmp_path / ".rulebook" / "tasks" / task / "tasks.md"
        path.parent.mkdir(parents=True)
        path.write_text("- [x] 1.1 done\n" + "- [ ] 2.1 open\n" * open_items, encoding="utf-8")
    return tmp_path


def entry(root: Path) -> dict[str, Any]:
    return current_envelope(root)


def request(root: Path, name: str, *, colour: str | None = None, cites: str = "") -> dict[str, Any]:
    """A valid Tier 0 texture request of the current envelope, built from the recorder sample."""
    document: dict[str, Any] = json.loads(SAMPLE.read_text(encoding="utf-8"))
    current = entry(root)
    document["golden_id"] = f"tier0/semantics/{name}"
    document["description"] = f"Batch test request {name}. {cites}".strip()
    document["software"]["painter"].update(
        version=current["painter_version"], build_id=current["painter_build"]
    )
    document["private_records"] = []
    document["applied_settings"] = [
        s for s in document["applied_settings"] if not s["name"].startswith("export.")
    ] + [
        {"name": "export.png.bit_depth", "value": 16, "applied_by": "recorder_api"},
        {"name": "export.padding", "value": "infinite", "applied_by": "recorder_api"},
        {"name": "export.dithering", "value": False, "applied_by": "recorder_api"},
    ]
    if colour is not None:
        document["applied_settings"].append(
            {"name": "OCIO", "value": colour, "applied_by": "environment_variable"}
        )
    # A distinct colour per name, so that different names never share their content.
    digest = hashlib.sha256(name.encode()).digest()
    document["instruction_sequence"]["steps"][3]["args"]["color"] = [d / 255 for d in digest[:3]]
    return document


def requests_dir(root: Path) -> Path:
    return manifest_root(entry(root), root).parent / "requests"


def write(root: Path, document: dict[str, Any], family: str = "tier0/semantics") -> Path:
    path = requests_dir(root) / family / f"{document['golden_id'].rsplit('/', 1)[1]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def admit(root: Path, document: dict[str, Any], build: str | None = None) -> None:
    admitted = copy.deepcopy(document)
    admitted["software"]["painter"]["build_id"] = build or entry(root)["painter_build"]
    path = manifest_root(entry(root), root) / "tier0" / "semantics"
    path.mkdir(parents=True, exist_ok=True)
    name = document["golden_id"].rsplit("/", 1)[1]
    (path / f"{name}.json").write_text(json.dumps(admitted), encoding="utf-8")


def scheduled(plan: dict[str, Any]) -> list[str]:
    return [item["golden_id"] for s in plan["sessions"] for item in s["items"]]


def not_scheduled(plan: dict[str, Any]) -> dict[str, str]:
    return {row["request"].rsplit("/", 1)[1]: row["status"] for row in plan["not_scheduled"]}


def test_only_requests_without_a_current_admitted_manifest_are_scheduled(root: Path) -> None:
    write(root, request(root, "pending-one"))
    done = request(root, "admitted-one")
    write(root, done)
    admit(root, done)
    stale = request(root, "stale-one")
    write(root, stale)
    admit(root, stale, build="12.1.5+js-api.1.1.20")
    retained = request(root, "retained-one")
    write(root, retained, family="admitted/tier0/semantics")
    plan = batch.build_plan(root)
    assert plan["blocked"] == []
    assert sorted(scheduled(plan)) == ["tier0/semantics/pending-one", "tier0/semantics/stale-one"]
    assert plan["summary"]["requests"] == 3
    assert plan["summary"]["admitted"] == 1


def test_a_later_version_supersedes_and_identical_content_is_recorded_once(root: Path) -> None:
    write(root, request(root, "probe"))
    write(root, request(root, "probe-v2"))
    old = request(root, "other")
    write(root, old)
    admit(root, request(root, "other-v3"))
    twin = request(root, "probe-v2")
    twin["golden_id"] = "tier0/semantics/probe-x-copy"
    write(root, twin)
    plan = batch.build_plan(root)
    assert scheduled(plan) == ["tier0/semantics/probe-v2"]
    assert not_scheduled(plan) == {
        "probe.json": "superseded",
        "other.json": "superseded",
        "probe-x-copy.json": "duplicate",
    }


def test_one_golden_id_at_two_paths(root: Path) -> None:
    same = request(root, "twice")
    write(root, same)
    write(root, same, family="tier0/assets3d")
    assert not_scheduled(batch.build_plan(root)) == {"twice.json": "duplicate"}
    changed = copy.deepcopy(same)
    changed["description"] = "edited"
    write(root, changed, family="tier0/assets3d")
    plan = batch.build_plan(root)
    assert scheduled(plan) == []
    assert [row["status"] for row in plan["blocked"]] == ["conflict", "conflict"]
    assert plan["summary"]["blocked"] == 2


def test_an_invalid_copy_never_hides_a_valid_one(root: Path) -> None:
    valid = request(root, "kept")
    broken = copy.deepcopy(valid)
    broken["golden_id"] = "tier0/semantics/a-broken-copy"
    broken["inputs"][0]["sha256"] = "0" * 64
    write(root, broken)
    write(root, valid)
    plan = batch.build_plan(root)
    assert scheduled(plan) == ["tier0/semantics/kept"]
    assert [row["golden_id"] for row in plan["blocked"]] == ["tier0/semantics/a-broken-copy"]


def test_an_unreadable_request_is_blocked_without_stopping_the_batch(root: Path) -> None:
    write(root, request(root, "fine"))
    bad = requests_dir(root) / "tier0" / "semantics" / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    nested = request(root, "nested")
    nested["instruction_sequence"] = None
    write(root, nested)
    plan = batch.build_plan(root)
    assert scheduled(plan) == ["tier0/semantics/fine"]
    blocked = {row["request"].rsplit("/", 1)[1]: row["problems"][0] for row in plan["blocked"]}
    assert blocked["bad.json"].startswith("unreadable JSON")
    assert blocked["nested.json"].startswith("schema")


def test_a_recorded_run_of_a_conflicting_golden_is_not_admitted(root: Path, tmp_path: Path) -> None:
    one = request(root, "split")
    other = copy.deepcopy(one)
    other["description"] = "edited"
    write(root, one)
    write(root, other, family="tier0/assets3d")
    plan = batch.build_plan(root)
    row = next(r for r in plan["blocked"] if r["request"].endswith("semantics/split.json"))
    run = ready_run(tmp_path / "inbox", row, {**one, "private_records": [{}]}, "r")
    (run / "READY").write_text("", encoding="utf-8")
    report = batch.status(plan, tmp_path / "inbox", root)
    assert "recorded" in states(report)
    assert batch.next_action(plan, report) is None


def test_a_raw_export_needs_its_admitted_capability_golden(root: Path) -> None:
    item = batch.Item(
        batch.Request(
            Path("x"),
            "tier0/api-probes/ocio16-raw-readout-calibration-float-export-v3.json",
            {"golden_id": "tier0/api-probes/ocio16-raw-readout-calibration-float-export-v3"},
        ),
        kind=batch.RAW_EXPORT,
    )
    assert batch.capability_manifest(item, "m") == (
        "m/tier0/api-probes/ocio16-raw-readout-calibration-float-capability-v3.json"
    )
    assert batch.command(item, "r.json", "m")[-2:] == [
        "--capability-manifest",
        "m/tier0/api-probes/ocio16-raw-readout-calibration-float-capability-v3.json",
    ]
    assert batch.checkpoint(item, "m")["inbox_dir"] is None


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (lambda d: d["software"]["painter"].update(build_id="12.1.5+js-api.1.1.20"), "regenerate"),
        (lambda d: d["inputs"][0].update(sha256="0" * 64), "differs from the manifest"),
        (lambda d: d["applied_settings"].pop(), "export setting not in applied_settings"),
        (lambda d: d.update(golden_id="tier0/semantics/renamed"), "file name differs"),
        (lambda d: d["private_records"].append({}), "schema"),
        (lambda d: d["instruction_sequence"]["steps"].pop(0), "recorder job check"),
    ],
)
def test_an_invalid_request_is_reported_and_not_scheduled(
    root: Path, edit: Any, problem: str
) -> None:
    document = request(root, "broken")
    edit(document)
    path = requests_dir(root) / "tier0" / "semantics" / "broken.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    plan = batch.build_plan(root)
    assert scheduled(plan) == []
    (row,) = plan["blocked"]
    assert any(problem in p for p in row["problems"]), row["problems"]


def assets3d_request(root: Path, sha: str) -> dict[str, Any]:
    document = request(root, "export-padding-kernel-wand-2048")
    document["inputs"][0] = {
        "input_id": "plane",
        "kind": "mesh",
        "assets3d_path": "meshes/wand.obj",
        "sha256": sha,
        "provenance": {"origin": "uzmigames_authored", "licence": ASSETS3D_LICENCE},
    }
    return document


def test_assets3d_inputs_are_checked_by_hash_under_the_root(root: Path, tmp_path: Path) -> None:
    data = b"o wand\nv 0 0 0\n"
    assets = tmp_path / "assets3d"
    (assets / "meshes").mkdir(parents=True)
    (assets / "meshes" / "wand.obj").write_bytes(data)
    write(root, assets3d_request(root, hashlib.sha256(data).hexdigest()), "tier0/assets3d")
    plan = batch.build_plan(root, assets_root=assets)
    assert plan["blocked"] == []
    (item,) = plan["sessions"][0]["items"]
    assert item["command"][-2:] == ["--assets-root", batch.ASSETS]
    assert item["checkpoint"]["admitted_manifest"].endswith(
        "manifests/tier0/assets3d/export-padding-kernel-wand-2048.json"
    )
    (assets / "meshes" / "wand.obj").write_bytes(b"changed")
    (row,) = batch.build_plan(root, assets_root=assets)["blocked"]
    assert row["problems"][0].endswith(
        "differs from the pin (pass --store to accept the private store's copy)"
    )


class FakeStore:
    """Only `blob_path` is used, and only its existence is checked."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def blob_path(self, sha256: str) -> Path:
        return self.directory / sha256


def test_a_store_blob_of_the_pinned_hash_stands_in_for_a_missing_assets3d_file(
    root: Path, tmp_path: Path
) -> None:
    document = assets3d_request(root, "a" * 64)
    (tmp_path / "store").mkdir()
    store: Any = FakeStore(tmp_path / "store")
    assert batch.assets3d_problems(document, tmp_path, store) == [
        "input plane: meshes/wand.obj is missing"
    ]
    (tmp_path / "store" / ("a" * 64)).write_bytes(b"")
    assert batch.assets3d_problems(document, tmp_path, store) == []
    assert batch.assets3d_problems(document, None, None) == [
        "input plane: no --assets-root given (pass --store to accept the private store's copy)"
    ]


def test_wand_first_then_open_items_and_sessions_by_colour(root: Path) -> None:
    write(root, request(root, "plain"))
    write(root, request(root, "bakers", cites="phase3.4_baker-ao item 3.1"))
    write(root, request(root, "ocio-one", colour="C:/ocio/config.ocio"))
    write(root, request(root, "g1-probe", cites="phase1.25_pilot-wand item 2.7"))
    write(root, request(root, "wand-ring"))
    plan = batch.build_plan(root)
    assert plan["blocked"] == []
    legacy, ocio = plan["sessions"]
    assert [i["golden_id"].rsplit("/", 1)[1] for i in legacy["items"]] == [
        "g1-probe",
        "wand-ring",
        "bakers",
        "plain",
    ]
    assert [i["order"] for i in legacy["items"] + ocio["items"]] == [1, 2, 3, 4, 5]
    assert legacy["items"][0]["priority"] == {
        "class": "g1-wand",
        "cited_tasks": ["phase1.25_pilot-wand"],
        "open_items": 2,
    }
    assert legacy["items"][2]["priority"]["open_items"] == 5
    assert ocio["colour_management"] == "ocio"
    assert ocio["preamble"][0].startswith("close Painter first")
    assert ocio["preamble"][1] == '$env:OCIO = "C:/ocio/config.ocio"'
    assert "--request" in ocio["preamble"][3]
    assert plan["summary"]["scheduled_by_priority"] == {"g1-wand": 2, "open-items": 1, "other": 2}


def test_the_plan_holds_repository_paths_only(root: Path, tmp_path: Path) -> None:
    write(root, request(root, "export-padding-kernel-x"))
    plan = batch.build_plan(root)
    text = json.dumps(plan)
    assert str(tmp_path) not in text and str(tmp_path.as_posix()) not in text
    (item,) = plan["sessions"][0]["items"]
    assert (root / item["request"]).is_file()
    assert item["estimated_seconds"] == 8
    assert plan["summary"]["estimated_seconds"] == batch.SESSION_SECONDS[0] + 8


def ready_run(inbox: Path, item: dict[str, Any], manifest: dict[str, Any], name: str) -> Path:
    run = inbox / str(item["checkpoint"]["inbox_dir"]) / name
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


def states(report: dict[str, Any]) -> list[str]:
    return [row["state"] for row in report["rows"]]


def test_status_resumes_from_the_inbox(root: Path, tmp_path: Path) -> None:
    first = request(root, "first")
    write(root, first)
    write(root, request(root, "second"))
    inbox = tmp_path / "inbox"
    plan = batch.build_plan(root)
    item = plan["sessions"][0]["items"][0]
    recorded = {**first, "private_records": [{"record_id": "golden-record"}]}
    unfinished = ready_run(inbox, item, recorded, "20261102T000000Z-a")
    assert states(batch.status(plan, inbox, root)) == ["pending", "pending"]
    action = batch.next_action(plan, batch.status(plan, inbox, root))
    assert action is not None and action["action"] == "record"
    assert action["golden_id"] == "tier0/semantics/first"
    assert action["preamble"] == plan["sessions"][0]["preamble"]
    (unfinished / "READY").write_text("", encoding="utf-8")
    report = batch.status(plan, inbox, root)
    assert states(report) == ["recorded", "pending"]
    assert report["rows"][0]["run"] == str(unfinished)
    assert report["unmatched_runs"] == []
    action = batch.next_action(plan, report)
    assert action is not None and action["action"] == "admit"
    assert action["command"][-1] == str(unfinished)
    assert action["command"][4] == item["checkpoint"]["admitted_manifest"]
    edited = {**recorded, "description": "an earlier wording"}
    (unfinished / "manifest.json").write_text(json.dumps(edited), encoding="utf-8")
    report = batch.status(plan, inbox, root)
    assert states(report) == ["pending", "pending"]
    assert report["unmatched_runs"] == [str(unfinished)]


def test_a_recorded_run_of_a_blocked_request_is_still_admitted(root: Path, tmp_path: Path) -> None:
    document = assets3d_request(root, "b" * 64)
    write(root, document, "tier0/assets3d")
    plan = batch.build_plan(root)
    (row,) = plan["blocked"]
    run = ready_run(tmp_path / "inbox", row, {**document, "private_records": [{}]}, "r")
    (run / "READY").write_text("", encoding="utf-8")
    report = batch.status(plan, tmp_path / "inbox", root)
    assert states(report) == ["recorded"]
    action = batch.next_action(plan, report)
    assert action is not None and action["action"] == "admit"


@pytest.mark.parametrize(
    ("relative", "interface", "kind"),
    [
        ("tier0/semantics/a.json", "substance_painter_documented_python_api", batch.TEXTURE),
        ("tier0/assets3d/a.json", "substance_painter_documented_python_api", batch.TEXTURE),
        ("tier0/api-probes/p22b-x.json", "substance_painter_documented_python_api", batch.PROBE),
        (
            "tier0/api-probes/ocio16-raw-readout-calibration-float-export-v3.json",
            "substance_painter_documented_python_api",
            batch.RAW_EXPORT,
        ),
        (
            "tier0/api-probes/ocio16-raw-readout-normalization-png16-capability-v3.json",
            "substance_painter_documented_python_api",
            batch.RAW_CAPABILITY,
        ),
        ("tier0/api-probes/filter-context-a.json", "x", batch.FILTER_CONTEXT),
        ("tier0/defaults-templates/baking-defaults-plane-512.json", "x", batch.DEFAULTS),
        ("tier0/defaults-templates/template-pbr.json", "x", batch.TEMPLATES),
        ("phase2/tier1/sash-v5.json", "uzmigames_pipeline_scripts", batch.SCRIPT),
        ("phase2/tier1/tunic-v10-saved.json", "painter_project_migration", batch.MIGRATION),
        ("phase0/iray-references/plane.json", "substance_painter_documented_python_api", ""),
    ],
)
def test_each_family_routes_to_its_recorder_command(
    relative: str, interface: str, kind: str
) -> None:
    golden_id = relative.removesuffix(".json")
    manifest = {"golden_id": golden_id, "instruction_sequence": {"interface": interface}}
    assert batch.kind_of(batch.Request(Path(relative), relative, manifest)) == kind


def test_the_current_repository_compiles(tmp_path: Path) -> None:
    plan = batch.build_plan(REPO_ROOT, assets_root=tmp_path)
    for session in plan["sessions"]:
        for item in session["items"]:
            assert (REPO_ROOT / item["request"]).is_file()
    assert plan["schema"] == batch.PLAN_SCHEMA

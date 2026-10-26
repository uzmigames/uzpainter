"""Recipe A with F context boundaries through the real orchestration (`filter_context_run`,
`probes` hooks, trace reconstruction, contract) against an authored Painter: operations answer
with authored outcomes and the context reads execute the real extension. No Painter, no private
evidence; the authored values assert nothing about Painter."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tests.parity.test_painter_filter_context import Session as ContextSession
from tests.parity.test_painter_filter_context import World
from tools.parity.filter_context_contract import (
    A_RECIPE_SHA256,
    BOUNDARIES,
    MISSING_SETTINGS,
    ContextRefused,
    require_effective_settings,
    typed,
)
from tools.parity.recorder import environment
from tools.parity.recorder import filter_context_run as run
from tools.parity.recorder.filter_context import PAINTER_FILTER_CONTEXT
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import MANIFEST_FILE, READY_FILE, RECORD_FILE
from tools.parity.recorder.probes import probe_job_from_manifest, record_api_probe
from tools.parity.recorder.raw_capability_capture import CapabilityPolicy, Request
from tools.parity.recorder.session import (
    PainterIdentity,
    PainterSession,
    ProjectState,
    RecorderError,
)
from tools.parity.schemas import Schema, record_problems, validation_errors
from tools.parity.tier0_semantics import filter_context_control as control
from tools.parity.tier0_semantics import filter_context_settings_control as settings_control
from tools.parity.tier0_semantics.source_substance_control import booleans_filter_request

LEGACY = {"mode": "legacy", "OCIO": None, "PAINTER_ACE_CONFIG": None}


class Painter:
    """Authored operation answers; `filter_context_read` runs the real extension."""

    def __init__(self, fail: dict[Any, Any] | None = None) -> None:
        self.world = World()
        self.context = ContextSession(self.world)
        self.log: list[tuple[Any, ...]] = []
        self.open = False
        self.path: str | None = None
        self.fail: dict[Any, Any] = fail or {}

    def connect(self) -> PainterIdentity:
        self.log.append(("connect",))
        return PainterIdentity("12.2.0", (12, 2, 0), "1.1.20", "authored-session", LEGACY)

    def wait_ready(self) -> ProjectState:
        assert self.open
        return ProjectState(True, True, False, self.path, 0.0)

    def wait_closed(self) -> ProjectState:
        assert not self.open
        return ProjectState(False, False, False, None, 0.0)

    def wait_catalog_ready(self) -> None:
        self.log.append(("catalog",))

    def call(self, operation: str, **args: Any) -> Any:
        if operation == "filter_context_read":
            self.log.append(("context", args["boundary"]))
            if self.fail.get("context") == args["boundary"]:
                raise RecorderError("authored context transport failure")
            return self.context.call(operation, **args)
        if operation == "probe_step":
            self.log.append(("step", args["step"]))
            if args["step"] == 6:
                self.world.setup = True
            return deepcopy(self.fail.get(args["step"], {"value": None}))
        self.log.append((operation,))
        if operation == "apply_step":
            self.open = True
            return {"colour_management": LEGACY}
        if operation == "save_as":
            self.path = args["path"]
        if operation in ("close_project",):
            self.open = False
        if operation == "open_project":
            self.open = True
        if operation == "probe_locations":
            return {"3": {"uid": 20}, "6": {"uid": 30}}
        if operation == "probe_identity":
            # painter_probes.probe_identity of a kept node.
            return {"present": True, "uid_same_as_recorded": True, "uid_resolves_to_node": True}
        if operation == "probe_rebind":
            # painter_probes.probe_rebind when both inserted nodes are found at their places.
            return {"found_by": {"3": "location", "6": "location"}}
        if operation in ("probe_finish", "probe_cleanup"):
            return {"cleanup_failures": []}
        return {}


def recipe() -> dict[str, Any]:
    return cast(dict[str, Any], control.request()["instruction_sequence"])


def record_with(painter: Painter, tmp_path: Path) -> Path:
    job = probe_job_from_manifest(control.request())
    return run.record_filter_context_golden(
        cast(PainterSession, painter), job, tmp_path / "work", tmp_path / "inbox"
    )


def load(directory: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((directory / RECORD_FILE).read_bytes()))


@pytest.fixture
def recorded(tmp_path: Path) -> tuple[Painter, Path, dict[str, Any]]:
    painter = Painter()
    directory = record_with(painter, tmp_path)
    return painter, directory, load(directory)


def test_the_request_is_recipe_a_unchanged_under_its_own_identity() -> None:
    manifest = control.request()
    original = booleans_filter_request()
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert hashlib.sha256(typed(manifest["instruction_sequence"])).hexdigest() == A_RECIPE_SHA256
    assert manifest["instruction_sequence"] == original["instruction_sequence"]
    assert manifest["golden_id"] == control.GOLDEN_ID != original["golden_id"]
    assert manifest["uncontrolled_settings"] == list(MISSING_SETTINGS)
    rest = {k: v for k, v in manifest.items() if k not in ("golden_id", "description")}
    rest.pop("uncontrolled_settings")
    assert rest == {k: v for k, v in original.items() if k not in ("golden_id", "description")}


def test_boundaries_are_read_at_the_five_hooks(
    recorded: tuple[Painter, Path, dict[str, Any]],
) -> None:
    painter, _, _ = recorded
    log = painter.log
    order = [entry for entry in log if entry[0] in ("step", "context", "apply_step")]
    assert [e[1] for e in order if e[0] == "context"] == list(BOUNDARIES)
    assert order[0] == ("apply_step",) and order[1] == ("context", "after-create")
    assert order[2] == ("step", 2)
    assert order.index(("context", "after-setup6")) == order.index(("step", 6)) + 1
    r1_16 = order.index(("step", 16))
    assert order[r1_16 - 1] == ("context", "pre16-r1")
    r2_16 = len(order) - 1 - order[::-1].index(("step", 16))
    assert order[r2_16 - 1] == ("context", "pre16-r2")
    reopen = log.index(("context", "after-reopen"))
    assert log[reopen - 1] == ("probe_rebind",)
    assert ("open_project",) in log[:reopen] and ("step", 7) in log[reopen:]
    assert order.index(("step", 7)) > order.index(("context", "after-setup6"))
    steps = [e[1] for e in log if e[0] == "step"]
    assert steps == [*range(2, 7), *range(7, 25), *range(7, 25)]


def test_record_rebuilds_trace_and_frames_but_settings_stay_unverified(
    recorded: tuple[Painter, Path, dict[str, Any]],
) -> None:
    _, directory, record = recorded
    assert record_problems(record) == []
    assert run.check_capture(directory)["golden_id"] == control.GOLDEN_ID
    evidence = run.f_evidence_from_record(record, recipe())
    assert [frame["boundary"] for frame in evidence.contexts] == list(BOUNDARIES)
    assert evidence.initial_paint_uid == 10
    with pytest.raises(ContextRefused, match="F_EFFECTIVE_SETTINGS_UNVERIFIED"):
        require_effective_settings(evidence)
    lifecycle = [
        o["output_id"]
        for rec in record["recordings"]
        for o in rec["outputs"]
        if o["output_id"].startswith("lifecycle/")
    ]
    # The closed-state poll calls only is_open and is_busy; nothing else is recorded for it.
    assert [o for o in lifecycle if o.startswith("lifecycle/close/")] == [
        "lifecycle/close/is_open",
        "lifecycle/close/is_busy",
    ]
    assert {o.split("/")[1] for o in lifecycle} == {"create", "save", "close", "open"}


def test_without_hooks_the_probe_flow_is_unchanged(
    recorded: tuple[Painter, Path, dict[str, Any]], tmp_path: Path
) -> None:
    painter, _, record = recorded
    plain = Painter()
    manifest = control.request()
    job = probe_job_from_manifest(manifest)
    directory = record_api_probe(
        cast(PainterSession, plain),
        job,
        tmp_path / "plain-work",
        tmp_path / "plain-inbox",
        lambda: __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC),
        "",
    )
    plain_record = load(directory)
    added = ("context",)
    assert [e for e in painter.log if e[0] not in added] == [
        e for e in plain.log if e[0] not in added
    ]
    assert not any(e[0] == "context" for e in plain.log)

    def operations(rec: dict[str, Any]) -> list[list[Any]]:
        return [
            [
                (o["output_id"], o.get("value"))
                for o in recording["outputs"]
                if not o["output_id"].startswith(("context/", "lifecycle/"))
            ]
            for recording in rec["recordings"]
        ]

    assert operations(record) == operations(plain_record)


def mutate(record: dict[str, Any], change: str) -> None:
    r1, r2 = (recording["outputs"] for recording in record["recordings"])
    if change == "missing-boundary":
        r2[:] = [o for o in r2 if not o["output_id"].startswith("context/after-reopen/")]
    elif change == "late-boundary":
        leaves = [o for o in r1 if o["output_id"].startswith("context/pre16-r1/")]
        r1[:] = [o for o in r1 if o not in leaves]
        at = next(i for i, o in enumerate(r1) if o["output_id"].startswith("s16/"))
        r1[at + 1 : at + 1] = leaves
    elif change == "split-boundary":
        at = next(i for i, o in enumerate(r1) if o["output_id"].startswith("context/after-create/"))
        r1.insert(at + 1, deepcopy(next(o for o in r1 if o["output_id"].startswith("s2/"))))
    elif change == "repeated-step":
        at = next(i for i, o in enumerate(r2) if o["output_id"].startswith("s9/"))
        r2.insert(at, deepcopy(r2[at]))
    elif change == "unknown-output":
        r1.append({"output_id": "painting/stroke", "kind": "api_readback", "call": "x", "value": 1})
    elif change == "closed-still-open":
        next(o for o in r2 if o["output_id"] == "lifecycle/close/is_open")["value"] = True
    elif change == "opened-elsewhere":
        next(o for o in r2 if o["output_id"] == "lifecycle/open/file_path")["value"] = "other"
    elif change == "missing-create":
        r1[:] = [o for o in r1 if not o["output_id"].startswith("lifecycle/create/")]
    elif change == "setup-failed":
        step = next(o for o in r1 if o["output_id"].startswith("s4/"))
        step["value"], step["raised"] = None, {"type": "RuntimeError", "message": "authored"}
    elif change == "rebind-failed":
        rebind = next(o for o in r2 if o["output_id"] == "identity/reopen")
        rebind["value"], rebind["raised"] = None, {"type": "RuntimeError", "message": "authored"}
    elif change == "other-key":
        record["key"]["instruction_sequence_sha256"] = "0" * 64
    elif change == "other-golden":
        record["golden_id"] = booleans_filter_request()["golden_id"]
    elif change == "rounds-swapped":
        record["recordings"].reverse()
    elif change.startswith("identity-"):
        identity = next(o for o in r1 if o["output_id"] == "identity/s3")
        if change == "identity-other-call":
            identity["call"] = "substance_painter.layerstack.get_root_layer_nodes"
        elif change == "identity-not-kept":
            identity["value"]["uid_same_as_recorded"] = False
        elif change == "identity-missing":
            r2[:] = [o for o in r2 if o["output_id"] != "identity/s6"]
        elif change == "identity-extra-step":
            r1.insert(r1.index(identity), {**deepcopy(identity), "output_id": "identity/s4"})
        elif change == "identity-after-probe":
            r1.remove(identity)
            at = next(i for i, o in enumerate(r1) if o["output_id"].startswith("s7/"))
            r1.insert(at + 1, identity)
    elif change == "template-not-first":
        r1[0], r1[1] = r1[1], r1[0]
    elif change.startswith("rebind-"):
        rebind = next(o for o in r2 if o["output_id"] == "identity/reopen")
        if change == "rebind-other-args":
            rebind["args"] = {"node_step": 3}
        elif change == "rebind-found-by-uid":
            rebind["value"]["found_by"]["3"] = "uid"
    elif change.startswith("lifecycle-"):
        ids = [o["output_id"] for o in r2]
        if change == "lifecycle-other-args":
            r2[ids.index("lifecycle/save/is_open")]["args"] = {"path": "x"}
        elif change == "lifecycle-other-kind":
            r2[ids.index("lifecycle/close/is_busy")]["kind"] = "effective_default_capture"
        elif change == "lifecycle-order":
            a, b = ids.index("lifecycle/save/is_open"), ids.index("lifecycle/save/is_busy")
            r2[a], r2[b] = r2[b], r2[a]
        elif change == "lifecycle-split":
            moved = r2.pop(ids.index("lifecycle/save/file_path"))
            r2.insert([o["output_id"] for o in r2].index("identity/reopen") + 1, moved)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("missing-boundary", "F lifecycle differs"),
        ("late-boundary", "F lifecycle differs"),
        ("split-boundary", "F lifecycle differs"),
        ("repeated-step", "F lifecycle differs"),
        ("unknown-output", "unknown recorded operation"),
        ("closed-still-open", "close did not reach"),
        ("opened-elsewhere", "open did not reach"),
        ("missing-create", "creation or reopen readbacks missing"),
        ("setup-failed", "setup/reopen operation failed"),
        ("rebind-failed", "rebind readback differs"),
        ("other-key", "record key is not recipe A"),
        ("other-golden", "not the F context golden"),
        ("rounds-swapped", "one same-session and one reopened"),
        ("identity-other-call", "identity readback differs"),
        ("identity-not-kept", "identity readback differs"),
        ("identity-missing", "identity readbacks differ"),
        ("identity-extra-step", "identity readback differs"),
        ("identity-after-probe", "identity readback differs"),
        ("template-not-first", "template capture"),
        ("rebind-other-args", "rebind readback differs"),
        ("rebind-found-by-uid", "rebind readback differs"),
        ("lifecycle-other-args", "lifecycle readback differs"),
        ("lifecycle-other-kind", "lifecycle readback differs"),
        ("lifecycle-order", "lifecycle phase save"),
        ("lifecycle-split", "lifecycle phase save"),
    ],
)
def test_malformed_records_are_refused(
    recorded: tuple[Painter, Path, dict[str, Any]], change: str, reason: str
) -> None:
    _, _, record = recorded
    record = deepcopy(record)
    mutate(record, change)
    with pytest.raises(ContextRefused, match=reason):
        run.f_evidence_from_record(record, recipe())


def test_documented_refusals_are_kept_but_a_failed_setup_step_refuses(tmp_path: Path) -> None:
    refused = {"value": None, "raised": {"type": "ValueError", "message": "authored refusal"}}
    painter = Painter({19: refused, 20: refused})
    record = load(record_with(painter, tmp_path / "probe"))
    raised = [
        o["output_id"]
        for rec in record["recordings"]
        for o in rec["outputs"]
        if "raised" in o and not o["output_id"].startswith("context/")
    ]
    steps = {step["step"]: step["call"].rsplit(".", 1)[1] for step in recipe()["steps"]}
    assert raised == [f"s19/{steps[19]}", f"s20/{steps[20]}"] * 2
    run.f_evidence_from_record(record, recipe())
    failing = Painter({5: refused})
    record = load(record_with(failing, tmp_path / "setup"))
    with pytest.raises(ContextRefused, match="setup/reopen operation failed"):
        run.f_evidence_from_record(record, recipe())


def test_a_failed_context_read_cleans_up_and_writes_nothing(tmp_path: Path) -> None:
    painter = Painter({"context": "pre16-r1"})
    with pytest.raises(RecorderError, match="authored context transport failure"):
        record_with(painter, tmp_path)
    assert ("probe_cleanup",) in painter.log
    assert not (tmp_path / "inbox").exists() or not any((tmp_path / "inbox").rglob(READY_FILE))


def test_capture_check_needs_ready_and_the_named_record(
    recorded: tuple[Painter, Path, dict[str, Any]],
) -> None:
    _, directory, _ = recorded
    record = directory / RECORD_FILE
    record.write_bytes(record.read_bytes() + b" ")
    with pytest.raises(RecorderError, match="does not name"):
        run.check_capture(directory)
    (directory / READY_FILE).unlink()
    with pytest.raises(RecorderError, match="not READY"):
        run.check_capture(directory)


def rewrite(directory: Path, record: dict[str, Any]) -> None:
    """Replace the run's record and rehash the manifest's receipt for it."""
    data = canonical_json(record)
    (directory / RECORD_FILE).write_bytes(data)
    manifest = json.loads((directory / MANIFEST_FILE).read_bytes())
    for ref in manifest["private_records"]:
        if ref["kind"] == "private_oracle_record":
            ref["sha256"], ref["size_bytes"] = hashlib.sha256(data).hexdigest(), len(data)
    (directory / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("conditions-swapped", "two rounds"),
        ("third-round", "two rounds"),
        ("ids-swapped", "two rounds"),
        ("other-key", "record key is not recipe A"),
        ("manifest-recipe", "not the authored recipe A request"),
        ("manifest-schema", "public manifest invalid"),
        ("missing-blob", "run blob differs"),
        ("missing-empty-blob", "run blob differs"),
    ],
)
def test_capture_check_needs_two_complete_rounds_of_recipe_a(
    recorded: tuple[Painter, Path, dict[str, Any]], change: str, reason: str
) -> None:
    _, directory, record = recorded
    assert run.check_capture(directory)["recordings"] == 2
    record = deepcopy(record)
    manifest = json.loads((directory / MANIFEST_FILE).read_bytes())
    if change == "conditions-swapped":
        first, second = record["recordings"]
        first["condition"], second["condition"] = "after_save_reopen", "same_session"
    elif change == "third-round":
        record["recordings"].append({**deepcopy(record["recordings"][1]), "recording_id": "r3"})
    elif change == "ids-swapped":
        first, second = record["recordings"]
        first["recording_id"], second["recording_id"] = "r2", "r1"
    elif change == "other-key":
        record["key"]["instruction_sequence_sha256"] = "1" * 64
    elif change == "manifest-recipe":
        manifest["instruction_sequence"]["steps"][-1]["args"]["mode"] = "Custom"
    elif change == "manifest-schema":
        manifest["unreviewed"] = True
    elif change == "missing-empty-blob":
        empty = hashlib.sha256(b"").hexdigest()
        manifest["private_records"].append(
            {"record_id": "r1-empty", "kind": "exported_map", "sha256": empty, "size_bytes": 0}
        )
    elif change == "missing-blob":
        manifest["private_records"].append(
            {"record_id": "r1-extra", "kind": "exported_map", "sha256": "2" * 64, "size_bytes": 1}
        )
    assert record_problems(record) == []
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == [] or change == "manifest-schema"
    (directory / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")
    rewrite(directory, record)
    with pytest.raises(RecorderError, match=reason):
        run.check_capture(directory)


def test_other_jobs_are_refused_before_any_operation(tmp_path: Path) -> None:
    painter = Painter()
    job = probe_job_from_manifest(booleans_filter_request())
    with pytest.raises(RecorderError, match="not the F context golden"):
        run.record_filter_context_golden(
            cast(PainterSession, painter), job, tmp_path / "work", tmp_path / "inbox"
        )
    assert painter.log == []


def test_install_registers_the_context_operation_next_to_the_probes() -> None:
    world = World()
    probes = ContextSession(world).probes
    operations = probes["OPERATIONS"]
    operations.pop("filter_context_read", None)

    class Transport:
        def run(self, code: str) -> None:
            exec(code, {"uzp_probes": probes})

    run.install(cast(PainterSession, SimpleNamespace(transport=Transport())))
    assert "filter_context_read" in operations
    assert PAINTER_FILTER_CONTEXT.is_file()


def test_policy_prepares_only_the_authored_request(tmp_path: Path) -> None:
    manifest = tmp_path / "request.json"
    exe = tmp_path / "authored.exe"
    exe.write_bytes(b"not-executable")
    manifest.write_text(json.dumps(control.request()), encoding="utf-8")
    policy = run.FContextPolicy()
    job = policy.prepare(Request(control.NAME, manifest, exe, tmp_path / "capture"))
    assert job.golden_id == control.GOLDEN_ID
    with pytest.raises(Exception, match="unknown F capture"):
        policy.prepare(Request("calibration-float", manifest, exe, tmp_path / "capture"))
    changed = control.request()
    changed["description"] = "edited"
    manifest.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(Exception, match="authored request differs"):
        policy.prepare(Request(control.NAME, manifest, exe, tmp_path / "capture"))
    assert CapabilityPolicy.record is not run.FContextPolicy.record
    assert CapabilityPolicy.session is not run.FContextPolicy.session


def test_recorder_version_covers_the_injected_contract() -> None:
    environment.recorder_version.cache_clear()
    digest = hashlib.sha256()
    recorder = environment.RECORDER_DIR
    for path in [
        *sorted(recorder.glob("*.py")),
        recorder / "documented_symbols.json",
        recorder.parent / "tga.py",
        recorder.parent / "filter_context_contract.py",
        recorder.parent / "filter_context_settings.py",
    ]:
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    expected = f"{environment.RECORDER_VERSION}+src.{digest.hexdigest()[:16]}"
    assert environment.recorder_version() == expected


class Panels:
    """An authored settings panel reader: one panel and two image outputs per boundary, the image
    files written once inside the run directory; it records what the runner handed it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(
        self, boundary: str, frame: dict[str, Any], run_dir: Path, mesh_import: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[Path]]:
        self.calls.append((boundary, frame["boundary"], deepcopy(mesh_import)))
        outputs: list[dict[str, Any]] = [
            {
                "output_id": f"settings/{boundary}/panel",
                "kind": "settings_panel_readback",
                "panel": "Project Configuration",
                "values": {"schema": "authored", "boundary": boundary},
            }
        ]
        files = []
        for name in ("configuration-image", "physical-size-image"):
            path = run_dir / f"settings-{boundary}-{name}.png"
            with path.open("xb") as stream:
                stream.write(f"authored {boundary} {name}".encode())
            data = path.read_bytes()
            outputs.append(
                {
                    "output_id": f"settings/{boundary}/{name}",
                    "kind": "settings_panel_evidence",
                    "panel": "Project Configuration",
                    "blob": {
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data),
                        "media_type": "image/png",
                    },
                }
            )
            files.append(path)
        return outputs, files


def record_settings(tmp_path: Path) -> tuple[Painter, Panels, Path]:
    painter, panels = Painter({13: {"value": None}, 15: {"value": None}}), Panels()
    job = probe_job_from_manifest(settings_control.request())
    directory = run.record_filter_context_golden(
        cast(PainterSession, painter),
        job,
        tmp_path / "work",
        tmp_path / "inbox",
        settings_panel=panels,
    )
    return painter, panels, directory


def test_the_settings_golden_binds_a_panel_after_each_boundary(tmp_path: Path) -> None:
    painter, panels, directory = record_settings(tmp_path)
    assert run.check_capture(directory, settings_control)["golden_id"] == settings_control.GOLDEN_ID
    assert [call[0] for call in panels.calls] == list(BOUNDARIES)
    assert all(boundary == frame for boundary, frame, _ in panels.calls)
    staged = directory_of_inputs(tmp_path) / "plane.obj"
    expected = {
        "sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
        "size_bytes": len(staged.read_bytes()),
    }
    for _, _, packet in panels.calls:
        assert packet == {
            "input_id": "plane",
            "resolved_path": staged.as_posix(),
            "before": expected,
            "after": expected,
        }
    record = load(directory)
    for recording in record["recordings"]:
        ids = [o["output_id"] for o in recording["outputs"]]
        for boundary in BOUNDARIES:
            leaves = [i for i, oid in enumerate(ids) if oid.startswith(f"context/{boundary}/")]
            if not leaves:
                continue
            assert leaves == list(range(leaves[0], leaves[-1] + 1))
            assert ids[leaves[-1] + 1 : leaves[-1] + 4] == [
                f"settings/{boundary}/panel",
                f"settings/{boundary}/configuration-image",
                f"settings/{boundary}/physical-size-image",
            ]
    # The probes ran exactly as for filter-context-a.
    plain = [e for e in painter.log if e[0] != "context"]
    reference = Painter({13: {"value": None}, 15: {"value": None}})
    record_with(reference, tmp_path / "plain")
    assert plain == [e for e in reference.log if e[0] != "context"]


def test_the_historical_golden_never_reads_the_staged_mesh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(path: Path) -> dict[str, Any]:
        raise AssertionError("filter-context-a hashed the staged mesh")

    monkeypatch.setattr(run, "file_identity", refuse)
    directory = record_with(Painter(), tmp_path)
    assert run.check_capture(directory)["golden_id"] == control.GOLDEN_ID


def directory_of_inputs(tmp_path: Path) -> Path:
    runs = list((tmp_path / "work").rglob("inputs"))
    assert len(runs) == 1
    return runs[0]


def test_golden_and_panel_reader_must_match(tmp_path: Path) -> None:
    settings_job = probe_job_from_manifest(settings_control.request())
    plain_job = probe_job_from_manifest(control.request())
    for job, reader in ((settings_job, None), (plain_job, Panels())):
        painter = Painter()
        with pytest.raises(RecorderError, match="not the F context golden"):
            run.record_filter_context_golden(
                cast(PainterSession, painter),
                job,
                tmp_path / "work",
                tmp_path / "inbox",
                settings_panel=reader,
            )
        assert painter.log == []


def test_the_historical_parser_refuses_and_the_core_needs_the_exact_slots_removed(
    tmp_path: Path,
) -> None:
    _, _, directory = record_settings(tmp_path)
    record = load(directory)
    with pytest.raises(ContextRefused, match="not the F context golden"):
        run.f_evidence_from_record(record, recipe())
    with pytest.raises(ContextRefused, match="unknown recorded operation"):
        run._f_evidence_from_record(record, recipe(), expected_golden_id=settings_control.GOLDEN_ID)
    stripped = deepcopy(record)
    for recording in stripped["recordings"]:
        recording["outputs"] = [
            o for o in recording["outputs"] if not o["output_id"].startswith("settings/")
        ]
    evidence = run._f_evidence_from_record(
        stripped, recipe(), expected_golden_id=settings_control.GOLDEN_ID
    )
    assert [frame["boundary"] for frame in evidence.contexts] == list(BOUNDARIES)

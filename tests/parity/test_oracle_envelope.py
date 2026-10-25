"""Oracle envelope (task phase0.9_oracle-envelope; decisions 034 and 037) on the fake Painter.

Covers the environment record (schemas, recorder, back-fill), the registry and build guard,
the transactional refresh (complete run -> atomic promotion; build change mid-run -> abort and
quarantine; partial run -> previous envelope still current; same build under another
environment -> canary), the stability study (five recordings, classification, prepared register
entries) and the launcher. No real Painter is started.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
import types
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from tools.parity.envelope import canary as canary_module
from tools.parity.envelope import ocio as ocio_module
from tools.parity.envelope.backfill import backfill, manifest_environment
from tools.parity.envelope.canary import CANARY
from tools.parity.envelope.compare import RecordSource, normalise_text, normalised
from tools.parity.envelope.corpus import recorder_kind
from tools.parity.envelope.drift import DriftInput, golden_drift
from tools.parity.envelope.ocio import (
    OCIO_REFERENCE,
    detect_for_colour,
    named_ocio,
    ocio_reference_state,
    recorded_request_environment_matches,
)
from tools.parity.envelope.refresh import (
    CURRENT_OUTCOME,
    EQUIVALENT,
    INCOMPLETE,
    PROMOTED,
    detect,
    ensure_current,
)
from tools.parity.envelope.registry import (
    candidate_manifest_root,
    envelope_directory,
    envelope_id_for,
    initial_registry,
    load_registry,
    recordable_builds,
    registry_problems,
    save_registry,
)
from tools.parity.envelope.report import draft_problems, render, result_problems
from tools.parity.envelope.study import admit, load_study, new_study, publish, run_study
from tools.parity.feasibility import png
from tools.parity.recorder.environment import (
    ENVIRONMENT_KIND,
    UNKNOWN,
    colour_configuration_sha256,
    envelope_match,
    envelope_sha256,
    environment_bytes,
    environment_record,
    environment_sha256,
    recorder_version,
    video_controllers,
)
from tools.parity.recorder.job import job_from_manifest
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.output import RECORD_FILE, write_run
from tools.parity.recorder.session import (
    IdentityChanged,
    PainterSession,
    RecorderError,
    UnseenBuild,
)
from tools.parity.recorder.texture import file_url, record_texture_golden
from tools.parity.schemas import (
    REPO_ROOT,
    Schema,
    environment_problems,
    load_json,
    record_problems,
    validation_errors,
)
from tools.parity.store.manifest import record_run
from tools.parity.store.store import OracleStore, StoreError

SAMPLE = "parity/manifests/tier0/recorder-sample/blend-multiply-plane.json"
OLD_BUILD = "12.1.0+js-api.1.1.20"
HOST_A = {"gpu_model": "Fake GPU", "driver_version": "1.0", "os_build": "10.0.1.1"}
HOST_B = {"gpu_model": "Fake GPU", "driver_version": "2.0", "os_build": "10.0.1.1"}
FAKE_NAME = "uzp_recorder_fake_painter"


def load_fake() -> types.ModuleType:
    if FAKE_NAME in sys.modules:
        return sys.modules[FAKE_NAME]
    path = Path(__file__).parent / "recorder" / "fake_painter.py"
    spec = importlib.util.spec_from_file_location(FAKE_NAME, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[FAKE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake() -> types.ModuleType:
    return load_fake()


class Clock:
    """Strictly increasing UTC times (run names and study ids never collide)."""

    def __init__(self) -> None:
        self.time = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.time += timedelta(seconds=1)
        return self.time


def bump(fake: types.ModuleType, path: Path, delta: int = 1) -> None:
    """Rewrite an exported PNG with every value moved by `delta` codes."""
    values = png.decode(path.read_bytes())
    height, width, _ = values.shape
    pixels = [
        tuple(int(min(max(int(v) + delta, 0), 65535)) for v in values[y, x])
        for y in range(height)
        for x in range(width)
    ]
    fake.write_png(path, width, height, pixels)


def world(
    fake: types.ModuleType, version: str = "12.1.0", js_api: str = "1.1.20", hook: Any = None
) -> Any:
    w = fake.FakeWorld(export_hook=hook)
    w.version = version
    w.version_info = tuple(int(v) for v in version.split("."))
    w.js_api = js_api
    return w


class Painter:
    """A fake Painter installation: one FakeWorld per started process."""

    def __init__(self, fake: types.ModuleType, make_world: Callable[[int], Any]) -> None:
        self.fake = fake
        self.make_world = make_world
        self.starts = 0
        self.world: Any = None
        self.transport: Any = None
        self.process: Any = None

    def start_process(self, command: list[str]) -> Any:
        self.starts += 1
        self.world = self.make_world(self.starts)
        self.transport = self.fake.LocalTransport(self.world)
        self.process = FakeProcess()
        return self.process

    def answers(self) -> bool:
        return self.process is not None and self.process.alive

    def run(self, code: str) -> Any:  # the Transport protocol, bound to the live process
        return self.transport.run(code)


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.alive = True
        self.terminated = False

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.alive, self.terminated = False, True

    def kill(self) -> None:
        self.alive = False

    def wait(self, timeout: float | None = None) -> int:
        return 0


class Repo:
    """A throwaway repository root with the sample corpus admitted under the 12.1.0 envelope."""

    def __init__(self, tmp: Path, fake: types.ModuleType, goldens: int = 2) -> None:
        self.root = tmp / "repo"
        self.work = tmp / "work"
        self.inbox = tmp / "inbox"
        self.store = OracleStore.init(tmp / "store")
        self.fake = fake
        self.clock = Clock()
        for relative in ("parity/fixtures/meshes/plane.obj", "parity/exceptions.json"):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, target)
        save_registry(
            initial_registry(OLD_BUILD, "12.1.0", "parity/manifests", "2026-10-10"), self.root
        )
        template = load_json(REPO_ROOT / SAMPLE)
        template["private_records"] = []
        self.manifests: list[Path] = []
        for index in range(goldens):
            manifest = copy.deepcopy(template)
            manifest["golden_id"] = f"tier0/recorder-sample/plane-{index}"
            path = (
                self.root
                / "parity"
                / "manifests"
                / "tier0"
                / "recorder-sample"
                / f"plane-{index}.json"
            )
            session = self.session(world(fake), lambda: frozenset({OLD_BUILD}), HOST_A)
            job = job_from_manifest(manifest, self.root)
            run = record_texture_golden(
                session, job, self.work / "seed", self.inbox / "seed", self.clock
            )
            record_run(self.store, path, run)
            self.manifests.append(path)

    def session(
        self,
        w: Any,
        builds: Callable[[], frozenset[str]] | None = None,
        host: dict[str, str] | None = None,
        verify: bool = False,
    ) -> PainterSession:
        return PainterSession(
            self.fake.LocalTransport(w),
            sleep=lambda seconds: None,
            allowed_builds=builds or (lambda: recordable_builds(self.root)),
            host_environment=lambda: dict(host or HOST_A),
            verify_calls=verify,
        )

    def factory(self, transport: Any, host: Callable[[], dict[str, str]]) -> Any:
        def make(builds: Callable[[], frozenset[str]], verify: bool) -> PainterSession:
            return PainterSession(
                transport,
                sleep=lambda seconds: None,
                allowed_builds=builds,
                host_environment=host,
                verify_calls=verify,
            )

        return make

    def ensure(self, transport: Any, host: dict[str, str] = HOST_A, **kwargs: Any) -> Any:
        return ensure_current(
            self.factory(transport, lambda: dict(host)),
            self.store,
            self.work,
            self.inbox,
            now=self.clock,
            host=lambda: dict(host),
            repo_root=self.root,
            **kwargs,
        )

    def snapshot(self) -> dict[str, bytes]:
        return {p.as_posix(): p.read_bytes() for p in self.manifests}


@pytest.fixture
def repo(tmp_path: Path, fake: types.ModuleType) -> Repo:
    return Repo(tmp_path, fake)


# --- environment record -----------------------------------------------------------------------


def test_environment_record_is_schema_valid_and_never_guesses() -> None:
    record = environment_record(
        painter_build=OLD_BUILD, colour_management={"mode": "legacy", "OCIO": None}, host={}
    )
    assert environment_problems(record) == []
    assert {record[f] for f in ("gpu_model", "driver_version", "os_build")} == {UNKNOWN}
    assert record["recorder_version"] == recorder_version()
    assert recorder_version().startswith("uzp-recorder/1+src.")
    same = colour_configuration_sha256({"mode": "legacy", "OCIO": None})
    assert record["colour_configuration_sha256"] == same
    assert colour_configuration_sha256({"mode": "ocio", "OCIO": "C:/missing.ocio"}) != same
    assert environment_problems({**record, "gpu_model": ""}) != []
    assert environment_problems({**record, "extra": 1}) != []


def test_host_capture_records_unknown_rather_than_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def answering(stdout: str, code: int = 0) -> Callable[..., Any]:
        return lambda *a, **k: types.SimpleNamespace(returncode=code, stdout=stdout)

    two = json.dumps(
        [{"Name": "B GPU", "DriverVersion": "2"}, {"Name": "A GPU", "DriverVersion": "1"}]
    )
    assert video_controllers(answering(two)) == ("A GPU | B GPU", "1 | 2")
    assert video_controllers(answering("not json")) == (UNKNOWN, UNKNOWN)
    assert video_controllers(answering(two, code=1)) == (UNKNOWN, UNKNOWN)

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no powershell")

    assert video_controllers(failing) == (UNKNOWN, UNKNOWN)


def test_envelope_match_needs_every_field_known() -> None:
    base = environment_record(painter_build=OLD_BUILD, colour_management={}, host=HOST_A)
    assert envelope_match(base, dict(base)) == "match"
    assert envelope_match(base, {**base, "driver_version": "9"}) == "differs"
    assert envelope_match(base, {**base, "gpu_model": UNKNOWN}) == "unknown"
    assert envelope_match(base, {**base, "recorder_version": "other"}) == "match"
    assert envelope_match(None, base) == "unknown"


def test_private_record_environment_cross_checks() -> None:
    record = load_json(REPO_ROOT / "parity/schema/samples/private/exported-map-record.json")
    build = record["key"]["painter_build"]["build_id"]
    environment = environment_record(painter_build=build, colour_management={}, host=HOST_A)
    assert record_problems({**record, "environment": environment}) == []
    assert record_problems(record) == []  # optional: existing goldens stay valid
    wrong = {**record, "environment": {**environment, "painter_build": "other-build"}}
    assert any("key's build" in p for p in record_problems(wrong))
    operator = {**record, "environment": {**environment, "operator_id": "owner"}}
    assert any("Iray references only" in p for p in record_problems(operator))
    iray = load_json(REPO_ROOT / "parity/schema/samples/private/iray-reference-record.json")
    iray_env = environment_record(
        painter_build=iray["key"]["painter_build"]["build_id"], colour_management={}, host=HOST_A
    )
    assert any("operator_id" in p for p in record_problems({**iray, "environment": iray_env}))
    assert record_problems({**iray, "environment": {**iray_env, "operator_id": "owner"}}) == []


def test_public_manifest_names_the_environment_by_hash_and_any_painter_version() -> None:
    manifest = load_json(REPO_ROOT / SAMPLE)
    ref = {
        "record_id": "oracle-environment",
        "kind": ENVIRONMENT_KIND,
        "sha256": "0" * 64,
        "size_bytes": 1,
    }
    assert validation_errors({**manifest, "private_records": [ref]}, Schema.GOLDEN_PUBLIC) == []
    newer = copy.deepcopy(manifest)
    newer["software"]["painter"]["version"] = "12.1.5"
    assert validation_errors(newer, Schema.GOLDEN_PUBLIC) == []
    newer["software"]["painter"]["version"] = "12.1"
    assert validation_errors(newer, Schema.GOLDEN_PUBLIC) != []


def test_recorded_run_carries_the_environment_and_its_public_hash(repo: Repo) -> None:
    manifest = load_json(repo.manifests[0])
    env_refs = [r for r in manifest["private_records"] if r["kind"] == ENVIRONMENT_KIND]
    assert [r["record_id"] for r in env_refs] == ["oracle-environment"]
    record = json.loads(repo.store.load(manifest["private_records"][0]["sha256"]) or b"{}")
    assert record["environment"]["painter_build"] == OLD_BUILD
    assert record["environment"]["driver_version"] == HOST_A["driver_version"]
    assert env_refs[0]["sha256"] == environment_sha256(record["environment"])
    stored = repo.store.load(env_refs[0]["sha256"])
    assert stored is not None and hashlib.sha256(stored).hexdigest() == env_refs[0]["sha256"]
    assert "Fake GPU" not in repo.manifests[0].read_text(encoding="utf-8")


def test_backfill_appends_only_the_environment_reference(tmp_path: Path, repo: Repo) -> None:
    # A golden recorded before environment records existed: same record without `environment`.
    seed = next((repo.inbox / "seed").rglob(RECORD_FILE)).parent
    record = load_json(seed / RECORD_FILE)
    del record["environment"]
    template = load_json(REPO_ROOT / SAMPLE)
    template["private_records"] = []
    template["golden_id"] = record["golden_id"] = "tier0/recorder-sample/legacy"
    named = {o["blob"]["sha256"] for r in record["recordings"] for o in r["outputs"] if "blob" in o}
    blobs = [seed / "blobs" / name for name in sorted(named)]
    legacy = write_run(tmp_path / "legacy-inbox", record, blobs, template, "legacy")
    path = tmp_path / "legacy-manifests" / "legacy.json"
    record_run(repo.store, path, legacy)
    before = load_json(path)
    done = backfill(repo.store, [path], {"gpu_model": "Owner GPU"})
    after = load_json(path)
    assert [p for p, _ in done] == [path]
    assert after["private_records"][:-1] == before["private_records"]
    assert after["private_records"][-1]["record_id"] == "oracle-environment"
    assert {k: v for k, v in after.items() if k != "private_records"} == {
        k: v for k, v in before.items() if k != "private_records"
    }
    environment = done[0][1]
    assert environment["basis"] == "backfilled" and environment["gpu_model"] == "Owner GPU"
    assert environment["driver_version"] == UNKNOWN and environment["recorder_version"] == UNKNOWN
    assert environment["painter_build"] == OLD_BUILD
    assert environment["colour_configuration_sha256"] != UNKNOWN  # Legacy mode: no file named
    assert repo.store.load(after["private_records"][-1]["sha256"]) is not None
    assert backfill(repo.store, [path], {}) == []  # idempotent
    with pytest.raises(Exception, match="only"):
        backfill(repo.store, [repo.manifests[0]], {"recorder_version": "x"})


# --- registry and build guard -----------------------------------------------------------------


def test_repository_registry_is_valid_and_names_the_corpus_build() -> None:
    registry = load_registry()
    current = next(e for e in registry["envelopes"] if e["envelope_id"] == registry["current"])
    builds = {
        load_json(p)["software"]["painter"]["build_id"]
        for p in (REPO_ROOT / current["manifest_root"]).rglob("*.json")
    }
    assert builds == {current["painter_build"]}


def test_registry_rules() -> None:
    registry = initial_registry(OLD_BUILD, "12.1.0", "parity/manifests", "2026-10-10")
    assert registry_problems(registry) == []
    second = copy.deepcopy(registry["envelopes"][0])
    second["envelope_id"] = "painter-x"
    assert registry_problems({**registry, "envelopes": [*registry["envelopes"], second]}) != []
    candidate = {
        "envelope_id": "painter-12.1.5+js-api.1.1.21",
        "painter_build": "12.1.5+js-api.1.1.21",
        "painter_version": "12.1.5",
        "record_prefix": "",
        "envelope_sha256": "0" * 64,
        "previous": "painter-other",
        "started_on": "2026-10-11",
    }
    assert any(
        "refresh the current" in p for p in registry_problems({**registry, "candidate": candidate})
    )


def test_build_guard_admits_only_the_current_or_candidate_build(
    repo: Repo, fake: types.ModuleType
) -> None:
    newer = world(fake, "12.1.5", "1.1.21")
    with pytest.raises(UnseenBuild, match=r"12\.1\.5\+js-api\.1\.1\.21"):
        repo.session(newer).connect()
    found = detect(repo.session(newer), repo.root)
    assert found.state == "unseen_build"
    registry = load_registry(repo.root)
    registry["candidate"] = {
        "envelope_id": "painter-12.1.5+js-api.1.1.21",
        "painter_build": "12.1.5+js-api.1.1.21",
        "painter_version": "12.1.5",
        "record_prefix": "",
        "envelope_sha256": "0" * 64,
        "previous": registry["current"],
        "started_on": "2026-10-11",
    }
    save_registry(registry, repo.root)
    assert (
        repo.session(world(fake, "12.1.5", "1.1.21")).connect().build_id == "12.1.5+js-api.1.1.21"
    )
    with pytest.raises(UnseenBuild):
        repo.session(world(fake, "12.1.6", "1.1.22")).connect()


def test_identity_change_during_a_run_is_detected(repo: Repo, fake: types.ModuleType) -> None:
    w = world(fake)

    def update(path: Path) -> None:
        w.version, w.version_info, w.js_api = "12.1.5", (12, 1, 5), "1.1.21"

    w.export_hook = update
    session = repo.session(w, lambda: frozenset({OLD_BUILD}), verify=True)
    job = job_from_manifest(load_json(repo.manifests[0]) | {"private_records": []}, repo.root)
    with pytest.raises(IdentityChanged, match="changed during the run"):
        record_texture_golden(session, job, repo.work / "x", repo.inbox / "x", repo.clock)


# --- refresh transaction ----------------------------------------------------------------------


def test_complete_refresh_promotes_atomically_and_keeps_history(
    repo: Repo, fake: types.ModuleType
) -> None:
    before = repo.snapshot()
    newer = world(fake, "12.1.5", "1.1.21")
    outcome = repo.ensure(fake.LocalTransport(newer))
    assert outcome.outcome == PROMOTED
    registry = load_registry(repo.root)
    new_id = "painter-12.1.5+js-api.1.1.21"
    assert registry["current"] == new_id and registry["candidate"] is None
    old, new = registry["envelopes"]
    assert (old["status"], old["superseded_on"]) == ("superseded", "2026-10-11")
    assert new["previous"] == old["envelope_id"] and new["environment_known"]
    assert repo.snapshot() == before  # the previous envelope's manifests are history, unchanged
    promoted = sorted((repo.root / new["manifest_root"]).rglob("*.json"))
    assert len(promoted) == 2
    for path in promoted:
        manifest = load_json(path)
        assert manifest["software"]["painter"]["build_id"] == "12.1.5+js-api.1.1.21"
        assert {r["kind"] for r in manifest["private_records"]} >= {ENVIRONMENT_KIND}
    drift = load_json(repo.root / new["drift_report"])
    assert result_problems(drift) == []
    assert drift["scope"] == "corpus" and drift["summary"]["unchanged"] == 2
    assert drift["divergence_candidates"] == [] and not drift["new_evaluator_profile_needed"]
    assert recordable_builds(repo.root) == frozenset({"12.1.5+js-api.1.1.21"})
    # A candidate's run can never be admitted under the previous envelope's build.
    inbox = repo.inbox / "envelopes" / envelope_directory(new_id)
    run = next((inbox / "tier0__recorder-sample__plane-0").rglob(RECORD_FILE)).parent
    with pytest.raises(StoreError, match="build differs"):
        record_run(repo.store, repo.manifests[0], run)
    assert "painter-12.1.5+js-api.1.1.21" in render(repo.root)
    # Detection now sees the current envelope; the old build is superseded and refused.
    assert (
        repo.ensure(fake.LocalTransport(world(fake, "12.1.5", "1.1.21"))).outcome == CURRENT_OUTCOME
    )
    with pytest.raises(RecorderError, match="superseded envelope"):
        repo.ensure(fake.LocalTransport(world(fake)))


def test_build_change_mid_refresh_aborts_quarantines_and_restarts(
    repo: Repo, fake: types.ModuleType
) -> None:
    w = world(fake, "12.1.5", "1.1.21")
    flipped: list[bool] = []

    def update(path: Path) -> None:
        if not flipped:
            flipped.append(True)
            w.version, w.version_info, w.js_api = "12.1.6", (12, 1, 6), "1.1.22"

    w.export_hook = update
    outcome = repo.ensure(fake.LocalTransport(w))
    registry = load_registry(repo.root)
    assert outcome.outcome == PROMOTED and registry["current"] == "painter-12.1.6+js-api.1.1.22"
    (quarantined,) = registry["quarantine"]
    assert quarantined["envelope_id"] == "painter-12.1.5+js-api.1.1.21"
    assert "changed" in quarantined["reason"]
    kept = repo.work / "quarantine" / "painter-12.1.5_js-api.1.1.21"
    assert (kept / "work" / "candidate.json").is_file() and (kept / "work" / "runs").is_dir()
    assert not (repo.root / "parity" / "envelopes" / "painter-12.1.5_js-api.1.1.21").exists()


def test_abort_without_restart_leaves_the_previous_envelope_current(
    repo: Repo, fake: types.ModuleType
) -> None:
    w = world(fake, "12.1.5", "1.1.21")

    def update(path: Path) -> None:
        w.version, w.version_info, w.js_api = "12.1.6", (12, 1, 6), "1.1.22"

    w.export_hook = update
    with pytest.raises(RecorderError, match="aborted 1 times"):
        repo.ensure(fake.LocalTransport(w), max_restarts=0)
    registry = load_registry(repo.root)
    assert registry["current"] == f"painter-{OLD_BUILD}" and registry["candidate"] is None
    assert [q["painter_build"] for q in registry["quarantine"]] == ["12.1.5+js-api.1.1.21"]


def test_partial_refresh_keeps_the_previous_envelope_and_resumes(
    repo: Repo, fake: types.ModuleType
) -> None:
    w = world(fake, "12.1.5", "1.1.21")
    exports: list[Path] = []

    def fail_second_golden(path: Path) -> None:
        exports.append(path)
        if len(exports) == 3:
            raise RuntimeError("export failed")

    w.export_hook = fail_second_golden
    transport = fake.LocalTransport(w)
    outcome = repo.ensure(transport)
    assert outcome.outcome == INCOMPLETE and "refused" in outcome.message
    registry = load_registry(repo.root)
    assert registry["current"] == f"painter-{OLD_BUILD}"
    assert registry["candidate"]["envelope_id"] == "painter-12.1.5+js-api.1.1.21"
    ledger = load_json(repo.work / "envelopes" / "painter-12.1.5_js-api.1.1.21" / "candidate.json")
    first = ledger["goldens"]["tier0/recorder-sample/plane-0"]["run"]
    w.export_hook = None
    assert repo.ensure(transport).outcome == PROMOTED
    ledger = load_json(repo.work / "envelopes" / "painter-12.1.5_js-api.1.1.21" / "candidate.json")
    assert (
        ledger["goldens"]["tier0/recorder-sample/plane-0"]["run"] == first
    )  # resumed, not re-recorded
    assert load_registry(repo.root)["current"] == "painter-12.1.5+js-api.1.1.21"


def test_envelope_directories_pass_the_file_url_rule(tmp_path: Path) -> None:
    """A Painter build string holds `+`; paths named after its envelope must still give a bake's
    staged mesh a file URL without percent-encoding (the recorder refuses one that needs it)."""
    envelope_id = "painter-12.1.5+js-api.1.1.20"
    directory = envelope_directory(envelope_id)
    assert directory == "painter-12.1.5_js-api.1.1.20"
    assert candidate_manifest_root(envelope_id) == f"parity/envelopes/{directory}/manifests"
    staged = Path(
        "runs", "phase0__normal-convention__hemisphere-0", "inputs", "hemisphere-high.obj"
    )
    for root in (tmp_path / "work", tmp_path / "inbox"):
        file_url(root / "envelopes" / directory / staged)
        file_url(root / "quarantine" / directory / staged)
    file_url(REPO_ROOT / candidate_manifest_root(envelope_id) / "tier0" / "x.json")
    with pytest.raises(RecorderError, match="percent-encoding"):
        file_url(tmp_path / "work" / "envelopes" / envelope_id / staged)
    # No two envelopes of one registry share a directory.
    registry = initial_registry(OLD_BUILD, "12.1.0", "parity/manifests", "2026-10-10")
    registry["quarantine"].append(
        {
            "envelope_id": "painter-12.1.5_js-api.1.1.20",
            "painter_build": "12.1.5_js-api.1.1.20",
            "reason": "x",
            "quarantined_on": "2026-10-11",
        }
    )
    minted = envelope_id_for("12.1.5+js-api.1.1.20", dict(HOST_A), registry)
    assert minted.startswith(f"{envelope_id}-env-") and envelope_directory(minted) != directory


def test_open_candidate_without_a_ledger_in_its_directory_starts_there(
    repo: Repo, fake: types.ModuleType
) -> None:
    """A candidate entered before ids were mapped to directories (its ledger under the raw id)
    is recorded afresh in its directory; the raw-id directory is left as it is."""
    candidate_id = "painter-12.1.5+js-api.1.1.21"
    w = world(fake, "12.1.5", "1.1.21")
    found = detect(repo.session(w), repo.root)
    assert found.identity.environment is not None
    registry = load_registry(repo.root)
    registry["candidate"] = {
        "envelope_id": candidate_id,
        "painter_build": "12.1.5+js-api.1.1.21",
        "painter_version": "12.1.5",
        "record_prefix": "",
        "envelope_sha256": envelope_sha256(found.identity.environment),
        "previous": registry["current"],
        "started_on": "2026-10-11",
    }
    save_registry(registry, repo.root)
    raw = repo.work / "envelopes" / candidate_id
    raw.mkdir(parents=True)
    old_ledger = {"envelope_id": candidate_id, "goldens": {}}
    (raw / "candidate.json").write_text(json.dumps(old_ledger), encoding="utf-8")
    assert repo.ensure(fake.LocalTransport(w)).outcome == PROMOTED
    assert load_registry(repo.root)["current"] == candidate_id
    ledger = load_json(
        repo.work / "envelopes" / envelope_directory(candidate_id) / "candidate.json"
    )
    assert ledger["envelope_id"] == candidate_id and len(ledger["goldens"]) == 2
    assert load_json(raw / "candidate.json") == old_ledger


def test_same_build_other_environment_runs_the_canary(
    repo: Repo, fake: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic envelope change (driver update) on the fake Painter, task item 4.2."""
    monkeypatch.setattr(
        canary_module,
        "CANARY",
        tuple((f"tier0/recorder-sample/plane-{i}", "sample") for i in range(2)),
    )
    before = repo.snapshot()
    stored_before = sorted(p.name for p in (repo.store.root / "blobs").rglob("*") if p.is_file())
    # Driver 2.0, identical outputs: the environment is recorded as equivalent.
    outcome = repo.ensure(fake.LocalTransport(world(fake)), host=HOST_B)
    assert outcome.outcome == EQUIVALENT
    current = load_registry(repo.root)["envelopes"][0]
    assert len(current["equivalent_envelopes"]) == 1
    assert repo.ensure(fake.LocalTransport(world(fake)), host=HOST_B).outcome == CURRENT_OUTCOME
    # Driver 3.0 and one value off on every export: canary drift, then a full re-record.
    host_c = {**HOST_A, "driver_version": "3.0"}
    outcome = repo.ensure(
        fake.LocalTransport(world(fake, hook=lambda p: bump(fake, p))), host=host_c
    )
    assert outcome.outcome == PROMOTED
    registry = load_registry(repo.root)
    new = next(e for e in registry["envelopes"] if e["status"] == "current")
    assert new["envelope_id"].startswith(f"painter-{OLD_BUILD}-env-")
    assert new["record_prefix"] == "env-2-" and new["painter_build"] == OLD_BUILD
    drift = load_json(repo.root / new["drift_report"])
    assert drift["divergence_candidates"] == [f"tier0/recorder-sample/plane-{i}" for i in range(2)]
    changed = drift["goldens"][0]
    assert changed["status"] == "changed" and changed["changed_recordings"] == ["r1", "r2"]
    assert changed["differing_outputs"][0]["difference"]["max"] == 1
    canary = sorted(
        (repo.root / "parity" / "reports" / "phase0").glob("oracle-envelope-drift-canary-*.json")
    )
    assert canary and all(result_problems(load_json(p)) == [] for p in canary)
    # The originals stay: their manifests, records and blobs are untouched.
    assert repo.snapshot() == before
    stored_after = {p.name for p in (repo.store.root / "blobs").rglob("*") if p.is_file()}
    assert set(stored_before) <= stored_after
    promoted = load_json(next((repo.root / new["manifest_root"]).rglob("*.json")))
    assert all(r["record_id"].startswith("env-2-") for r in promoted["private_records"])


# --- stability study --------------------------------------------------------------------------


def run_fake_study(
    tmp_path: Path, repo: Repo, fake: types.ModuleType, make_world: Callable[[int], Any]
) -> Any:
    painter = Painter(fake, make_world)
    launcher = PainterLauncher(
        Path("painter.exe"),
        popen=painter.start_process,
        answers=painter.answers,
        sleep=lambda s: None,
    )
    current = load_registry(repo.root)["envelopes"][0]
    study = new_study(repo.manifests, repo.work, current, repo.clock(), repo.root)

    def make() -> PainterSession:
        return PainterSession(
            painter,
            sleep=lambda seconds: None,
            allowed_builds=lambda: frozenset({OLD_BUILD}),
            host_environment=lambda: dict(HOST_A),
            verify_calls=True,
        )

    run_study(study, launcher, make, repo.inbox, repo.clock, lambda: dict(HOST_A), repo.root)
    assert painter.starts == 2 and not painter.process.alive
    return study, publish(study, repo.clock().date(), repo.root)


def test_stable_study_records_five_recordings_per_golden(
    tmp_path: Path, repo: Repo, fake: types.ModuleType
) -> None:
    exceptions = (repo.root / "parity" / "exceptions.json").read_bytes()
    study, results = run_fake_study(tmp_path, repo, fake, lambda n: world(fake))
    assert result_problems(results) == []
    assert results["summary"]["stable"] == 2
    golden = results["goldens"][0]
    assert [r["role"] for r in golden["runs"]] == ["a", "b", "c"]
    assert (
        golden["runs"][0]["session"] == golden["runs"][1]["session"] != golden["runs"][2]["session"]
    )
    categories = sorted((p["left"], p["right"], p["category"]) for p in golden["pairs"])
    assert categories == [
        ("a.r1", "a.r2", "save_reopen"),
        ("a.r1", "b.r1", "same_session"),
        ("a.r1", "c.r1", "fresh_process"),
        ("b.r1", "b.r2", "save_reopen"),
        ("c.r1", "c.r2", "save_reopen"),
    ]
    assert not (
        repo.root / "parity" / "reports" / "phase0" / "oracle-envelope-register-drafts.json"
    ).exists()
    assert (repo.root / "parity" / "exceptions.json").read_bytes() == exceptions
    before = repo.snapshot()
    admitted = admit(study, repo.store, repo.root)
    assert len(admitted) == 6 and repo.snapshot() == before
    study_manifest = load_json(
        study.directory / "manifests" / "tier0" / "recorder-sample" / "plane-0.json"
    )
    ids = [r["record_id"] for r in study_manifest["private_records"]]
    assert all(i.startswith(f"study-{study.study_id}-") for i in ids)
    assert load_study(study.directory).ledger == study.ledger


def test_fresh_process_instability_is_classified_and_its_entry_prepared(
    tmp_path: Path, repo: Repo, fake: types.ModuleType
) -> None:
    exceptions = (repo.root / "parity" / "exceptions.json").read_bytes()
    _, results = run_fake_study(
        tmp_path,
        repo,
        fake,
        lambda n: world(fake, hook=(lambda p: bump(fake, p, 3)) if n == 2 else None),
    )
    assert results["summary"]["fresh-process-unstable"] == 2
    golden = results["goldens"][0]
    fresh = [p for p in golden["pairs"] if p["category"] == "fresh_process"]
    assert fresh[0]["status"] == "differs" and fresh[0]["worst_map"]["max"] == 3
    drafts = load_json(
        repo.root / "parity" / "reports" / "phase0" / "oracle-envelope-register-drafts.json"
    )
    assert result_problems(drafts) == [] and drafts["status"] == "prepared_unapproved"
    assert len(drafts["drafts"]) == 2
    for draft in drafts["drafts"]:
        assert "approved_by" not in draft and "approved_on" not in draft
        assert draft_problems(draft) == []
        assert draft["decision_id"] == "034"
        assert {b["metric"]: b["max"] for b in draft["bounds"]}["max_abs_diff"] == 3
    assert draft_problems({**drafts["drafts"][0], "approved_by": "owner"}) != []
    assert (repo.root / "parity" / "exceptions.json").read_bytes() == exceptions  # never edited
    assert "fresh-process-unstable" in render(repo.root)


def test_save_reopen_instability_is_classified_apart(
    tmp_path: Path, repo: Repo, fake: types.ModuleType
) -> None:
    def make(n: int) -> Any:
        w = world(fake)
        w.export_hook = lambda p: bump(fake, p) if w.file_path is not None else None
        return w

    _, results = run_fake_study(tmp_path, repo, fake, make)
    assert results["summary"]["save-reopen-unstable"] == 2
    assert not (
        repo.root / "parity" / "reports" / "phase0" / "oracle-envelope-register-drafts.json"
    ).exists()


def test_report_renders_the_not_yet_run_state(repo: Repo) -> None:
    text = render(repo.root)
    assert "## 2. Stability study" in text and "Not yet run" in text
    assert f"painter-{OLD_BUILD}" in text


# --- launcher ---------------------------------------------------------------------------------


def test_launcher_never_stops_a_painter_it_did_not_start() -> None:
    started: list[list[str]] = []

    def popen(command: list[str]) -> FakeProcess:
        started.append(command)
        return FakeProcess()

    launcher = PainterLauncher(
        Path("painter.exe"),
        popen=popen,
        answers=lambda: True,
        sleep=lambda s: None,
    )
    with pytest.raises(RecorderError, match="already answers"):
        launcher.start()
    assert started == []
    launcher.stop()  # nothing started: nothing stopped


def test_launcher_starts_with_remote_scripting_and_closes_the_project_first(
    fake: types.ModuleType,
) -> None:
    painter = Painter(fake, lambda n: world(fake))
    launcher = PainterLauncher(
        Path("painter.exe"),
        popen=painter.start_process,
        answers=painter.answers,
        sleep=lambda s: None,
    )
    launcher.start()
    assert painter.process.alive
    session = PainterSession(
        painter,
        sleep=lambda s: None,
        allowed_builds=lambda: frozenset({OLD_BUILD}),
        host_environment=lambda: dict(HOST_A),
    )
    session.connect()
    painter.world.project_open = True
    process = painter.process
    launcher.stop(session)
    assert not painter.world.project_open and process.terminated and launcher.process is None


def test_launcher_times_out_and_ends_its_process() -> None:
    process = FakeProcess()
    ticks = iter(range(0, 10_000, 100))
    launcher = PainterLauncher(
        Path("painter.exe"),
        popen=lambda command: process,
        answers=lambda: False,
        sleep=lambda s: None,
        monotonic=lambda: float(next(ticks)),
        ready_timeout_s=300,
    )
    with pytest.raises(RecorderError, match="did not answer"):
        launcher.start()
    assert process.terminated


# --- canary subset and corpus dispatch --------------------------------------------------------

GOLDEN_PUBLIC = "uzpainter/parity/golden-public/1"


def corpus_golden_manifests() -> list[Path]:
    """The golden manifests under `parity/manifests`. The tree also holds public manifests of
    other schemas (the glTF consumer fixture `consumers/gltf/wand-v1.json`), which the guard
    validates against their own schema (`tools/parity/guard/guard.py` PATH_RULES)."""
    root = REPO_ROOT / "parity" / "manifests"
    paths = sorted(root.rglob("*.json"))
    goldens = [p for p in paths if load_json(p).get("schema") == GOLDEN_PUBLIC]
    # Only the files the guard gives a schema of their own may be skipped (the glTF consumer
    # fixture, procedural certification batches): a golden with a wrong schema is not dropped.
    others = {p.relative_to(root).as_posix() for p in paths if p not in goldens}
    assert all(
        o == "consumers/gltf/wand-v1.json" or o.startswith("phase3/proc-cert/") for o in others
    ), others
    return goldens


def test_canary_subset_is_fixed_and_covers_the_required_areas() -> None:
    ids = [g for g, _ in CANARY]
    assert len(ids) == len(set(ids)) == 10
    index = {load_json(p)["golden_id"]: p for p in corpus_golden_manifests()}
    assert set(ids) <= set(index)
    calls = {
        g: {s["call"] for s in load_json(index[g])["instruction_sequence"]["steps"]} for g in ids
    }
    assert any("blend" in g for g in ids) and any("quantisation" in g for g in ids)
    assert any("srgb" in g for g in ids) and any("height-normal" in g for g in ids)
    assert any("resample" in g for g in ids)
    assert any("substance_painter.baking.bake_async" in c for c in calls.values())
    assert any(g.startswith("tier0/api-probes/") for g in ids)


def test_every_texture_golden_has_a_recorder_command() -> None:
    kinds = {}
    for path in corpus_golden_manifests():
        manifest = load_json(path)
        if manifest["tier"] != "3":
            kinds[manifest["golden_id"]] = recorder_kind(manifest)
    assert set(kinds.values()) == {"texture", "probe", "defaults", "templates"}
    assert kinds["tier0/api-probes/mask-stack"] == "probe"


# --- drift: environment-identity normalisation and save/reopen instability --------------------


def test_drift_normaliser_strips_environment_identity_only() -> None:
    shipped = "resource://starter_assets/mg_position/mg_position?version={}.sbsar"
    imported = "resource://project3/field-a?version={}.image"
    old = {"resource": {"context": "project42", "url": shipped.format("1" * 40)}}
    new = {"resource": {"context": "project16", "url": shipped.format("2" * 40)}}
    # The per-session resource context and an installed asset's version are identities.
    assert normalised(old) == normalised(new)
    # What Painter computes, and the content version of a resource the golden imports, are not.
    assert normalised({"label": "Skew base normal"}) != normalised({"label": "Skew correction"})
    assert normalised({"value": 0.5}) != normalised({"value": 0.25})
    assert normalised({"context": "Untitled"}) == {"context": "Untitled"}
    assert normalise_text(imported.format("1" * 40)) != normalise_text(imported.format("2" * 40))


def drift_source(label: str, recordings: dict[str, dict[str, Any]]) -> RecordSource:
    record = {
        "recordings": [
            {
                "recording_id": rid,
                "condition": "same_session" if rid == "r1" else "after_save_reopen",
                "outputs": [
                    {"output_id": oid, "kind": "api_readback", "value": value}
                    for oid, value in outputs.items()
                ],
            }
            for rid, outputs in recordings.items()
        ]
    }
    return RecordSource(record, label * 64, lambda _sha, _size: None, label)


def test_drift_classifies_save_reopen_instability_apart_from_drift() -> None:
    previous = drift_source("a", {"r1": {"x": 1, "y": 1}, "r2": {"x": 2, "y": 1}})
    # r1 equal across builds; r2 differs only where the previous build's r1~r2 already differed.
    unstable = golden_drift(
        DriftInput(
            "g", "0", previous, drift_source("b", {"r1": {"x": 1, "y": 1}, "r2": {"x": 3, "y": 1}})
        )
    )
    assert unstable["status"] == "unstable" and unstable["unstable_recordings"] == ["r2"]
    assert unstable["changed_recordings"] == []
    assert ("previous.r1", "previous.r2", "differs") in {
        (p["left"], p["right"], p["status"]) for p in unstable["pairs"]
    }
    # r2 differs in an output the previous build reproduced: drift.
    drifted = golden_drift(
        DriftInput(
            "g", "0", previous, drift_source("b", {"r1": {"x": 1, "y": 1}, "r2": {"x": 2, "y": 5}})
        )
    )
    assert drifted["status"] == "changed" and drifted["changed_recordings"] == ["r2"]
    # The reference itself changed: every differing recording is drift.
    moved = golden_drift(
        DriftInput(
            "g", "0", previous, drift_source("b", {"r1": {"x": 1, "y": 7}, "r2": {"x": 3, "y": 1}})
        )
    )
    assert moved["status"] == "changed" and moved["changed_recordings"] == ["r1", "r2"]
    assert moved["unstable_recordings"] == []


# --- OCIO sessions against the current envelope (decision 309) --------------------------------

OCIO_VALUE = "resources/ocio/substance/config.ocio"


def admit_environment(repo: Repo, name: str, environment: dict[str, Any], ocio: bool) -> Path:
    """A manifest of the current envelope naming `environment` as its environment record."""
    manifest = load_json(repo.manifests[0])
    manifest["golden_id"] = f"tier0/recorder-sample/{name}"
    if ocio:
        manifest["applied_settings"] = [
            *manifest["applied_settings"],
            {"name": "OCIO", "value": OCIO_VALUE, "applied_by": "environment_variable"},
        ]
    data = environment_bytes(environment)
    sha = hashlib.sha256(data).hexdigest()
    source = repo.root.parent / f"{name}-environment.json"
    source.write_bytes(data)
    repo.store.put_blob(source, sha)
    manifest["private_records"] = [
        {
            "record_id": "oracle-environment",
            "kind": ENVIRONMENT_KIND,
            "sha256": sha,
            "size_bytes": len(data),
        }
    ]
    path = repo.manifests[0].with_name(f"{name}.json")
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def ocio_repo(repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """The sample corpus as a known current envelope (its registry hash is the seeded Legacy
    goldens'), plus one admitted golden recorded in an OCIO session on the same host."""
    legacy = manifest_environment(repo.store, repo.manifests[0])
    assert legacy is not None
    registry = load_registry(repo.root)
    registry["envelopes"][0]["envelope_sha256"] = envelope_sha256(legacy)
    save_registry(registry, repo.root)
    config = tmp_path / "Painter" / Path(OCIO_VALUE)
    config.parent.mkdir(parents=True)
    config.write_text("ocio_profile_version: 2\n", encoding="utf-8")
    monkeypatch.setenv("OCIO", str(config))
    found = detect(repo.session(world(repo.fake)), repo.root)
    assert found.identity.environment is not None
    admit_environment(repo, "ocio-reference", found.identity.environment, ocio=True)
    return repo


def check_state(
    repo: Repo, configuration: str | None, host: dict[str, str] = HOST_A
) -> tuple[str, str]:
    found = detect(repo.session(world(repo.fake), host=host), repo.root)
    return detect_for_colour(found, configuration, repo.store, repo.root)


def test_ocio_request_on_the_matching_ocio_identity_is_admitted(ocio_repo: Repo) -> None:
    state, reason = check_state(ocio_repo, OCIO_VALUE)
    assert state == OCIO_REFERENCE and "1 admitted goldens naming OCIO" in reason
    # the plain check (a Legacy request) still sees another environment: nothing relabelled
    assert check_state(ocio_repo, None)[0] == "other_environment"
    assert load_registry(ocio_repo.root)["envelopes"][0]["equivalent_envelopes"] == []


def test_legacy_request_on_an_ocio_session_is_refused(ocio_repo: Repo) -> None:
    request = load_json(ocio_repo.manifests[0])
    assert named_ocio(request) is None
    assert check_state(ocio_repo, named_ocio(request)) == ("other_environment", "")


def test_ocio_request_on_a_legacy_session_is_refused(
    ocio_repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OCIO")
    assert check_state(ocio_repo, None)[0] == CURRENT_OUTCOME
    state, reason = check_state(ocio_repo, OCIO_VALUE)
    assert state == "other_environment" and "colour_configuration_sha256" in reason


def test_any_identity_field_mismatch_is_refused(ocio_repo: Repo, tmp_path: Path) -> None:
    state, reason = check_state(ocio_repo, OCIO_VALUE, HOST_B)
    assert state == "other_environment" and "(driver_version)" in reason
    for field, value in (("gpu_model", "Other GPU"), ("os_build", "10.0.2.2")):
        state, reason = check_state(ocio_repo, OCIO_VALUE, {**HOST_A, field: value})
        assert state == "other_environment" and f"({field})" in reason
    # the same configuration path with other file contents: another colour configuration hash
    config = tmp_path / "Painter" / Path(OCIO_VALUE)
    config.write_text("ocio_profile_version: 2.1\n", encoding="utf-8")
    state, reason = check_state(ocio_repo, OCIO_VALUE)
    assert state == "other_environment" and "colour_configuration_sha256" in reason
    # another Painter build is the build guard's answer, not an OCIO one
    newer = detect(ocio_repo.session(world(ocio_repo.fake, "12.1.5", "1.1.21")), ocio_repo.root)
    found = detect_for_colour(newer, OCIO_VALUE, ocio_repo.store, ocio_repo.root)
    assert found[0] == "unseen_build"


def test_ocio_check_refuses_without_a_single_reference_identity(ocio_repo: Repo) -> None:
    with pytest.raises(RecorderError, match=r"no admitted golden .* names OCIO other.ocio"):
        check_state(ocio_repo, "other.ocio")
    found = detect(ocio_repo.session(world(ocio_repo.fake)), ocio_repo.root)
    with pytest.raises(RecorderError, match="no private store"):
        detect_for_colour(found, OCIO_VALUE, None, ocio_repo.root)
    assert found.identity.environment is not None
    split = {**found.identity.environment, "colour_configuration_sha256": "0" * 64}
    admit_environment(ocio_repo, "ocio-split", split, ocio=True)
    with pytest.raises(RecorderError, match="disagree on 2 envelope identities"):
        check_state(ocio_repo, OCIO_VALUE)


def test_ocio_references_must_share_the_current_envelope_host() -> None:
    anchor = {
        "painter_build": "b",
        "gpu_model": "g",
        "driver_version": "1",
        "os_build": "o",
        "colour_configuration_sha256": "legacy",
    }
    reference = {**anchor, "driver_version": "2", "colour_configuration_sha256": "ocio"}
    with pytest.raises(RecorderError, match="other host fields"):
        ocio_reference_state(reference, [anchor], [reference], OCIO_VALUE)
    with pytest.raises(RecorderError, match="carries its identity"):
        ocio_reference_state(reference, [], [reference], OCIO_VALUE)
    running = {**anchor, "colour_configuration_sha256": "ocio"}
    recorded = {**running, "recorder_version": "x"}  # provenance, not part of the match
    assert ocio_reference_state(running, [anchor], [recorded], OCIO_VALUE)[0] == OCIO_REFERENCE


def test_named_ocio_reads_the_manifest_setting() -> None:
    setting = {"name": "OCIO", "value": OCIO_VALUE, "applied_by": "environment_variable"}
    assert named_ocio({"applied_settings": [setting]}) == OCIO_VALUE
    assert named_ocio({"applied_settings": [{**setting, "applied_by": "recorder_api"}]}) is None
    with pytest.raises(RecorderError, match="several OCIO"):
        named_ocio({"applied_settings": [setting, {**setting, "value": "x.ocio"}]})


@pytest.fixture
def recorded_envelope_case(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], ...]:
    anchor = {
        "basis": "recorded",
        "painter_build": "synthetic-build",
        **HOST_A,
        "colour_configuration_sha256": "1" * 64,
    }
    reference = {**anchor, "colour_configuration_sha256": "2" * 64}
    current = {
        "painter_build": anchor["painter_build"],
        "envelope_sha256": envelope_sha256(anchor),
        "equivalent_envelopes": [],
    }
    request = {
        "applied_settings": [
            {"name": "OCIO", "value": OCIO_VALUE, "applied_by": "environment_variable"}
        ]
    }
    monkeypatch.setattr(
        ocio_module,
        "ocio_identities",
        lambda entry, store, config, root: ([anchor], [reference] if config == OCIO_VALUE else []),
    )
    return anchor, reference, current, request


@pytest.mark.parametrize("kind", ["current", "equivalent", "ocio"])
def test_recorded_request_policy_accepts_only_matching_relation(
    recorded_envelope_case: tuple[dict[str, Any], ...], kind: str
) -> None:
    anchor, reference, current, request = recorded_envelope_case
    environment = reference if kind == "ocio" else dict(anchor)
    store = Mock(spec=OracleStore) if kind == "ocio" else None
    if kind == "equivalent":
        environment["driver_version"] = "equivalent-driver"
        current["equivalent_envelopes"] = [envelope_sha256(environment)]
    assert recorded_request_environment_matches(
        environment, request if kind == "ocio" else {}, current, store
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy_for_ocio",
        "ocio_for_legacy",
        "foreign_request",
        "conflicting_request",
        "missing_store",
        "missing_field",
        "unknown_field",
        "numeric_field",
        "basis",
        "build",
        "gpu",
        "driver",
        "os",
        "config",
        "missing_anchor",
        "missing_reference",
        "split",
        "foreign_reference",
        "unreadable",
        "store_error",
    ],
)
def test_recorded_request_policy_refuses_invalid_context(
    recorded_envelope_case: tuple[dict[str, Any], ...],
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor, reference, current, request = recorded_envelope_case
    environment = dict(reference)
    store = None if mutation == "missing_store" else Mock(spec=OracleStore)
    if mutation == "legacy_for_ocio":
        environment = dict(anchor)
    elif mutation == "ocio_for_legacy":
        request = {}
    elif mutation == "foreign_request":
        request["applied_settings"][0]["value"] = "foreign.ocio"
    elif mutation == "conflicting_request":
        request["applied_settings"].append({**request["applied_settings"][0], "value": "other"})
    elif mutation == "missing_field":
        environment.pop("gpu_model")
    elif mutation in ("unknown_field", "numeric_field", "basis"):
        field, value = {
            "unknown_field": ("gpu_model", "unknown"),
            "numeric_field": ("gpu_model", 3),
            "basis": ("basis", "inferred"),
        }[mutation]
        environment[field] = value
    elif mutation in ("build", "gpu", "driver", "os", "config"):
        field = {
            "build": "painter_build",
            "gpu": "gpu_model",
            "driver": "driver_version",
            "os": "os_build",
            "config": "colour_configuration_sha256",
        }[mutation]
        environment[field] = "foreign"
    elif mutation in ("missing_anchor", "missing_reference", "split", "foreign_reference"):
        anchors = [] if mutation == "missing_anchor" else [anchor]
        references = [] if mutation == "missing_reference" else [reference]
        if mutation == "split":
            references.append({**reference, "colour_configuration_sha256": "3" * 64})
        elif mutation == "foreign_reference":
            references = [{**reference, "gpu_model": "foreign"}]
        monkeypatch.setattr(ocio_module, "ocio_identities", lambda *args: (anchors, references))
    elif mutation in ("unreadable", "store_error"):
        monkeypatch.setattr(
            ocio_module,
            "ocio_identities",
            Mock(
                side_effect=(RecorderError if mutation == "unreadable" else StoreError)(
                    "private-path-marker"
                )
            ),
        )
    assert recorded_request_environment_matches(environment, request, current, store) is False


def test_recorded_ocio_policy_reads_existing_store_offline(ocio_repo: Repo) -> None:
    request = load_json(ocio_repo.manifests[0].with_name("ocio-reference.json"))
    environment = manifest_environment(
        ocio_repo.store, ocio_repo.manifests[0].with_name("ocio-reference.json")
    )
    assert environment is not None
    current = load_registry(ocio_repo.root)["envelopes"][0]
    assert recorded_request_environment_matches(
        environment, request, current, ocio_repo.store, ocio_repo.root
    )

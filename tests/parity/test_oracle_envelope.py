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

import pytest

from tools.parity.envelope import canary as canary_module
from tools.parity.envelope.backfill import backfill
from tools.parity.envelope.canary import CANARY
from tools.parity.envelope.corpus import recorder_kind
from tools.parity.envelope.refresh import (
    CURRENT_OUTCOME,
    EQUIVALENT,
    INCOMPLETE,
    PROMOTED,
    detect,
    ensure_current,
)
from tools.parity.envelope.registry import (
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
from tools.parity.recorder.texture import record_texture_golden
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
    run = next(
        (repo.inbox / "envelopes" / new_id / "tier0__recorder-sample__plane-0").rglob(RECORD_FILE)
    ).parent
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
    kept = repo.work / "quarantine" / "painter-12.1.5+js-api.1.1.21"
    assert (kept / "work" / "candidate.json").is_file() and (kept / "work" / "runs").is_dir()
    assert not (repo.root / "parity" / "envelopes" / "painter-12.1.5+js-api.1.1.21").exists()


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
    ledger = load_json(repo.work / "envelopes" / "painter-12.1.5+js-api.1.1.21" / "candidate.json")
    first = ledger["goldens"]["tier0/recorder-sample/plane-0"]["run"]
    w.export_hook = None
    assert repo.ensure(transport).outcome == PROMOTED
    ledger = load_json(repo.work / "envelopes" / "painter-12.1.5+js-api.1.1.21" / "candidate.json")
    assert (
        ledger["goldens"]["tier0/recorder-sample/plane-0"]["run"] == first
    )  # resumed, not re-recorded
    assert load_registry(repo.root)["current"] == "painter-12.1.5+js-api.1.1.21"


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
        painter, sleep=lambda s: None, allowed_builds=lambda: frozenset({OLD_BUILD})
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


def test_canary_subset_is_fixed_and_covers_the_required_areas() -> None:
    ids = [g for g, _ in CANARY]
    assert len(ids) == len(set(ids)) == 10
    index = {
        load_json(p)["golden_id"]: p for p in (REPO_ROOT / "parity" / "manifests").rglob("*.json")
    }
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
    for path in sorted((REPO_ROOT / "parity" / "manifests").rglob("*.json")):
        manifest = load_json(path)
        if manifest["tier"] != "3":
            kinds[manifest["golden_id"]] = recorder_kind(manifest)
    assert set(kinds.values()) == {"texture", "probe", "defaults", "templates"}
    assert kinds["tier0/api-probes/mask-stack"] == "probe"

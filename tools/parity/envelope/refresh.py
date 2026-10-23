"""Rolling oracle: detection and the transactional envelope refresh (decision 037).

Detection (`detect`, `ensure_current`): read the running Painter build and environment first.

- the current envelope's build and envelope hash (or an environment the canary proved
  equivalent): nothing to do;
- the current build under another environment (driver, GPU, OS, colour configuration): the
  canary runs; exact equality records the environment as equivalent, any difference starts the
  refresh (decision 034 (d));
- an unseen build: the refresh starts, with no human step;
- the build of a superseded envelope: refused (acceptance follows the newest promoted envelope).

Refresh = transaction:

1. A candidate envelope is entered in the registry (its build becomes recordable; the current
   envelope stays current). Its private ledger is `<work>/envelopes/<dir>/candidate.json`; its
   runs go to `<inbox>/envelopes/<dir>/` (`<dir>`: `registry.envelope_directory(<id>)`).
2. The canary goldens first, then every other Tier 0-2b golden of the current envelope, each
   recorded by its own recorder command under the candidate build, always in full (no aliasing,
   even when the canary shows no drift). The canary's drift is published as soon as it is
   recorded.
3. The running build and session are verified before every call that is not a readiness poll,
   the host environment before every golden and at the end, and every run's record is checked
   for the candidate's build and envelope. Any change, or an identity that cannot be verified,
   aborts the candidate: its partial outputs move to `<work>/quarantine/<dir>/`, the registry
   records why, and detection restarts against the new build.
4. Promotion only when every golden is recorded and the runs are consistent and schema-valid,
   the corpus drift report (unchanged / changed per golden) is published, and the private store
   is available: the runs are admitted with the store's `record --run` into the candidate's
   manifests (`parity/envelopes/<dir>/manifests/`), then the registry is replaced in one atomic
   write (the commit point). Until then the previous envelope stays current; an interrupted
   candidate resumes from its ledger.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tools.parity.envelope import colour_sessions as colours
from tools.parity.envelope.canary import canary_ids, drift_free, run_canary
from tools.parity.envelope.compare import SourceUnavailable, run_source
from tools.parity.envelope.corpus import job_manifest, record_golden
from tools.parity.envelope.drift import DriftInput, drift_document, tier3_goldens
from tools.parity.envelope.registry import (
    CURRENT,
    SUPERSEDED,
    TEXTURE_TIERS,
    candidate_manifest_root,
    corpus_manifests,
    envelope,
    envelope_directory,
    envelope_id_for,
    load_registry,
    manifest_root,
    record_prefix_for,
    recordable_builds,
    save_registry,
    updated,
)
from tools.parity.envelope.report import drift_path, write_json, write_report
from tools.parity.recorder.environment import (
    HOST_FIELDS,
    UNKNOWN,
    HostEnvironment,
    capture_host_environment,
    envelope_sha256,
    environment_record,
)
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.output import MANIFEST_FILE, ensure_outside_repository
from tools.parity.recorder.session import (
    BuildPolicy,
    IdentityChanged,
    PainterIdentity,
    PainterSession,
    RecorderError,
    UnseenBuild,
)
from tools.parity.schemas import REPO_ROOT, Schema, load_json, record_problems, validation_errors
from tools.parity.store.store import OracleStore

LEDGER_SCHEMA = "uzpainter/parity/envelope-candidate-ledger/1"
CURRENT_OUTCOME = "current"
EQUIVALENT = "equivalent"
PROMOTED = "promoted"
INCOMPLETE = "incomplete"
RECORDED, REFUSED = "recorded", "refused"
UNSEEN = "unseen_build"
OTHER_ENVIRONMENT = "other_environment"
SUPERSEDED_BUILD = "superseded_build"
MAX_RESTARTS = 3

SessionFactory = Callable[[BuildPolicy, bool], PainterSession]
Now = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Outcome:
    outcome: str
    envelope_id: str
    message: str
    drift_report: Path | None = None


@dataclass(frozen=True)
class Detection:
    state: str  # current, other_environment, unseen_build, superseded_build
    identity: PainterIdentity
    current: dict[str, Any]


def detect(session: PainterSession, repo_root: Path = REPO_ROOT) -> Detection:
    """Read the running build and environment and place them against the registry (no guard,
    nothing recorded). The local parity gate calls this, or `ensure_current`."""
    identity = session.read_identity()
    assert identity.environment is not None
    registry = load_registry(repo_root)
    current = envelope(registry, registry["current"])
    if identity.build_id == current["painter_build"]:
        envelope_hash = envelope_sha256(identity.environment)
        known = {current["envelope_sha256"], *current["equivalent_envelopes"]}
        return Detection(
            CURRENT_OUTCOME if envelope_hash in known else OTHER_ENVIRONMENT, identity, current
        )
    if identity.build_id in {e["painter_build"] for e in registry["envelopes"]}:
        return Detection(SUPERSEDED_BUILD, identity, current)
    return Detection(UNSEEN, identity, current)


def save_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class Candidate:
    entry: dict[str, Any]
    ledger: dict[str, Any]
    work: Path
    inbox: Path

    @property
    def envelope_id(self) -> str:
        return str(self.entry["envelope_id"])

    @property
    def ledger_path(self) -> Path:
        return self.work / "candidate.json"

    def save(self) -> None:
        save_json(self.ledger_path, self.ledger)


def quarantine(
    candidate_entry: Mapping[str, Any],
    reason: str,
    work_root: Path,
    inbox_root: Path,
    today: date,
    repo_root: Path,
) -> None:
    """Move a candidate's partial outputs to the private quarantine and drop it from the
    registry, recording why. Nothing is deleted."""
    envelope_id = str(candidate_entry["envelope_id"])
    directory = envelope_directory(envelope_id)
    target = work_root / "quarantine" / directory
    target.mkdir(parents=True, exist_ok=True)
    for name, source in (
        ("work", work_root / "envelopes" / directory),
        ("inbox", inbox_root / "envelopes" / directory),
    ):
        if source.exists():
            destination = target / name
            if destination.exists():
                destination = target / f"{name}-{uuid.uuid4().hex[:8]}"
            shutil.move(str(source), str(destination))
    registry = updated(load_registry(repo_root))
    if registry["candidate"] is not None and registry["candidate"]["envelope_id"] == envelope_id:
        registry["candidate"] = None
    registry["quarantine"].append(
        {
            "envelope_id": envelope_id,
            "painter_build": candidate_entry["painter_build"],
            "reason": reason[:512] or "aborted",
            "quarantined_on": today.isoformat(),
        }
    )
    save_registry(registry, repo_root)


def open_candidate(
    identity: PainterIdentity,
    work_root: Path,
    inbox_root: Path,
    today: date,
    repo_root: Path,
) -> Candidate:
    """Resume the registry's candidate when it is this build and envelope, else quarantine it
    and enter a new candidate."""
    assert identity.environment is not None
    envelope_hash = envelope_sha256(identity.environment)
    registry = load_registry(repo_root)
    existing = registry["candidate"]
    resumed = None
    if existing is not None:
        work = work_root / "envelopes" / envelope_directory(existing["envelope_id"])
        if (work / "candidate.json").is_file():
            resumed = load_json(work / "candidate.json")
    declared_resume = False
    if resumed is not None and "anchor_environment" in resumed:
        colours.same_host(resumed["anchor_environment"], identity.environment)
        declared_resume = any(
            colours.matches(identity, info.get("colour", colours.LEGACY))
            for info in resumed["goldens"].values()
        )
    if existing is not None and (
        existing["painter_build"] != identity.build_id
        or (existing["envelope_sha256"] != envelope_hash and not declared_resume)
    ):
        quarantine(
            existing,
            f"superseded before promotion: Painter now runs {identity.build_id} under envelope "
            f"{envelope_hash[:12]}",
            work_root,
            inbox_root,
            today,
            repo_root,
        )
        registry = load_registry(repo_root)
        existing = None
    current = envelope(registry, registry["current"])
    if existing is not None:
        work = work_root / "envelopes" / envelope_directory(existing["envelope_id"])
        ledger_path = work / "candidate.json"
        if ledger_path.is_file():
            candidate = Candidate(
                existing,
                load_json(ledger_path),
                work,
                inbox_root / "envelopes" / envelope_directory(existing["envelope_id"]),
            )
            prepare_colours(candidate, identity, repo_root)
            return candidate
        entry = existing  # no ledger in its directory: the candidate starts afresh there
    else:
        if not colours.matches(identity, colours.LEGACY):
            raise RecorderError("a new refresh needs a Legacy anchor session; use --launch")
        entry = {
            "envelope_id": envelope_id_for(identity.build_id, identity.environment, registry),
            "painter_build": identity.build_id,
            "painter_version": identity.version,
            "record_prefix": record_prefix_for(identity.build_id, registry),
            "envelope_sha256": envelope_hash,
            "previous": current["envelope_id"],
            "started_on": today.isoformat(),
        }
        changed = updated(registry)
        changed["candidate"] = entry
        save_registry(changed, repo_root)
    canary = list(canary_ids())
    root = manifest_root(current, repo_root)
    goldens: dict[str, Any] = {}
    paths = corpus_manifests(current, repo_root, TEXTURE_TIERS)
    for path in paths:
        manifest = load_json(path)
        goldens[str(manifest["golden_id"])] = {
            "manifest": path.resolve().relative_to(repo_root.resolve()).as_posix(),
            "relative": path.resolve().relative_to(root.resolve()).as_posix(),
            "tier": manifest["tier"],
            "status": "pending",
        }
    order = [g for g in canary if g in goldens] + sorted(g for g in goldens if g not in canary)
    ledger = {
        "schema": LEDGER_SCHEMA,
        "envelope_id": entry["envelope_id"],
        "painter_build": entry["painter_build"],
        "envelope_sha256": entry["envelope_sha256"],
        "previous": current["envelope_id"],
        "order": order,
        "canary_published": False,
        "goldens": goldens,
    }
    candidate = Candidate(
        dict(entry),
        ledger,
        work_root / "envelopes" / envelope_directory(entry["envelope_id"]),
        inbox_root / "envelopes" / envelope_directory(entry["envelope_id"]),
    )
    prepare_colours(candidate, identity, repo_root)
    candidate.save()
    return candidate


def prepare_colours(candidate: Candidate, identity: PainterIdentity, repo_root: Path) -> None:
    """Upgrade a v1 ledger only after its existing runs pass the original anchor check."""
    ledger = candidate.ledger
    if "anchor_environment" not in ledger:
        if identity.environment is None or not colours.matches(identity, colours.LEGACY):
            raise RecorderError("a legacy candidate ledger needs its original Legacy session")
        if envelope_sha256(identity.environment) != candidate.entry["envelope_sha256"]:
            raise IdentityChanged("legacy candidate anchor differs")
        for golden, info in ledger["goldens"].items():
            if info["status"] == RECORDED:
                check_run(Path(info["run"]), golden, candidate)
                original = load_json(repo_root / info["manifest"])
                if colours.declaration(original) != colours.LEGACY:
                    raise IdentityChanged(
                        "legacy run has an OCIO declaration under the Legacy anchor"
                    )
        ledger["anchor_environment"] = dict(identity.environment)
        ledger["colour_sessions"] = {}
        colours.bind(ledger, identity, colours.LEGACY)
    anchor = ledger["anchor_environment"]
    colours.known(anchor)
    if envelope_sha256(anchor) != candidate.entry["envelope_sha256"]:
        raise IdentityChanged("candidate anchor was changed")
    for info in ledger["goldens"].values():
        declared = colours.declaration(load_json(repo_root / info["manifest"]))
        if "colour" in info and info["colour"] != declared:
            raise IdentityChanged("a golden's colour declaration changed during refresh")
        info["colour"] = declared
    candidate.save()


def check_run(run: Path, golden_id: str, candidate: Candidate) -> None:
    """A run belongs to the candidate: its build and envelope, valid record and manifest."""
    source = run_source(run)
    record = source.record
    if record["golden_id"] != golden_id:
        raise RecorderError(f"{run}: records {record['golden_id']}, not {golden_id}")
    problems = record_problems(record)
    problems += validation_errors(load_json(run / MANIFEST_FILE), Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"{run}: invalid run: {problems}")
    build = record["key"]["painter_build"]["build_id"]
    environment = record.get("environment")
    if build != candidate.entry["painter_build"]:
        raise IdentityChanged(f"{golden_id} was recorded on build {build}, not the candidate's")
    expected_hash = candidate.entry["envelope_sha256"]
    if "anchor_environment" in candidate.ledger:
        info = candidate.ledger["goldens"][golden_id]
        declared = info["colour"]
        if colours.declaration(load_json(run / MANIFEST_FILE)) != declared:
            raise IdentityChanged(f"{golden_id} was recorded with another colour declaration")
        slot = candidate.ledger["colour_sessions"].get(declared)
        if slot is None:
            raise IdentityChanged(f"{golden_id} has no pinned colour session")
        colours.same_host(candidate.ledger["anchor_environment"], slot["environment"])
        expected_hash = envelope_sha256(slot["environment"])
        if declared == colours.LEGACY and expected_hash != candidate.entry["envelope_sha256"]:
            raise IdentityChanged("Legacy colour session differs from the candidate anchor")
    if environment is None or envelope_sha256(environment) != expected_hash:
        raise IdentityChanged(f"{golden_id} was recorded under another environment")


def previous_inputs(
    candidate: Candidate, golden_ids: list[str], store: OracleStore | None, repo_root: Path
) -> list[DriftInput]:
    from tools.parity.envelope.canary import previous_source

    registry = load_registry(repo_root)
    previous = envelope(registry, candidate.ledger["previous"])
    items: list[DriftInput] = []
    for golden_id in golden_ids:
        info = candidate.ledger["goldens"][golden_id]
        old, error = previous_source(store, repo_root / info["manifest"], previous["record_prefix"])
        try:
            new = run_source(Path(info["run"])) if info["status"] == RECORDED else None
        except SourceUnavailable:
            new = None
        items.append(DriftInput(golden_id, info["tier"], old, new, error))
    return items


def publish_drift(
    scope: str,
    candidate: Candidate,
    golden_ids: list[str],
    store: OracleStore | None,
    today: date,
    repo_root: Path,
) -> Path:
    registry = load_registry(repo_root)
    previous = envelope(registry, candidate.ledger["previous"])
    document = drift_document(
        scope,
        candidate.entry,
        previous,
        previous_inputs(candidate, golden_ids, store, repo_root),
        tier3_goldens(corpus_manifests(previous, repo_root, frozenset({"3"}))),
        today,
        repo_root,
    )
    path = drift_path(scope, candidate.envelope_id, repo_root)
    write_json(path, document)
    write_report(repo_root)
    return path


def record_candidate(
    session: PainterSession,
    candidate: Candidate,
    store: OracleStore | None,
    now: Now,
    today: date,
    host: HostEnvironment,
    repo_root: Path,
    switch: Callable[[str, PainterSession], PainterSession] | None = None,
) -> None:
    identity = session.connect()
    if identity.build_id != candidate.entry["painter_build"]:
        raise IdentityChanged(
            f"Painter runs {identity.build_id}, not the candidate build "
            f"{candidate.entry['painter_build']}"
        )
    canary = [g for g in candidate.ledger["order"] if g in set(canary_ids())]
    # Preserve the canary-first order within each colour, and avoid restarting per golden.
    order = sorted(
        candidate.ledger["order"],
        key=lambda g: (
            candidate.ledger["goldens"][g]["colour"] != colours.LEGACY,
            candidate.ledger["goldens"][g]["colour"],
        ),
    )
    for golden_id in order:
        info = candidate.ledger["goldens"][golden_id]
        if info["status"] != RECORDED:
            session.verify_identity(host)
            declared = info["colour"]
            if not colours.matches(identity, declared):
                if switch is None:
                    info.update(
                        status="pending",
                        error=f"needs declared colour session {declared}; use --launch",
                    )
                    candidate.save()
                    continue
                session = switch(declared, session)
                identity = session.connect()
                session.verify_identity(host)
            colours.bind(candidate.ledger, identity, declared)
            candidate.save()
            manifest = job_manifest(load_json(repo_root / info["manifest"]), identity)
            try:
                run = record_golden(
                    session,
                    manifest,
                    candidate.work / "runs",
                    candidate.inbox,
                    now,
                    str(candidate.entry["record_prefix"]),
                    repo_root,
                    store=store,
                )
                check_run(run, golden_id, candidate)
                # Re-read file bytes after the run too; a path alone never pins an OCIO config.
                session.verify_identity(host)
                state = dict(session.call("hello")["colour_management"])
                assert identity.environment is not None
                colours.bind(
                    candidate.ledger,
                    replace(
                        identity,
                        colour_management=state,
                        environment=environment_record(
                            painter_build=identity.build_id,
                            colour_management=state,
                            host=identity.environment,
                        ),
                    ),
                    declared,
                )
            except UnseenBuild as error:
                raise IdentityChanged(str(error)) from error
            except IdentityChanged:
                candidate.save()
                raise
            except RecorderError as error:
                info.update({"status": REFUSED, "error": str(error)})
            else:
                info.update({"status": RECORDED, "run": run.as_posix(), "error": None})
            candidate.save()
        if (
            not candidate.ledger["canary_published"]
            and canary
            and all(candidate.ledger["goldens"][g]["status"] == RECORDED for g in canary)
        ):
            publish_drift("canary", candidate, canary, store, today, repo_root)
            candidate.ledger["canary_published"] = True
            candidate.save()
    session.verify_identity(host)
    if switch is not None and not colours.matches(identity, colours.LEGACY):
        session = switch(colours.LEGACY, session)
        colours.bind(candidate.ledger, session.connect(), colours.LEGACY)
        session.verify_identity(host)


def consistency_problems(candidate: Candidate, repo_root: Path) -> list[str]:
    registry = load_registry(repo_root)
    previous = envelope(registry, candidate.ledger["previous"])
    expected = {
        str(load_json(p)["golden_id"]) for p in corpus_manifests(previous, repo_root, TEXTURE_TIERS)
    }
    problems: list[str] = []
    if set(candidate.ledger["goldens"]) != expected:
        problems.append("the candidate does not cover exactly the previous envelope's corpus")
    for golden_id, info in sorted(candidate.ledger["goldens"].items()):
        if info["status"] != RECORDED:
            problems.append(
                f"{golden_id}: {info['status']} ({info.get('error') or 'not recorded'})"
            )
            continue
        try:
            declared = colours.declaration(load_json(repo_root / info["manifest"]))
            if info.get("colour", colours.LEGACY) != declared:
                raise IdentityChanged("golden colour declaration differs from its source")
            check_run(Path(info["run"]), golden_id, candidate)
        except (RecorderError, SourceUnavailable, OSError) as error:
            problems.append(f"{golden_id}: {error}")
    return problems


def promote(
    candidate: Candidate,
    store: OracleStore,
    drift_report: Path,
    today: date,
    repo_root: Path,
) -> None:
    """Admit every run into the candidate's manifests, then flip the registry atomically."""
    from tools.parity.store.manifest import record_run

    root = repo_root / candidate_manifest_root(candidate.envelope_id)
    for golden_id in candidate.ledger["order"]:
        info = candidate.ledger["goldens"][golden_id]
        record_run(store, root / info["relative"], Path(info["run"]))
    registry = updated(load_registry(repo_root))
    if (
        registry["candidate"] is None
        or registry["candidate"]["envelope_id"] != candidate.envelope_id
    ):
        raise RecorderError(f"{candidate.envelope_id} is no longer the registry's candidate")
    for entry in registry["envelopes"]:
        if entry["status"] == CURRENT:
            entry["status"], entry["superseded_on"] = SUPERSEDED, today.isoformat()
    run = run_source(Path(next(iter(candidate.ledger["goldens"].values()))["run"]))
    environment = run.record["environment"]
    registry["envelopes"].append(
        {
            "envelope_id": candidate.envelope_id,
            "status": CURRENT,
            "painter_build": candidate.entry["painter_build"],
            "painter_version": candidate.entry["painter_version"],
            "manifest_root": candidate_manifest_root(candidate.envelope_id),
            "record_prefix": candidate.entry["record_prefix"],
            "envelope_sha256": candidate.entry["envelope_sha256"],
            "environment_known": all(
                environment.get(f, UNKNOWN) != UNKNOWN
                for f in (*HOST_FIELDS, "colour_configuration_sha256")
            ),
            "equivalent_envelopes": [],
            "previous": candidate.ledger["previous"],
            "promoted_on": today.isoformat(),
            "superseded_on": None,
            "drift_report": drift_report.resolve().relative_to(repo_root.resolve()).as_posix(),
        }
    )
    registry["current"] = candidate.envelope_id
    registry["candidate"] = None
    save_registry(registry, repo_root)
    write_report(repo_root)


def refresh(
    session: PainterSession,
    identity: PainterIdentity,
    store: OracleStore | None,
    work_root: Path,
    inbox_root: Path,
    now: Now,
    today: date,
    host: HostEnvironment,
    repo_root: Path,
    switch: Callable[[str, PainterSession], PainterSession] | None = None,
) -> Outcome:
    candidate = open_candidate(identity, work_root, inbox_root, today, repo_root)
    record_candidate(session, candidate, store, now, today, host, repo_root, switch)
    problems = consistency_problems(candidate, repo_root)
    if problems:
        return Outcome(
            INCOMPLETE,
            candidate.envelope_id,
            "candidate not promoted; the previous envelope stays current: "
            + "; ".join(problems[:10]),
        )
    report = publish_drift(
        "corpus", candidate, list(candidate.ledger["order"]), store, today, repo_root
    )
    if store is None:
        return Outcome(
            INCOMPLETE,
            candidate.envelope_id,
            "candidate complete but not promoted: the private store is not available on this "
            "machine",
            report,
        )
    promote(candidate, store, report, today, repo_root)
    return Outcome(PROMOTED, candidate.envelope_id, "candidate promoted to current", report)


def close_own_project(session: PainterSession) -> None:
    """After an abort, close the throwaway project only when the Painter process is still the
    one the recorder connected to (a project in any other process is not the recorder's)."""
    identity = session.identity
    verify_calls = session.verify_calls
    session.verify_calls = False
    try:
        if identity is not None and session.call("hello")["session_id"] == identity.session_id:
            session.call("close_project")
    except (RecorderError, OSError, KeyError, TypeError):
        return
    finally:
        session.verify_calls = verify_calls


def ensure_current(
    make_session: SessionFactory,
    store: OracleStore | None,
    work_root: Path,
    inbox_root: Path,
    now: Now = utc_now,
    host: HostEnvironment = capture_host_environment,
    launcher: PainterLauncher | None = None,
    max_restarts: int = MAX_RESTARTS,
    repo_root: Path = REPO_ROOT,
) -> Outcome:
    """Detect, and refresh when needed; aborted candidates are quarantined and detection
    restarts (with the launcher, against a newly started Painter) up to `max_restarts` times."""
    work_root = ensure_outside_repository(work_root, repo_root)
    inbox_root = ensure_outside_repository(inbox_root, repo_root)
    aborts = 0
    active_session: PainterSession | None = None

    def switch(colour: str, previous: PainterSession) -> PainterSession:
        nonlocal active_session
        assert launcher is not None
        _ = launcher.pid  # refuse to take ownership of an unrelated process
        settings = colours.launch_environment(colour, launcher.exe)
        launcher.stop(previous)
        launcher.start(settings)
        active_session = make_session(lambda: recordable_builds(repo_root), True)
        return active_session

    while True:
        today = now().date()
        session = make_session(lambda: recordable_builds(repo_root), True)
        active_session = session
        try:
            found = detect(session, repo_root)
            if launcher is not None and not colours.matches(found.identity, colours.LEGACY):
                session = switch(colours.LEGACY, session)
                found = detect(session, repo_root)
        except OSError as error:
            raise RecorderError(f"Painter's remote endpoint is not reachable: {error}") from error
        current = found.current
        if found.state == CURRENT_OUTCOME:
            return Outcome(
                CURRENT_OUTCOME,
                current["envelope_id"],
                "the running Painter is the current envelope",
            )
        if found.state == SUPERSEDED_BUILD:
            raise RecorderError(
                f"Painter runs {found.identity.build_id}, the build of a superseded envelope; the "
                f"acceptance oracle is {current['envelope_id']} (decision 037): update Painter"
            )
        try:
            if found.state == OTHER_ENVIRONMENT:
                registry = load_registry(repo_root)
                if registry["candidate"] is None:
                    document, _runs = run_canary(
                        session, current, store, work_root, inbox_root, now, today, repo_root
                    )
                    assert found.identity.environment is not None
                    envelope_hash = envelope_sha256(found.identity.environment)
                    document["envelope_id"] = f"{current['envelope_id']}-env-{envelope_hash[:12]}"
                    path = drift_path("canary", str(document["envelope_id"]), repo_root)
                    write_json(path, document)
                    if drift_free(document):
                        changed = updated(load_registry(repo_root))
                        envelope(changed, current["envelope_id"])["equivalent_envelopes"].append(
                            envelope_hash
                        )
                        save_registry(changed, repo_root)
                        write_report(repo_root)
                        return Outcome(
                            EQUIVALENT,
                            current["envelope_id"],
                            "same build under another environment; the canary equals the current "
                            "goldens exactly, the environment is recorded as equivalent",
                            path,
                        )
            return refresh(
                session,
                found.identity,
                store,
                work_root,
                inbox_root,
                now,
                today,
                host,
                repo_root,
                switch if launcher is not None else None,
            )
        except IdentityChanged as error:
            close_own_project(active_session or session)
            registry = load_registry(repo_root)
            if registry["candidate"] is not None:
                quarantine(
                    registry["candidate"], str(error), work_root, inbox_root, today, repo_root
                )
            aborts += 1
            if aborts > max_restarts:
                raise RecorderError(
                    f"refresh aborted {aborts} times; the last abort: {error}"
                ) from error
            if launcher is not None:
                launcher.stop(active_session)
                launcher.start(colours.launch_environment(colours.LEGACY, launcher.exe))

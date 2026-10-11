"""Stability study (decision 034 (b), (c); task phase0.9_oracle-envelope 3.1-3.3).

Driver. Every golden of the given manifests is recorded by its own recorder command three
times, which gives the five recordings of decision 034 (b) plus one:

- runs `a` and `b` in one Painter process: `a.r1`, `b.r1` (same session) and `a.r2`, `b.r2`
  (after save and reopen);
- run `c` in a freshly started Painter process (the launcher stops the first process and starts
  a new one): `c.r1` (fresh process) and `c.r2` (fresh process, after save and reopen).

Runs go to the private inbox under `stability-study/<study id>/` with record ids prefixed
`study-<study id>-<run>-`, so their admission to the store (`--admit`, or
`python -m tools.parity.store record <study manifest> --run <run>`) never touches a golden's own
records. The ledger `study.json` in the private work directory lists every run; an interrupted
study resumes from it (`--resume <study dir>`). The session that records is checked before every
call (same Painter process and build) and the host environment at every golden.

Analysis (pairs, all exact): each run's later recordings against its `r1` (`save_reopen`, or
`same_session` for a second same-session recording such as the baking defaults' `r3`), `b.r1`
against `a.r1` and `c.r1` against `a.r1` (`same_session` when the two runs share a Painter
session id, else `fresh_process`). Classification per golden: `stable`,
`save-reopen-unstable` (decision 032), `fresh-process-unstable`,
`save-reopen-and-fresh-process-unstable`, `same-session-unstable` (r1 itself does not repeat in
one process; neither 032 nor 034 covers it), `incomplete` (a run is missing) or `unavailable`.
For a fresh-process-unstable golden, r1 stays the exact target (decision 034 (c)); its register
entry is prepared with the evidence and left without the owner's approval fields.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tools.parity.envelope.compare import (
    DIFFERS,
    UNAVAILABLE,
    RecordSource,
    SourceUnavailable,
    compare_recordings,
    run_source,
)
from tools.parity.envelope.corpus import record_golden
from tools.parity.envelope.report import (
    DRAFTS_JSON,
    draft_problems,
    study_path,
    write_json,
    write_report,
)
from tools.parity.recorder.environment import HostEnvironment, environment_sha256
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.recorder.session import (
    IdentityChanged,
    PainterSession,
    RecorderError,
    UnseenBuild,
)
from tools.parity.schemas import REGISTER_PATH, REPO_ROOT, load_json

STUDY_SCHEMA = "uzpainter/parity/oracle-envelope-study/1"
LEDGER_SCHEMA = "uzpainter/parity/oracle-envelope-study-ledger/1"
DRAFTS_SCHEMA = "uzpainter/parity/oracle-envelope-register-drafts/1"
FIRST_SESSION_ROLES = ("a", "b")
FRESH_ROLE = "c"
ROLES = (*FIRST_SESSION_ROLES, FRESH_ROLE)
RECORDED, REFUSED = "recorded", "refused"
STABLE = "stable"
SAVE_REOPEN = "save-reopen-unstable"
FRESH = "fresh-process-unstable"
BOTH = "save-reopen-and-fresh-process-unstable"
SAME_SESSION = "same-session-unstable"
INCOMPLETE, UNAVAILABLE_CLASS = "incomplete", "unavailable"
DEFECT_TEST = "tests/parity/test_verdict.py::test_decision_032_entries_catch_injected_defects"
INJECTED_DEFECTS = [
    "one_value_off_by_one_code",
    "uniform_offset_one_code",
    "one_wrong_texel_region",
    "float32_last_place_residual",
]

SessionFactory = Callable[[], PainterSession]
Now = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def study_id_of(now: datetime) -> str:
    return now.strftime("%Y%m%dt%H%M%Sz")


def save_ledger(path: Path, ledger: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class Study:
    directory: Path
    ledger: dict[str, Any]

    @property
    def ledger_path(self) -> Path:
        return self.directory / "study.json"

    @property
    def study_id(self) -> str:
        return str(self.ledger["study_id"])

    def save(self) -> None:
        save_ledger(self.ledger_path, self.ledger)

    def entry(self, golden_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self.ledger["goldens"][golden_id]
        return result


def new_study(
    manifests: Sequence[Path],
    work: Path,
    envelope: Mapping[str, Any],
    now: datetime,
    repo_root: Path = REPO_ROOT,
) -> Study:
    study_id = study_id_of(now)
    directory = ensure_outside_repository(work, repo_root) / "stability-study" / study_id
    goldens: dict[str, Any] = {}
    for path in manifests:
        manifest = load_json(path)
        if manifest["tier"] not in ("0", "1", "2a", "2b"):
            continue
        if manifest["golden_id"] in goldens:
            raise RecorderError(f"{manifest['golden_id']} is named twice")
        goldens[str(manifest["golden_id"])] = {
            "manifest": path.resolve().relative_to(repo_root.resolve()).as_posix(),
            "tier": manifest["tier"],
            "domain": manifest["domain"],
            "runs": {},
        }
    if not goldens:
        raise RecorderError("the study needs at least one Tier 0-2b manifest")
    study = Study(
        directory,
        {
            "schema": LEDGER_SCHEMA,
            "study_id": study_id,
            "envelope_id": envelope["envelope_id"],
            "painter_build": envelope["painter_build"],
            "goldens": goldens,
        },
    )
    study.save()
    return study


def load_study(directory: Path) -> Study:
    ledger = load_json(directory / "study.json")
    if ledger.get("schema") != LEDGER_SCHEMA:
        raise RecorderError(f"{directory}: not a stability-study ledger")
    return Study(directory, ledger)


def record_role(
    study: Study,
    session: PainterSession,
    role: str,
    inbox: Path,
    now: Now,
    host: HostEnvironment,
    repo_root: Path,
) -> None:
    """Record every golden of the study once more as run `role` (skipping recorded ones)."""
    identity = session.connect()
    study.ledger.setdefault("sessions", {})[role] = identity.session_id
    if role == FRESH_ROLE:
        earlier = {study.ledger["sessions"].get(r) for r in FIRST_SESSION_ROLES}
        if identity.session_id in earlier:
            raise RecorderError(
                "the fresh-process run must use a newly started Painter process, but the "
                "session id is the first run's"
            )
    study.save()
    prefix = f"study-{study.study_id}-{role}-"
    target = inbox / "stability-study" / study.study_id
    work = study.directory / "work" / role
    for entry in study.ledger["goldens"].values():
        if entry["runs"].get(role, {}).get("status") == RECORDED:
            continue
        session.verify_identity(host)
        manifest = load_json(repo_root / entry["manifest"])
        try:
            run = record_golden(session, manifest, work, target, now, prefix, repo_root)
        except UnseenBuild as error:
            study.save()
            raise IdentityChanged(str(error)) from error
        except IdentityChanged:
            study.save()
            raise
        except RecorderError as error:
            entry["runs"][role] = {"status": REFUSED, "error": str(error)}
        else:
            entry["runs"][role] = {
                "status": RECORDED,
                "run": run.as_posix(),
                "session_id": identity.session_id,
            }
        study.save()
    session.verify_identity(host)


def run_study(
    study: Study,
    launcher: PainterLauncher | None,
    make_session: SessionFactory,
    inbox: Path,
    now: Now = utc_now,
    host: HostEnvironment | None = None,
    repo_root: Path = REPO_ROOT,
) -> Study:
    """Record runs `a` and `b` in one Painter process, then `c` in a freshly started one.

    Without a launcher, the operator's Painter is used for `a` and `b`, and the study stops
    before `c` (a fresh process needs the launcher, which never stops a Painter it did not
    start)."""
    from tools.parity.recorder.environment import capture_host_environment

    host = host or capture_host_environment
    inbox = ensure_outside_repository(inbox, repo_root)

    def done(role: str) -> bool:
        goldens = study.ledger["goldens"].values()
        return all(e["runs"].get(role, {}).get("status") == RECORDED for e in goldens)

    if not all(done(r) for r in FIRST_SESSION_ROLES):
        session = make_session()
        if launcher is not None:
            launcher.start()
        try:
            for role in FIRST_SESSION_ROLES:
                record_role(study, session, role, inbox, now, host, repo_root)
        finally:
            if launcher is not None:
                launcher.stop(session)
    if done(FRESH_ROLE):
        return study
    if launcher is None:
        raise RecorderError(
            "runs a and b are recorded; the fresh-process run needs the launcher (--launch) "
            f"to start a new Painter process: resume with --resume {study.directory}"
        )
    session = make_session()
    launcher.start()
    try:
        record_role(study, session, FRESH_ROLE, inbox, now, host, repo_root)
    finally:
        launcher.stop(session)
    return study


# --- analysis ----------------------------------------------------------------------------------


def pair_label(role: str, recording: str) -> str:
    return f"{role}.{recording}"


def classify(categories: Mapping[str, set[str]], complete: bool) -> str:
    if not complete:
        return INCOMPLETE
    if UNAVAILABLE in categories.get("status", set()):
        return UNAVAILABLE_CLASS
    differs = categories.get(DIFFERS, set())
    if "same_session" in differs:
        return SAME_SESSION
    if "save_reopen" in differs and "fresh_process" in differs:
        return BOTH
    if "fresh_process" in differs:
        return FRESH
    if "save_reopen" in differs:
        return SAVE_REOPEN
    return STABLE


def analyse_golden(
    golden_id: str, entry: Mapping[str, Any], labels: dict[str, str]
) -> dict[str, Any]:
    sources: dict[str, RecordSource] = {}
    runs: list[dict[str, Any]] = []
    for role in ROLES:
        info = entry["runs"].get(role)
        session_label = "session-0"
        if info is None or info["status"] != RECORDED:
            runs.append(
                {
                    "role": role,
                    "session": session_label,
                    "status": "refused" if info else "unavailable",
                }
            )
            continue
        session_id = str(info["session_id"])
        labels.setdefault(session_id, f"session-{len(labels) + 1}")
        run: dict[str, Any] = {"role": role, "session": labels[session_id], "status": RECORDED}
        try:
            source = run_source(Path(info["run"]))
        except (SourceUnavailable, OSError) as error:
            run["status"] = "unavailable"
            runs.append(run)
            del error
            continue
        sources[role] = source
        run["record_sha256"] = source.record_sha256
        environment = source.record.get("environment")
        if environment is not None:
            run["environment_sha256"] = environment_sha256(environment)
        run["recordings"] = source.recording_ids()
        runs.append(run)
    pairs = []
    differing: list[dict[str, Any]] = []
    categories: dict[str, set[str]] = {"status": set(), DIFFERS: set()}

    def add(left_role: str, left_id: str, right_role: str, right_id: str, category: str) -> None:
        comparison = compare_recordings(
            sources[left_role], left_id, sources[right_role], right_id, category
        )
        summary = comparison.summary()
        summary["left"] = pair_label(left_role, left_id)
        summary["right"] = pair_label(right_role, right_id)
        pairs.append(summary)
        label = f"{summary['left']}~{summary['right']}"
        differing.extend({"pair": label, **o} for o in comparison.differing_outputs())
        categories["status"].add(comparison.status)
        if comparison.status == DIFFERS:
            categories[DIFFERS].add(category)

    for role, source in sources.items():
        records = source.record["recordings"]
        first = str(records[0]["recording_id"])
        for recording in records[1:]:
            category = (
                "save_reopen" if recording["condition"] == "after_save_reopen" else "same_session"
            )
            add(role, first, role, str(recording["recording_id"]), category)
    if "a" in sources:
        first_a = sources["a"].recording_ids()[0]
        for role in ("b", "c"):
            if role in sources:
                same = entry["runs"][role]["session_id"] == entry["runs"]["a"]["session_id"]
                add(
                    "a",
                    first_a,
                    role,
                    sources[role].recording_ids()[0],
                    "same_session" if same else "fresh_process",
                )
    complete = set(sources) == set(ROLES)
    return {
        "golden_id": golden_id,
        "tier": entry["tier"],
        "classification": classify(categories, complete),
        "runs": runs,
        "pairs": pairs,
        "differing_outputs": differing,
    }


def analyse(study: Study, today: date) -> dict[str, Any]:
    labels: dict[str, str] = {}
    goldens = [
        analyse_golden(golden_id, entry, labels)
        for golden_id, entry in sorted(study.ledger["goldens"].items())
    ]
    summary: dict[str, int] = {"goldens": len(goldens)}
    for name in (STABLE, SAVE_REOPEN, FRESH, BOTH, SAME_SESSION, INCOMPLETE, UNAVAILABLE_CLASS):
        summary[name] = sum(g["classification"] == name for g in goldens)
    environments = sorted(
        {r["environment_sha256"] for g in goldens for r in g["runs"] if "environment_sha256" in r}
    )
    return {
        "schema": STUDY_SCHEMA,
        "study_id": study.study_id,
        "envelope_id": study.ledger["envelope_id"],
        "painter_build": study.ledger["painter_build"],
        "environment_sha256": environments,
        "generated_on": today.isoformat(),
        "goldens": goldens,
        "summary": summary,
    }


# --- prepared register entries (decision 034 (c), 017) -----------------------------------------


def next_exception_number(register_path: Path = REGISTER_PATH) -> int:
    register = load_json(register_path)
    numbers = [int(e["exception_id"].split("-")[1]) for e in register["entries"]]
    return max(numbers, default=0) + 1


def draft_entry(
    golden: Mapping[str, Any], entry: Mapping[str, Any], manifest: Mapping[str, Any], number: int
) -> dict[str, Any]:
    fresh = [
        o
        for o in golden["differing_outputs"]
        if o["pair"].startswith("a.") and o["pair"].split("~")[1].startswith("c.")
    ]
    maps = [o["difference"] for o in fresh if o.get("difference")]
    bounds: list[dict[str, Any]] = []
    if maps:
        bounds += [
            {"metric": "max_abs_diff", "scope": "whole", "max": max(d["max"] or 0 for d in maps)},
            {"metric": "mean_abs_diff", "scope": "whole", "max": max(d["mean"] or 0 for d in maps)},
            {
                "metric": "differing_percent",
                "scope": "whole",
                "max": round(max(100.0 * d["differing"] / d["total"] for d in maps), 4),
            },
        ]
    others = [o for o in fresh if not o.get("difference")]
    if others or not bounds:
        bounds.append({"metric": "differing_count", "scope": "whole", "max": len(others)})
    runs = {r["role"]: r for r in golden["runs"]}
    process = {"a": "first Painter process", "c": "freshly started Painter process"}
    evidence = [
        {
            "sha256": runs[role]["record_sha256"],
            "description": f"stability-study run {role} of {golden['golden_id']}: private record "
            f"with its recordings and blob hashes ({process[role]})",
        }
        for role in ("a", "c")
        if "record_sha256" in runs.get(role, {})
    ]
    return {
        "exception_id": f"EXC-{number:03d}",
        "version": 1,
        "tier": golden["tier"],
        "domain": {"kind": "channel", "selector": entry["domain"]},
        "bounds": bounds,
        "evidence": {
            "basis": "oracle_instability",
            "summary": (
                f"Painter is unstable across fresh processes on {golden['golden_id']}: the "
                "recording of a freshly started Painter process differs from the same-session "
                "recording r1 (parity/reports/phase0/oracle-envelope.md §2, classification "
                f"{golden['classification']}). Under decision 034 (c) r1 stays the exact target "
                "and every comparison against r1 must be exact; this entry would cover only "
                "comparisons against the fresh-process recording, per output in native units."
            ),
            "private_evidence": evidence,
            "uncontrolled_settings": list(manifest.get("uncontrolled_settings", [])),
        },
        "defect_detection_test": {
            "test_id": DEFECT_TEST,
            "injected_defects": list(INJECTED_DEFECTS),
            "outcome": "every_injected_defect_fails",
        },
        "decision_id": "034",
        "notes": (
            "Prepared by the stability study; provisional exception id. Before the owner "
            "approves it, the defect-detection test must be extended to this entry."
        ),
    }


def register_drafts(
    results: Mapping[str, Any], study: Study, repo_root: Path = REPO_ROOT
) -> dict[str, Any] | None:
    unstable = [g for g in results["goldens"] if g["classification"] in (FRESH, BOTH)]
    if not unstable:
        return None
    number = next_exception_number(repo_root / "parity" / "exceptions.json")
    drafts = []
    for offset, golden in enumerate(unstable):
        entry = study.entry(golden["golden_id"])
        manifest = load_json(repo_root / entry["manifest"])
        draft = draft_entry(golden, entry, manifest, number + offset)
        problems = draft_problems(draft)
        if problems:
            raise RecorderError(f"{golden['golden_id']}: prepared entry invalid: {problems}")
        drafts.append(draft)
    return {
        "schema": DRAFTS_SCHEMA,
        "study_id": results["study_id"],
        "envelope_id": results["envelope_id"],
        "status": "prepared_unapproved",
        "owner_fields": ["approved_by", "approved_on"],
        "drafts": drafts,
    }


def publish(study: Study, today: date, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Analyse, publish the results, the prepared entries (if any) and the Markdown report."""
    results = analyse(study, today)
    write_json(study_path(study.study_id, repo_root), results)
    drafts = register_drafts(results, study, repo_root)
    if drafts is not None:
        write_json(repo_root / DRAFTS_JSON, drafts)
    write_report(repo_root)
    return results


def admit(study: Study, store: Any, repo_root: Path = REPO_ROOT) -> list[Path]:
    """Admit every recorded run to the private store with the store CLI's own `record --run`.

    Each run is merged into a study manifest in the private study directory (never into the
    golden's repository manifest): `<study dir>/manifests/<golden path>.json`."""
    from tools.parity.store.manifest import record_run

    admitted: list[Path] = []
    for golden_id, entry in sorted(study.ledger["goldens"].items()):
        target = study.directory / "manifests" / f"{golden_id}.json"
        for role in ROLES:
            info = entry["runs"].get(role)
            if info is None or info["status"] != RECORDED:
                continue
            record_run(store, target, Path(info["run"]))
            admitted.append(Path(info["run"]))
    return admitted

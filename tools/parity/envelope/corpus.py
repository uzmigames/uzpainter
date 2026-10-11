"""Record any texture-corpus golden (tiers 0-2b) with the recorder command its manifest needs.

The corpus holds four kinds of jobs; each is recorded exactly as its own command records it
(`parity/RECORDER.md` §3, §8, §9):

- API probes (`tier0/api-probes`): `tools.parity.recorder.probes`;
- baking defaults (`record-defaults`) and shipped templates (`record-templates`);
- every other texture golden (`record`); one whose settings sheet names values only Painter's
  UI can set (`texture_sheet.py`) is recorded with the UI operator (`painter_ui.py`, decision
  029), so a refresh or a study never records a default in place of the sheet's value.

A job may be re-targeted to another Painter build (a refresh records the current envelope's
instruction sequences under the candidate build): only `software.painter` changes and
`private_records` is emptied; inputs, instructions and settings stay as authored.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.parity.recorder.defaults import (
    check_baking_job,
    check_template_job,
    record_baking_defaults,
    record_project_templates,
)
from tools.parity.recorder.job import job_from_manifest
from tools.parity.recorder.probes import probe_job_from_manifest, record_probe_golden
from tools.parity.recorder.session import PainterIdentity, PainterSession, RecorderError
from tools.parity.recorder.texture import record_texture_golden
from tools.parity.recorder.texture_sheet import Operator, texture_sheet
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors

TEXTURE, PROBE, DEFAULTS, TEMPLATES = "texture", "probe", "defaults", "templates"
Now = Callable[[], datetime]


def recorder_kind(manifest: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> str:
    """Which recorder command records this golden (refuses a Tier 3 or unrecordable job)."""
    if manifest["tier"] == "3":
        raise RecorderError(
            f"{manifest['golden_id']}: Tier 3 references are recorded by an operator"
        )
    try:
        job = job_from_manifest(dict(manifest), repo_root)
    except RecorderError:
        probe_job_from_manifest(dict(manifest), repo_root)
        return PROBE
    try:
        check_template_job(job)
        return TEMPLATES
    except RecorderError:
        pass
    try:
        check_baking_job(job)
        return DEFAULTS
    except RecorderError:
        pass
    return TEXTURE


def job_manifest(
    manifest: Mapping[str, Any], identity: PainterIdentity | None = None
) -> dict[str, Any]:
    """The manifest as a recording job: `private_records` empty and, with `identity`, the
    software identity of the build that records it."""
    job = copy.deepcopy(dict(manifest))
    job["private_records"] = []
    if identity is not None:
        job["software"]["painter"] = identity.painter_build()
    problems = validation_errors(job, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"{manifest['golden_id']}: job manifest invalid: {problems}")
    return job


def record_golden(
    session: PainterSession,
    manifest: Mapping[str, Any],
    work: Path,
    inbox: Path,
    now: Now,
    record_prefix: str = "",
    repo_root: Path = REPO_ROOT,
    operator: Operator | None = None,
) -> Path:
    """Record one golden with its own recorder command; returns the inbox run. A golden with
    UI-set values uses `operator`, by default the UI operator of Painter's panels."""
    kind = recorder_kind(manifest, repo_root)
    if kind == PROBE:
        probe = probe_job_from_manifest(dict(manifest), repo_root)
        return record_probe_golden(session, probe, work, inbox, now, record_prefix=record_prefix)
    job = job_from_manifest(dict(manifest), repo_root)
    if kind == TEMPLATES:
        return record_project_templates(session, job, work, inbox, now, record_prefix=record_prefix)
    if kind == DEFAULTS:
        return record_baking_defaults(session, job, work, inbox, now, record_prefix=record_prefix)
    if texture_sheet(job) and operator is None:
        operator = ui_operator(work)
    return record_texture_golden(
        session, job, work, inbox, now, record_prefix=record_prefix, operator=operator
    )


def ui_operator(work: Path) -> Operator:
    """The UI automation operator of Painter's panels (dev-only dependency, decision 029)."""
    from tools.parity.recorder.painter_ui import PainterUi, UiOperator

    return UiOperator(PainterUi(), work / "ui-operator")


def manifests_under(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.rglob("*.json")))
        elif path.is_file():
            found.append(path)
        else:
            raise RecorderError(f"{path} does not exist")
    return found


def golden_index(manifests: list[Path]) -> dict[str, Path]:
    """golden_id -> manifest path; refuses a golden named by two manifests."""
    index: dict[str, Path] = {}
    for path in manifests:
        golden_id = str(load_json(path)["golden_id"])
        if golden_id in index:
            raise RecorderError(f"{golden_id} is named by {index[golden_id]} and {path}")
        index[golden_id] = path
    return index

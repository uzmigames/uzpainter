"""The stability probe of decision 052's capture request (task `phase0.9_render-reference-capture`,
decision 062): its staged captures and their admission to the private store.

Each golden of `references.STABILITY_FIXTURES` holds two S renders staged by the recorder
(`python -m tools.parity.recorder iray ... --condition separate_session|same_session`) and no
k*S render, so the recorder never assembles a golden record from them. `admit` puts every blob
of the staged recordings into the private store under the golden's manifest, with the record ids
and kinds a recorder run uses (`<recording>-render-reference` as `iray_reference`,
`<recording>-panel-<panel>` as `settings_panel_evidence`) plus `<recording>-oracle-environment`
(`oracle_environment_record`, the environment record each capture was made under). The staged
recording JSON (session, condition, convergence, golden key) stays in the private work folder;
`staged_sha256` gives its hash for the report. Nothing here enters the repository but hashes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tools.parity.recorder.environment import environment_bytes
from tools.parity.recorder.iray import (
    SAME_SESSION,
    SEPARATE_SESSION,
    StagedRecording,
    load_staged,
)
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import slug
from tools.parity.render_procedure import references as refs
from tools.parity.store.manifest import record_file
from tools.parity.store.store import OracleStore

RENDERS = 2


class StabilityError(Exception):
    """A stability golden's staged captures are incomplete or inconsistent."""


@dataclass(frozen=True)
class Capture:
    """One staged S render of a stability golden."""

    golden: str
    recording_id: str
    condition: str
    session_id: str
    recorded_at: str
    render_sha256: str
    render_path: Path
    staged_sha256: str
    key_sha256: str
    staged: StagedRecording


def staging_folder(work: Path, fixture: refs.Fixture) -> Path:
    return work / "iray-staging" / fixture.golden_id.replace("/", "__")


def staged_sha256(folder: Path) -> str:
    return hashlib.sha256((folder / "staged.json").read_bytes()).hexdigest()


def captures(work: Path, fixture: refs.Fixture) -> list[Capture]:
    """The golden's staged S renders, checked: two renders, one key, the condition's sessions."""
    folder = staging_folder(work, fixture)
    found: list[Capture] = []
    for item, directory in zip(
        load_staged(folder), sorted(p.parent for p in folder.glob("*/staged.json")), strict=True
    ):
        recording = item.recording
        (render,) = [o for o in recording["outputs"] if o["kind"] == "iray_reference"]
        digest = render["blob"]["sha256"]
        path = directory / "blobs" / digest
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise StabilityError(f"{fixture.name}: render {digest} is missing from {directory}")
        found.append(
            Capture(
                fixture.name,
                recording["recording_id"],
                recording["condition"],
                recording["session_id"],
                recording["recorded_at"],
                digest,
                path,
                staged_sha256(directory),
                hashlib.sha256(canonical_json(item.key)).hexdigest(),
                item,
            )
        )
    if len(found) != RENDERS:
        raise StabilityError(f"{fixture.name}: {len(found)} staged renders, need {RENDERS}")
    conditions = {c.condition for c in found}
    sessions = {c.session_id for c in found}
    if conditions == {SEPARATE_SESSION} and len(sessions) != RENDERS:
        raise StabilityError(f"{fixture.name}: separate_session renders share a session")
    if conditions == {SAME_SESSION} and len(sessions) != 1:
        raise StabilityError(f"{fixture.name}: same_session renders come from two sessions")
    if conditions not in ({SEPARATE_SESSION}, {SAME_SESSION}):
        raise StabilityError(f"{fixture.name}: mixed conditions {sorted(conditions)}")
    if len({c.key_sha256 for c in found}) != 1:
        raise StabilityError(f"{fixture.name}: the staged renders disagree on the golden key")
    return found


def admit(
    store: OracleStore, work: Path, fixture: refs.Fixture, manifest: Path | None = None
) -> list[str]:
    """Store every blob of the golden's staged captures under its manifest (the committed one
    unless `manifest` is given); returns the record ids written."""
    manifest = manifest if manifest is not None else refs.manifest_path(fixture)
    written: list[str] = []
    for capture in captures(work, fixture):
        blobs = {p.name: p for p in capture.staged.blobs}
        prefix = slug(capture.recording_id)
        for output in capture.staged.recording["outputs"]:
            blob = output.get("blob")
            if blob is None:
                continue
            record_id = f"{prefix}-{slug(output['output_id'])}"
            record_file(store, manifest, record_id, output["kind"], blobs[blob["sha256"]])
            written.append(record_id)
        environment = capture.staged.environment
        if environment is not None:
            path = capture.render_path.parent.parent / "oracle-environment.json"
            path.write_bytes(environment_bytes(environment))
            record_id = f"{prefix}-oracle-environment"
            record_file(store, manifest, record_id, "oracle_environment_record", path)
            written.append(record_id)
    return written

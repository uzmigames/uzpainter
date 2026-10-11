"""Envelope registry: which Painter envelope is the acceptance oracle (decision 037).

`parity/envelopes/registry.json` (`parity/schema/envelope-registry.json`) is public: Painter
builds, envelope hashes, manifest roots and dates, never a recorded value. It names

- `current`: the newest promoted envelope, the only one gates and verdicts use;
- `candidate`: the envelope being recorded by a refresh, or null. Its build is recordable (the
  recorder's build guard admits the current and the candidate build), but nothing of it is used
  for acceptance until it is promoted;
- `envelopes`: every promoted envelope, `current` or `superseded` (history is kept, never
  deleted), each with the root of its public manifests;
- `quarantine`: aborted candidates and why.

Promotion and every other change replace the file atomically (`os.replace`), so a reader sees
the old registry or the new one, never a mixture. The 12.1.0 corpus keeps `parity/manifests` as
its manifest root; a promoted candidate's manifests live under
`parity/envelopes/<envelope directory>/manifests/` with the same relative paths.

Every filesystem path named after an envelope (work, inbox, quarantine, manifest root, drift
report) uses `envelope_directory(envelope_id)`, never the raw id: each character outside letters,
digits and `. _ ~ -` (the `+` of a Painter build string) becomes `_`, so a path under it passes
the recorder's file-URL rule (`tools.parity.recorder.texture.URL_SAFE_PATH`, which bakes need).
`envelope_id_for` never mints an id whose directory another registered id already has, so the
mapping is one-to-one within a registry. The ids themselves are unchanged everywhere else.
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.parity.recorder.environment import UNKNOWN, envelope_sha256
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors

REGISTRY_SCHEMA = "uzpainter/parity/envelope-registry/1"
REGISTRY_RELATIVE = Path("parity") / "envelopes" / "registry.json"
ENVELOPES_RELATIVE = Path("parity") / "envelopes"
CURRENT, SUPERSEDED = "current", "superseded"
TEXTURE_TIERS = frozenset({"0", "1", "2a", "2b"})
_NOT_DIRECTORY_SAFE = re.compile(r"[^A-Za-z0-9._~-]")


class RegistryError(Exception):
    """The registry is missing, invalid or inconsistent."""


def registry_path(repo_root: Path = REPO_ROOT) -> Path:
    return repo_root / REGISTRY_RELATIVE


def registry_problems(document: Any) -> list[str]:
    """Schema violations plus the rules a schema cannot state."""
    problems = validation_errors(document, Schema.ENVELOPE_REGISTRY)
    if problems:
        return problems
    ids = [e["envelope_id"] for e in document["envelopes"]]
    if len(ids) != len(set(ids)):
        problems.append(f"duplicate envelope ids {ids}")
    current = [e for e in document["envelopes"] if e["status"] == CURRENT]
    if len(current) != 1 or current[0]["envelope_id"] != document["current"]:
        problems.append("exactly one envelope must be current, and `current` must name it")
    candidate = document["candidate"]
    if candidate is not None:
        if candidate["envelope_id"] in ids:
            problems.append(f"candidate {candidate['envelope_id']} is already promoted")
        if candidate["previous"] != document["current"]:
            problems.append("the candidate must refresh the current envelope")
    quarantined = [q["envelope_id"] for q in document["quarantine"]]
    if set(quarantined) & set(ids):
        problems.append("a quarantined candidate id is also a promoted envelope")
    return problems


def load_registry(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    path = registry_path(repo_root)
    try:
        document = load_json(path)
    except (OSError, ValueError) as error:
        raise RegistryError(f"{path}: cannot read the envelope registry ({error})") from error
    problems = registry_problems(document)
    if problems:
        raise RegistryError(f"{path}: invalid envelope registry: " + "; ".join(problems))
    result: dict[str, Any] = document
    return result


def save_registry(document: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> None:
    """Validate, then replace the registry in one `os.replace` (the commit point of a change)."""
    problems = registry_problems(document)
    if problems:
        raise RegistryError(
            "refusing to write an invalid envelope registry: " + "; ".join(problems)
        )
    path = registry_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(temporary, path)


def envelope(document: Mapping[str, Any], envelope_id: str) -> dict[str, Any]:
    for entry in document["envelopes"]:
        if entry["envelope_id"] == envelope_id:
            result: dict[str, Any] = entry
            return result
    raise RegistryError(f"no envelope {envelope_id!r} in the registry")


def current_envelope(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The acceptance oracle: the newest promoted envelope (gates and verdicts use only it)."""
    document = load_registry(repo_root)
    return envelope(document, document["current"])


def recordable_builds(repo_root: Path = REPO_ROOT) -> frozenset[str]:
    """The recorder's build guard: the current envelope's build and the candidate's, if any."""
    document = load_registry(repo_root)
    builds = {envelope(document, document["current"])["painter_build"]}
    if document["candidate"] is not None:
        builds.add(document["candidate"]["painter_build"])
    return frozenset(builds)


def manifest_root(entry: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> Path:
    return repo_root / Path(str(entry["manifest_root"]))


def envelope_directory(envelope_id: str) -> str:
    """The directory name of an envelope: its id with every character outside letters, digits
    and `. _ ~ -` replaced by `_` (`painter-12.1.5+js-api.1.1.20` ->
    `painter-12.1.5_js-api.1.1.20`), so paths under it need no percent-encoding in a file URL."""
    return _NOT_DIRECTORY_SAFE.sub("_", envelope_id)


def candidate_manifest_root(envelope_id: str) -> str:
    return (ENVELOPES_RELATIVE / envelope_directory(envelope_id) / "manifests").as_posix()


def corpus_manifests(
    entry: Mapping[str, Any], repo_root: Path = REPO_ROOT, tiers: frozenset[str] = TEXTURE_TIERS
) -> list[Path]:
    """Manifests of an envelope whose tier is in `tiers`, sorted by path."""
    found: list[Path] = []
    for path in sorted(manifest_root(entry, repo_root).rglob("*.json")):
        document = load_json(path)
        if isinstance(document, dict) and document.get("tier") in tiers:
            found.append(path)
    return found


def envelope_id_for(build: str, environment: Mapping[str, Any], document: Mapping[str, Any]) -> str:
    """`painter-<build>`, or `painter-<build>-env-<hash>` when that build already has an
    envelope (a driver, GPU, OS or colour change under the same build). An id whose directory
    (`envelope_directory`) another registered id already has counts as used."""
    plain = f"painter-{build}"
    used = {e["envelope_id"] for e in document["envelopes"]}
    used |= {q["envelope_id"] for q in document["quarantine"]}
    used = {envelope_directory(i) for i in used}
    taken_builds = {e["painter_build"] for e in document["envelopes"]}
    if build not in taken_builds and envelope_directory(plain) not in used:
        return plain
    stem = f"{plain}-env-{envelope_sha256(environment)[:12]}"
    candidate, n = stem, 1
    while envelope_directory(candidate) in used:
        n += 1
        candidate = f"{stem}-{n}"
    return candidate


def record_prefix_for(build: str, document: Mapping[str, Any]) -> str:
    """Record-id prefix of a candidate: empty for a new build (the store keeps one corpus per
    build), `env-<n>-` when the build already has records, so no id is recorded twice."""
    count = sum(1 for e in document["envelopes"] if e["painter_build"] == build)
    return f"env-{count + 1}-" if count else ""


def initial_registry(
    build: str, version: str, manifest_root_path: str, promoted_on: str
) -> dict[str, Any]:
    """A registry whose only envelope is a corpus recorded before environment records existed
    (its environment fields other than the build are `unknown`)."""
    unknown = {
        "painter_build": build,
        "gpu_model": UNKNOWN,
        "driver_version": UNKNOWN,
        "os_build": UNKNOWN,
        "colour_configuration_sha256": UNKNOWN,
    }
    envelope_id = f"painter-{build}"
    return {
        "schema": REGISTRY_SCHEMA,
        "current": envelope_id,
        "candidate": None,
        "envelopes": [
            {
                "envelope_id": envelope_id,
                "status": CURRENT,
                "painter_build": build,
                "painter_version": version,
                "manifest_root": manifest_root_path,
                "record_prefix": "",
                "envelope_sha256": envelope_sha256(unknown),
                "environment_known": False,
                "equivalent_envelopes": [],
                "previous": None,
                "promoted_on": promoted_on,
                "superseded_on": None,
                "drift_report": None,
            }
        ],
        "quarantine": [],
    }


def updated(document: Mapping[str, Any]) -> dict[str, Any]:
    """A deep copy to change and save (the loaded document is never edited in place)."""
    return copy.deepcopy(dict(document))

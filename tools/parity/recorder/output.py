"""Output writer: private records to the oracle inbox, hashes into the public manifest (item 2.7).

Every recorded Painter output stays private (CONTRACT.md §6.4). The recorder writes one run
directory per recorded golden into the oracle inbox, outside the repository:

    <inbox>/<golden_id with "/" as "__">/<run>/record.json     private record (golden-private.json)
    <inbox>/<golden_id with "/" as "__">/<run>/blobs/<sha256>  every blob the record names
    <inbox>/<golden_id with "/" as "__">/<run>/manifest.json   public manifest with private_records
    <inbox>/<golden_id with "/" as "__">/<run>/READY           written last

`uzpainter parity record` (`phase0.3_oracle-store-cli`) admits a READY run into the private store
and merges its `private_records` into the repository manifest. Only SHA-256 values and sizes
reach the public manifest.

Environment record (decision 034 (a)): the record holds the session's `environment` in full, and
`blobs/<sha256>` holds its canonical JSON, named in the manifest as `oracle-environment` (kind
`oracle_environment_record`): the public manifest carries only that hash. A `record_prefix`
(stability study, canary, a second envelope under one build) is put in front of every record id
so that no store entry is ever recorded twice under one id.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.parity.recorder.environment import (
    ENVIRONMENT_KIND,
    ENVIRONMENT_RECORD_ID,
    environment_bytes,
)
from tools.parity.recorder.job import canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors

INBOX_ENV = "UZP_ORACLE_INBOX"
WORK_ENV = "UZP_ORACLE_WORK"
RECORD_FILE = "record.json"
MANIFEST_FILE = "manifest.json"
READY_FILE = "READY"
GOLDEN_RECORD_ID = "golden-record"


def local_app_data() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise RecorderError(f"LOCALAPPDATA is not set; set {INBOX_ENV} and {WORK_ENV}")
    return Path(base) / "UzPainter"


def private_dir(env: str, default_name: str, repo_root: Path = REPO_ROOT) -> Path:
    """A private directory from `env` (or under %LOCALAPPDATA%\\UzPainter), never in the repo."""
    configured = os.environ.get(env)
    path = Path(configured) if configured else local_app_data() / default_name
    return ensure_outside_repository(path, repo_root)


def inbox_root(repo_root: Path = REPO_ROOT) -> Path:
    return private_dir(INBOX_ENV, "oracle-inbox", repo_root)


def work_root(repo_root: Path = REPO_ROOT) -> Path:
    return private_dir(WORK_ENV, "oracle-work", repo_root)


def ensure_outside_repository(path: Path, repo_root: Path = REPO_ROOT) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(repo_root.resolve()):
        raise RecorderError(
            f"{resolved} is inside the repository {repo_root}: recorded outputs are private"
        )
    return resolved


def slug(text: str) -> str:
    """A record id fragment: lowercase, `[a-z0-9._-]`, starting with a letter or digit."""
    value = re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-._")
    return value or "output"


def run_name(session_id: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{slug(session_id)[:12]}"


def private_record_refs(
    record_bytes: bytes, record: dict[str, Any], blob_sizes: dict[str, int], prefix: str = ""
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = [
        {
            "record_id": prefix + GOLDEN_RECORD_ID,
            "kind": "private_oracle_record",
            "sha256": sha256_bytes(record_bytes),
            "size_bytes": len(record_bytes),
        }
    ]
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            blob = output.get("blob")
            if blob is None:
                continue
            refs.append(
                {
                    "record_id": (
                        f"{prefix}{slug(recording['recording_id'])}-{slug(output['output_id'])}"
                    ),
                    "kind": output["kind"],
                    "sha256": blob["sha256"],
                    "size_bytes": blob["size_bytes"],
                }
            )
            if blob_sizes.get(blob["sha256"]) != blob["size_bytes"]:
                raise RecorderError(f"blob {blob['sha256']} of {output['output_id']} is missing")
    ids = [r["record_id"] for r in refs]
    if len(ids) != len(set(ids)):
        raise RecorderError(f"duplicate private record ids {ids}")
    return refs


def public_manifest(
    template: dict[str, Any], build: dict[str, str], refs: list[dict[str, Any]]
) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(json.dumps(template))
    painter = manifest["software"]["painter"]
    if painter["build_id"] != build["build_id"]:
        raise RecorderError(
            f"manifest names Painter build {painter['build_id']!r} but the oracle is "
            f"{build['build_id']!r}: goldens are immutable per Painter build"
        )
    manifest["private_records"] = refs
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"public manifest invalid: {problems}")
    return manifest


def write_run(
    inbox: Path,
    record: dict[str, Any],
    blobs: list[Path],
    manifest_template: dict[str, Any],
    session_id: str,
    repo_root: Path = REPO_ROOT,
    *,
    environment: dict[str, Any] | None = None,
    record_prefix: str = "",
) -> Path:
    """Validate and write one run directory; returns it. Refuses before writing anything."""
    inbox = ensure_outside_repository(inbox, repo_root)
    if record_prefix and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*-", record_prefix):
        raise RecorderError(f"record prefix {record_prefix!r} is not `[a-z0-9][a-z0-9._-]*-`")
    if environment is not None:
        record = {**record, "environment": environment}
    problems = record_problems(record)
    if problems:
        raise RecorderError(f"private record invalid: {problems}")
    if record["golden_id"] != manifest_template["golden_id"]:
        raise RecorderError("record and manifest name different goldens")
    hashes = {sha256_file(b): b for b in blobs}
    sizes = {h: p.stat().st_size for h, p in hashes.items()}
    record_bytes = canonical_json(record)
    refs = private_record_refs(record_bytes, record, sizes, record_prefix)
    named = {r["sha256"] for r in refs[1:]}
    if named != set(hashes):
        raise RecorderError("blobs given do not match the blobs the record names")
    environment_data = environment_bytes(environment) if environment is not None else None
    if environment_data is not None:
        refs.append(
            {
                "record_id": record_prefix + ENVIRONMENT_RECORD_ID,
                "kind": ENVIRONMENT_KIND,
                "sha256": sha256_bytes(environment_data),
                "size_bytes": len(environment_data),
            }
        )
    manifest = public_manifest(manifest_template, record["key"]["painter_build"], refs)
    run: Path = inbox / str(record["golden_id"]).replace("/", "__") / run_name(session_id)
    if run.exists():
        raise RecorderError(f"{run} already exists")
    (run / "blobs").mkdir(parents=True)
    for digest, path in hashes.items():
        shutil.copyfile(path, run / "blobs" / digest)
        if sha256_file(run / "blobs" / digest) != digest:
            raise RecorderError(f"copy of {path} does not hash to {digest}")
    if environment_data is not None:
        (run / "blobs" / sha256_bytes(environment_data)).write_bytes(environment_data)
    (run / RECORD_FILE).write_bytes(record_bytes)
    (run / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (run / READY_FILE).write_bytes(b"")
    return run

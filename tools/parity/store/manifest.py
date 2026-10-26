"""`record`, `fetch` and `verify` over public manifests (`parity/schema/golden-public.json`).

The manifest names every private record by `record_id`, `kind`, SHA-256 and size; the store holds
the bytes. `record` stores bytes and writes their hashes into the manifest, `fetch` copies the
named blobs out of the store, `verify` re-hashes them in the store. A blob that cannot be
resolved is `oracle_unavailable`, never a pass.
"""

from __future__ import annotations

import copy
import json
import mimetypes
import os
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.schemas import Schema, load_json, record_problems, validation_errors
from tools.parity.store.store import (
    OracleStore,
    Resolution,
    Status,
    StoreError,
    refuse_inside_repository,
    refuse_snapshot_kind,
    resolve_oracle,
    sha256_file,
)

RECORD_KIND = "private_oracle_record"
READY_MARKER = "READY"


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        document = load_json(path)
    except (OSError, ValueError) as error:
        raise StoreError(f"{path}: cannot read the manifest ({error})") from error
    errors = validation_errors(document, Schema.GOLDEN_PUBLIC)
    if errors:
        raise StoreError(f"{path}: not a valid public manifest: " + "; ".join(errors))
    result: dict[str, Any] = document
    return result


def write_manifest(path: Path, document: dict[str, Any]) -> None:
    errors = validation_errors(document, Schema.GOLDEN_PUBLIC)
    if errors:
        raise StoreError(f"{path}: the updated manifest is invalid: " + "; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _painter_build(manifest: dict[str, Any]) -> str:
    build: str = manifest["software"]["painter"]["build_id"]
    return build


def _check_private_record(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """A `private_oracle_record` file is a valid record of the manifest's golden and build."""
    try:
        record = load_json(path)
    except (OSError, ValueError) as error:
        raise StoreError(f"{path}: not a JSON private record ({error})") from error
    problems = record_problems(record)
    if problems:
        raise StoreError(f"{path}: invalid private record: " + "; ".join(problems))
    if record["golden_id"] != manifest["golden_id"]:
        raise StoreError(f"{path}: golden {record['golden_id']} is not {manifest['golden_id']}")
    if record["key"]["painter_build"]["build_id"] != _painter_build(manifest):
        raise StoreError(f"{path}: Painter build differs from the manifest's")
    result: dict[str, Any] = record
    return result


@dataclass(frozen=True)
class _Pending:
    ref: dict[str, Any]
    source: Path
    file_name: str


def _merge(store: OracleStore, manifest: dict[str, Any], pending: list[_Pending]) -> dict[str, Any]:
    """Refuse every conflict first, then store the blobs and return the updated manifest."""
    for ref in [*manifest["private_records"], *(item.ref for item in pending)]:
        refuse_snapshot_kind(ref["kind"])
    build, golden = _painter_build(manifest), manifest["golden_id"]
    refs: list[dict[str, Any]] = manifest["private_records"]
    by_id = {ref["record_id"]: ref for ref in refs}
    for item in pending:
        known = by_id.get(item.ref["record_id"])
        if known is not None and known["sha256"] != item.ref["sha256"]:
            raise StoreError(
                f"the manifest already names {known['sha256']} as record "
                f"{item.ref['record_id']}; refusing to record {item.ref['sha256']} "
                "under the same id"
            )
        store.refuse_conflict(build, golden, item.ref["record_id"], item.ref["sha256"])
    updated = copy.deepcopy(manifest)
    for item in pending:
        stored = store.add_record(
            build,
            golden,
            item.ref["record_id"],
            item.ref["kind"],
            item.source,
            item.ref["sha256"],
            item.file_name,
        )
        if item.ref["record_id"] not in by_id:
            entry = {
                "record_id": stored.record_id,
                "kind": stored.kind,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
            }
            updated["private_records"].append(entry)
            by_id[stored.record_id] = entry
    return updated


def record_file(
    store: OracleStore, manifest_path: Path, record_id: str, kind: str, source: Path
) -> dict[str, Any]:
    """Store one recorded file and write its hash into an existing manifest."""
    refuse_snapshot_kind(kind)
    manifest = load_manifest(manifest_path)
    if kind == RECORD_KIND:
        _check_private_record(source, manifest)
    sha256, size = sha256_file(source)
    ref = {"record_id": record_id, "kind": kind, "sha256": sha256, "size_bytes": size}
    updated = _merge(store, manifest, [_Pending(ref, source, source.name)])
    write_manifest(manifest_path, updated)
    return updated


def _blob_media_types(record: Any) -> Iterator[tuple[str, str]]:
    if isinstance(record, dict):
        blob = record.get("blob")
        if isinstance(blob, dict) and {"sha256", "media_type"} <= blob.keys():
            yield blob["sha256"], blob["media_type"]
        for value in record.values():
            yield from _blob_media_types(value)
    elif isinstance(record, list):
        for value in record:
            yield from _blob_media_types(value)


def record_run(store: OracleStore, manifest_path: Path, run_dir: Path) -> dict[str, Any]:
    """Ingest one recorder run from the oracle inbox (`parity/STORE.md` §4).

    The run holds `manifest.json` (public, `private_records` filled), `record.json` (the private
    record), `blobs/<sha256>` and the `READY` marker written last. The target manifest is created
    from the run's manifest, or its `private_records` are merged into the existing one.
    """
    if not (run_dir / READY_MARKER).is_file():
        raise StoreError(f"{run_dir}: no {READY_MARKER} marker; the run is incomplete")
    run_manifest = load_manifest(run_dir / "manifest.json")
    for ref in run_manifest["private_records"]:
        refuse_snapshot_kind(ref["kind"])
    files: dict[str, tuple[Path, int]] = {}
    for path in [run_dir / "record.json", *sorted((run_dir / "blobs").glob("*"))]:
        sha256, size = sha256_file(path)
        if path.parent.name == "blobs" and path.name != sha256:
            raise StoreError(f"{path}: named {path.name} but hashes to {sha256}")
        files[sha256] = (path, size)
    media_types: dict[str, str] = {}
    named_blobs: set[str] = set()
    pending: list[_Pending] = []
    for ref in run_manifest["private_records"]:
        found = files.get(ref["sha256"])
        if found is None or found[1] != ref["size_bytes"]:
            raise StoreError(
                f"{run_dir}: no file matches record {ref['record_id']} ({ref['sha256']})"
            )
        source = found[0]
        if ref["kind"] == RECORD_KIND:
            record = _check_private_record(source, run_manifest)
            for sha256, media_type in _blob_media_types(record):
                media_types[sha256] = media_type
                named_blobs.add(sha256)
        pending.append(_Pending(ref, source, ""))
    missing = named_blobs - {item.ref["sha256"] for item in pending}
    if missing:
        raise StoreError(
            f"{run_dir}: the private record names blobs the manifest omits: {sorted(missing)}"
        )
    pending = [
        _Pending(
            item.ref,
            item.source,
            item.ref["record_id"]
            + (
                ".json"
                if item.ref["kind"] == RECORD_KIND
                else mimetypes.guess_extension(media_types.get(item.ref["sha256"], "")) or ""
            ),
        )
        for item in pending
    ]
    if manifest_path.exists():
        target = load_manifest(manifest_path)
        if target["golden_id"] != run_manifest["golden_id"]:
            raise StoreError(f"{manifest_path}: golden {target['golden_id']} is not the run's")
        if _painter_build(target) != _painter_build(run_manifest):
            raise StoreError(f"{manifest_path}: Painter build differs from the run's")
    else:
        target = copy.deepcopy(run_manifest)
        target["private_records"] = []
    updated = _merge(store, target, pending)
    write_manifest(manifest_path, updated)
    return updated


def fetch(store: OracleStore | None, manifest: dict[str, Any], out_dir: Path) -> list[Resolution]:
    """Copy every blob the manifest names to `out_dir` (outside the repository) and re-verify."""
    refuse_inside_repository(out_dir, "fetch destination")
    results: list[Resolution] = []
    for ref in manifest["private_records"]:
        resolution = resolve_oracle(store, ref)
        if resolution.status is Status.AVAILABLE and resolution.path is not None:
            assert store is not None
            entry = store.entry(_painter_build(manifest), manifest["golden_id"], ref["record_id"])
            suffix = Path(entry.file_name).suffix if entry and entry.sha256 == ref["sha256"] else ""
            destination = out_dir / f"{ref['record_id']}{suffix}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            shutil.copyfile(resolution.path, temporary)
            os.replace(temporary, destination)
            found, size = sha256_file(destination)
            if found != ref["sha256"] or size != ref["size_bytes"]:
                resolution = Resolution(
                    ref["record_id"],
                    ref["sha256"],
                    Status.ORACLE_UNAVAILABLE,
                    "copy fails its hash",
                )
            else:
                resolution = Resolution(
                    ref["record_id"], ref["sha256"], Status.AVAILABLE, path=destination
                )
        results.append(resolution)
    return results


def verify(store: OracleStore | None, manifest: dict[str, Any]) -> list[Resolution]:
    """Re-hash every blob the manifest names in the store."""
    return [resolve_oracle(store, ref) for ref in manifest["private_records"]]

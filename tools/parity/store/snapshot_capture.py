"""Private snapshot admission: trusted fresh validation followed by immutable publication."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.parity.store.snapshot_contract import (
    ADMISSION_SCHEMA,
    PROTOCOL,
    SHA256,
    capture_id,
    parse_admission_document,
    parse_document,
    parse_policy,
)
from tools.parity.store.snapshot_validator import validate_snapshot_capture
from tools.parity.store.store import (
    OracleStore,
    Resolution,
    Status,
    StoreError,
    publish_no_replace,
    refuse_inside_repository,
    sha256_file,
)


@dataclass(frozen=True)
class CaptureResolution:
    status: Status
    reason: str = ""
    document: dict[str, Any] | None = field(default=None, repr=False)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise StoreError(reason)


def _hash(value: str) -> None:
    _require(type(value) is str and SHA256.fullmatch(value) is not None, "invalid snapshot hash")


def admission_path(store: OracleStore, capture: str, policy: str) -> Path:
    _hash(capture)
    _hash(policy)
    return store.root / "snapshot-captures" / capture / f"{policy}.json"


def _policy_path(store: OracleStore, policy: str) -> Path:
    _hash(policy)
    return store.root / "snapshot-producer-policies" / f"{policy}.json"


def _refs(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        artifacts["receipt"],
        artifacts["request"],
        *artifacts["scalar_exports"],
        *artifacts["rgb_exports"],
    ]


def _read_regular(path: Path) -> bytes:
    _require(
        path.is_file() and not path.is_symlink() and not path.is_junction(),
        "snapshot file unavailable",
    )
    return path.read_bytes()


def _policy(data: bytes, sha: str, revision: int) -> dict[str, Any]:
    _hash(sha)
    _require(type(revision) is int and 1 <= revision < (1 << 63), "invalid policy revision")
    _require(hashlib.sha256(data).hexdigest() == sha, "snapshot policy hash differs")
    policy = parse_policy(data)
    _require(policy["revision"] == revision, "snapshot policy revision differs")
    return policy


def resolve_snapshot_capture(
    store: OracleStore | None,
    capture: str,
    *,
    approved_policy_sha256: str,
    approved_policy_revision: int,
) -> CaptureResolution:
    """Resolve a complete admission using caller-approved policy pins, never bare blobs."""
    try:
        _require(store is not None, "no private snapshot store")
        assert store is not None
        path = admission_path(store, capture, approved_policy_sha256)
        document = parse_admission_document(_read_regular(path))
        _require(document["capture_id"] == capture, "snapshot path capture id differs")
        _require(
            document["producer_policy"]
            == {"sha256": approved_policy_sha256, "revision": approved_policy_revision},
            "snapshot policy identity differs",
        )
        policy = _policy(
            _read_regular(_policy_path(store, approved_policy_sha256)),
            approved_policy_sha256,
            approved_policy_revision,
        )
        artifacts = document["artifacts"]
        for ref in _refs(artifacts):
            resolved = store.resolve(ref["record_id"], ref["sha256"], ref["size_bytes"])
            _require(resolved.status is Status.AVAILABLE, "snapshot artifact unavailable")
        receipt_ref = artifacts["receipt"]
        receipt_bytes = store.load(receipt_ref["sha256"], receipt_ref["size_bytes"])
        _require(receipt_bytes is not None, "snapshot receipt unavailable")
        assert receipt_bytes is not None
        recorder = parse_document(receipt_bytes).get("recorder")
        _require(
            type(recorder) is dict and set(recorder) == {"bridge_sha256", "painter_side_sha256"},
            "snapshot recorder identity differs",
        )
        assert isinstance(recorder, dict)
        _require(
            any(
                all(row[key] == value for key, value in recorder.items())
                for row in policy["producers"]
            ),
            "snapshot producer absent from policy",
        )
        return CaptureResolution(Status.AVAILABLE, document=document)
    except (OSError, ValueError, StoreError):
        return CaptureResolution(
            Status.ORACLE_UNAVAILABLE, "snapshot admission, policy or artifacts unavailable"
        )


def resolve_snapshot_artifact(
    store: OracleStore | None,
    capture: str,
    ref: dict[str, Any],
    *,
    approved_policy_sha256: str,
    approved_policy_revision: int,
) -> Resolution:
    """An exact role/round/hash/size member of an available capture, never a generic hash."""
    result = resolve_snapshot_capture(
        store,
        capture,
        approved_policy_sha256=approved_policy_sha256,
        approved_policy_revision=approved_policy_revision,
    )
    exact_ref = (
        set(ref) == {"record_id", "kind", "sha256", "size_bytes"}
        and type(ref.get("size_bytes")) is int
        and all(type(ref.get(key)) is str for key in ("record_id", "kind", "sha256"))
    )
    if exact_ref and result.document is not None and ref in _refs(result.document["artifacts"]):
        assert store is not None
        return store.resolve(ref["record_id"], ref["sha256"], ref["size_bytes"])
    return Resolution(
        str(ref.get("record_id", "")),
        str(ref.get("sha256", "")),
        Status.ORACLE_UNAVAILABLE,
        "not a member of an available snapshot admission",
    )


def _publish_bytes(store: OracleStore, target: Path, data: bytes) -> None:
    if target.exists():
        _require(_read_regular(target) == data, "immutable snapshot file conflicts")
        return
    staging = store.staging_path()
    with staging.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(staging, stat.S_IREAD)
    if not publish_no_replace(staging, target):
        _require(_read_regular(target) == data, "immutable snapshot file conflicts")


def _existing(store: OracleStore, proposed: dict[str, Any]) -> dict[str, Any]:
    policy = proposed["producer_policy"]
    result = resolve_snapshot_capture(
        store,
        proposed["capture_id"],
        approved_policy_sha256=policy["sha256"],
        approved_policy_revision=policy["revision"],
    )
    _require(result.document is not None, "existing snapshot admission unavailable")
    assert result.document is not None
    existing = result.document
    for key in ("schema", "protocol", "capture_id", "producer_policy", "artifacts", "provenance"):
        _require(existing[key] == proposed[key], "existing snapshot admission conflicts")
    for key in ("signature_sha256", "capture_context_sha256", "scalar_raster_sha256"):
        _require(
            existing["validation"][key] == proposed["validation"][key],
            "revalidated snapshot semantics conflict",
        )
    return existing


def admit_snapshot_capture(
    store: OracleStore,
    work: Path,
    *,
    binary: Path,
    approved_binary_sha256: str,
    approved_code_sha256: str,
    policy_bytes: bytes,
    approved_policy_sha256: str,
    approved_policy_revision: int,
) -> dict[str, Any]:
    """Fresh trusted invocation every time; publish complete admission last, without overwrite.

    An idempotent retry retains the original timestamp and validator identity after fresh
    semantic comparison. This does not claim historical execution attestation.
    """
    try:
        refuse_inside_repository(store.root, "store")
        refuse_inside_repository(work, "snapshot recording")
        _policy(policy_bytes, approved_policy_sha256, approved_policy_revision)
        result = validate_snapshot_capture(
            work,
            binary=binary,
            approved_binary_sha256=approved_binary_sha256,
            approved_code_sha256=approved_code_sha256,
            policy_bytes=policy_bytes,
            approved_policy_sha256=approved_policy_sha256,
            approved_policy_revision=approved_policy_revision,
        )
        report = result.report
        artifacts = report["artifacts"]
        proposed = {
            "schema": ADMISSION_SCHEMA,
            "protocol": PROTOCOL,
            "capture_id": capture_id(artifacts),
            "producer_policy": {
                "sha256": approved_policy_sha256,
                "revision": approved_policy_revision,
            },
            "artifacts": artifacts,
            "provenance": {"basis": "owner_local_submission", "execution_attestation": "none"},
            "validation": {
                "validator_revision": report["validator"]["revision"],
                "validator_code_sha256": report["validator"]["code_sha256"],
                "validator_binary_sha256": report["validator"]["binary_sha256"],
                "signature_sha256": report["signature_sha256"],
                "capture_context_sha256": report["capture_context_sha256"],
                "scalar_raster_sha256": report["scalar_raster_sha256"],
            },
            "admitted_at": datetime.now(UTC).isoformat(),
        }
        data = (json.dumps(proposed, indent=2) + "\n").encode("utf-8")
        parse_admission_document(data)
        paths = [
            work / "capture.json",
            work / "request.json",
            *(work / f"export{i}" / "user0.exr" for i in (1, 2)),
            *(work / f"export{i}" / "user1.exr" for i in (1, 2)),
        ]
        for path, ref in zip(paths, _refs(artifacts), strict=True):
            _require(
                sha256_file(path) == (ref["sha256"], ref["size_bytes"]),
                "snapshot source changed after validation",
            )
        target = admission_path(store, proposed["capture_id"], approved_policy_sha256)
        if target.exists():
            return _existing(store, proposed)
        _publish_bytes(store, _policy_path(store, approved_policy_sha256), policy_bytes)
        for path, ref in zip(paths, _refs(artifacts), strict=True):
            size = store.put_blob(path, ref["sha256"])
            _require(size == ref["size_bytes"], "stored snapshot size differs")
        # Stage a closed document only after every exact blob is durable and indexed.
        staging = store.staging_path()
        with staging.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staging, stat.S_IREAD)
        publish_no_replace(staging, target)
        return _existing(store, proposed)
    except StoreError:
        raise
    except (OSError, ValueError) as error:
        raise StoreError("snapshot capture admission refused") from error


def check_snapshot_captures(store: OracleStore) -> list[str]:
    """Integrity only: this does not grant approval to a policy found on disk."""
    problems: list[str] = []
    root = store.root / "snapshot-captures"
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        try:
            _require(
                path.parent.parent == root and path.suffix == ".json",
                "unexpected snapshot namespace entry",
            )
            document = parse_admission_document(_read_regular(path))
            result = resolve_snapshot_capture(
                store,
                path.parent.name,
                approved_policy_sha256=path.stem,
                approved_policy_revision=document["producer_policy"]["revision"],
            )
            _require(result.status is Status.AVAILABLE, "snapshot admission unavailable")
        except (OSError, ValueError, StoreError):
            problems.append(
                f"snapshot admission {path.relative_to(store.root).as_posix()} is unavailable"
            )
    for path in sorted((store.root / "snapshot-producer-policies").glob("*")):
        try:
            _require(path.suffix == ".json", "unexpected snapshot policy entry")
            data = _read_regular(path)
            policy = parse_policy(data)
            _policy(data, path.stem, policy["revision"])
        except (OSError, ValueError, StoreError):
            problems.append(f"snapshot policy {path.name} is unavailable")
    return problems

"""Invoke a coordinator-pinned native H diagnostic; never admit or publish evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.snapshot_host_transport import REPO, host_transport, recorder_pin_provenance
from tools.parity.store.snapshot_contract import (
    PROTOCOL,
    SHA256,
    parse_document,
    parse_policy,
    parse_validation_report,
    typed_hash,
    validate_artifact_slots,
)
from tools.parity.store.store import sha256_file

INPUT_SCHEMA = "uzpainter/parity/snapshot-capture-validation-input/1"
INPUT_LIMIT = 64 * 1024
TIMEOUT_SECONDS = 120


class ValidationRefused(ValueError):
    """A private diagnostic failed its invocation or identity checks."""


@dataclass(frozen=True)
class SnapshotValidation:
    """Private diagnostic result, not an admission or proof of historical execution."""

    report: dict[str, Any] = field(repr=False)
    producer_policy_sha256: str
    producer_policy_revision: int
    producer_source_revision: str


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValidationRefused(reason)


def _fingerprint(path: Path) -> tuple[str, int]:
    _require(
        path.is_file() and not path.is_symlink() and not path.is_junction(),
        "diagnostic input must be a regular file",
    )
    return sha256_file(path)


def validate_snapshot_capture(
    work: Path,
    *,
    binary: Path,
    approved_binary_sha256: str,
    approved_code_sha256: str,
    policy_bytes: bytes,
    approved_policy_sha256: str,
    approved_policy_revision: int,
    repo: Path = REPO,
) -> SnapshotValidation:
    """Execute only the explicitly pinned binary and join its report to unchanged inputs.

    Approval pins are trusted coordinator inputs, never inferred from capture contents or a
    cached report. The caller must still verify bytes at any later publication boundary.
    """
    try:
        return _validate(
            work,
            binary,
            approved_binary_sha256,
            approved_code_sha256,
            policy_bytes,
            approved_policy_sha256,
            approved_policy_revision,
            repo,
        )
    except ValidationRefused:
        raise
    except (OSError, ValueError):
        raise ValidationRefused("snapshot diagnostic inputs or report refused") from None


def _validate(
    work: Path,
    binary: Path,
    binary_sha: str,
    code_sha: str,
    policy_bytes: bytes,
    policy_sha: str,
    policy_revision: int,
    repo: Path,
) -> SnapshotValidation:
    _require(binary.is_absolute(), "validator binary must be absolute")
    _require(
        all(
            type(pin) is str and SHA256.fullmatch(pin) is not None
            for pin in (binary_sha, code_sha, policy_sha)
        ),
        "invalid coordinator hash pin",
    )
    _require(
        type(policy_revision) is int and 1 <= policy_revision < (1 << 63),
        "invalid approved policy revision",
    )
    _require(hashlib.sha256(policy_bytes).hexdigest() == policy_sha, "producer policy hash differs")
    policy = parse_policy(policy_bytes)
    _require(policy["revision"] == policy_revision, "producer policy revision differs")
    before_binary = _fingerprint(binary)
    _require(before_binary[0] == binary_sha, "validator binary hash differs")
    # Preserve slot identity even when repeated rounds have identical hashes.
    paths = [
        work / "capture.json",
        work / "request.json",
        *(work / f"export{i}" / "user0.exr" for i in (1, 2)),
        *(work / f"export{i}" / "user1.exr" for i in (1, 2)),
    ]
    observed = [*paths, work / "context.json", work / "mesh.obj"]
    before = [_fingerprint(path) for path in observed]
    transport = host_transport(work)
    _require(
        transport.source_fingerprints == dict(zip(observed, before, strict=True)),
        "input bytes changed during transport",
    )
    pins = transport.recorder
    producers = [
        row
        for row in policy["producers"]
        if row["protocol"] == PROTOCOL and all(row[key] == value for key, value in pins.items())
    ]
    _require(len(producers) == 1, "producer absent from pinned policy")
    revision = producers[0]["source_revision"]
    recorder_pin_provenance(pins, revision, repo)
    artifacts = {key: value for key, value in transport.section.items() if key != "protocol"}
    refs = [
        artifacts["receipt"],
        artifacts["request"],
        *artifacts["scalar_exports"],
        *artifacts["rgb_exports"],
    ]
    ids = ("receipt", "request", "r1-scalar", "r2-scalar", "r1-rgb", "r2-rgb")
    for ref, record_id, fingerprint in zip(refs, ids, before[:6], strict=True):
        ref["record_id"] = record_id
        _require(
            (ref["sha256"], ref["size_bytes"]) == fingerprint, "artifact changed during transport"
        )
    validate_artifact_slots(artifacts)
    receipt_bytes = paths[0].read_bytes()
    _require(
        (hashlib.sha256(receipt_bytes).hexdigest(), len(receipt_bytes)) == before[0],
        "receipt bytes changed during read",
    )
    receipt = parse_document(receipt_bytes)
    input_paths = [{"path": str(path.absolute())} for path in paths]
    request = {
        "schema": INPUT_SCHEMA,
        "protocol": PROTOCOL,
        "receipt": input_paths[0],
        "request": input_paths[1],
        "scalar_exports": input_paths[2:4],
        "rgb_exports": input_paths[4:6],
    }
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _require(len(encoded) <= INPUT_LIMIT, "validator input exceeds 64 KiB")
    _require([_fingerprint(path) for path in observed] == before, "input changed before invocation")
    _require(_fingerprint(binary) == before_binary, "validator changed before invocation")
    try:
        completed = subprocess.run(
            [str(binary), "snapshot-capture-validate", "--input-stdin"],
            input=encoded,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ValidationRefused("snapshot validator timed out") from None
    _require(_fingerprint(binary) == before_binary, "validator changed during invocation")
    _require([_fingerprint(path) for path in observed] == before, "input changed during invocation")
    _require(completed.returncode == 0, "native snapshot validator refused or failed")
    report = parse_validation_report(completed.stdout)
    _require(report["artifacts"] == artifacts, "native artifact references differ")
    _require(report["producer"] == pins, "native producer differs")
    _require(report["validator"]["binary_sha256"] == binary_sha, "native binary identity differs")
    _require(report["validator"]["code_sha256"] == code_sha, "native code identity differs")
    # SignatureHash(request) normalizes parameter numbers by value. Only the pinned native
    # validator computes that key; raw receipt/readback typed hashes have different semantics.
    _require(
        report["capture_context_sha256"] == typed_hash(receipt["readback"]),
        "native context differs",
    )
    return SnapshotValidation(report, policy_sha, policy["revision"], revision)

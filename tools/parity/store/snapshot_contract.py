"""Pure structural contracts for proposed private H admission (decision 363).

Successful parsing proves shapes and internal hash links only. It does not admit bytes,
approve a producer policy, authenticate Painter execution or verify a native report's
claims. Trusted validator execution, artifact resolution and store publication remain
separate dependencies. No file access, subprocess or store mutation occurs in these APIs.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any

from tools.parity.filter_observation_import import closed, parse, require, typed_json

PROTOCOL = "paired-scalar-rgb"
POLICY_SCHEMA = "uzpainter/parity/snapshot-producer-policy/1"
ADMISSION_SCHEMA = "uzpainter/parity/snapshot-capture-admission/1"
REPORT_SCHEMA = "uzpainter/parity/snapshot-capture-validation/1"
VALIDATOR_REVISION = "uzpainter/snapshot-capture-validator/1"
ARTIFACT_KEYS = {
    "receipt",
    "request",
    "environment",
    "environment_binding",
    "scalar_exports",
    "rgb_exports",
}
SHA256 = re.compile(r"[0-9a-f]{64}")
SOURCE_REVISION = re.compile(r"[0-9a-f]{40}")
UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)")


def parse_document(data: bytes) -> dict[str, Any]:
    """Strict UTF-8 JSON with shared int64/double, duplicate and underflow rules."""
    try:
        data.decode("utf-8")
    except UnicodeError:
        raise ValueError("snapshot contract requires UTF-8") from None
    return parse(data)


def typed_hash(value: Any) -> str:
    """Hash typed canonical JSON; integers, doubles and signed zero remain distinct."""
    return hashlib.sha256(typed_json(value)).hexdigest()


def _hash(value: Any, field: str) -> None:
    require(type(value) is str and SHA256.fullmatch(value) is not None, f"invalid {field}")


def _integer(value: Any, minimum: int, field: str) -> None:
    require(type(value) is int and minimum <= value < (1 << 63), f"invalid {field}")


def _reference(value: Any, record_id: str, kind: str) -> None:
    ref = closed(value, {"record_id", "kind", "sha256", "size_bytes"}, "artifact reference fields")
    require(ref["record_id"] == record_id and ref["kind"] == kind, "artifact role or round differs")
    _hash(ref["sha256"], "artifact hash")
    _integer(ref["size_bytes"], 0, "artifact size")


def validate_artifact_slots(value: Any) -> dict[str, Any]:
    """Validate six role/round slots, retaining repeated hashes; never resolve their bytes."""
    typed_json(value)
    artifacts = closed(value, ARTIFACT_KEYS, "artifact slots")
    require(
        artifacts["environment"] is None and artifacts["environment_binding"] is None,
        "H environment representation unsupported",
    )
    _reference(artifacts["receipt"], "receipt", "snapshot_receipt")
    _reference(artifacts["request"], "request", "snapshot_request")
    for field, role in (("scalar_exports", "scalar"), ("rgb_exports", "rgb")):
        exports = artifacts[field]
        require(type(exports) is list and len(exports) == 2, "two ordered exports required")
        for index, ref in enumerate(exports, 1):
            _reference(ref, f"r{index}-{role}", f"snapshot_{role}_export")
    sizes: dict[str, int] = {}
    for ref in [
        artifacts["receipt"],
        artifacts["request"],
        *artifacts["scalar_exports"],
        *artifacts["rgb_exports"],
    ]:
        require(
            ref["sha256"] not in sizes or sizes[ref["sha256"]] == ref["size_bytes"],
            "one artifact hash has conflicting sizes",
        )
        sizes[ref["sha256"]] = ref["size_bytes"]
    return artifacts


def parse_artifact_slots(data: bytes) -> dict[str, Any]:
    return validate_artifact_slots(parse_document(data))


def capture_id(artifacts: Any) -> str:
    return typed_hash({"protocol": PROTOCOL, "artifacts": validate_artifact_slots(artifacts)})


def parse_policy(data: bytes) -> dict[str, Any]:
    """Parse a policy's structure; a valid policy is not necessarily reviewed or approved."""
    policy = closed(
        parse_document(data), {"schema", "revision", "producers"}, "producer policy fields"
    )
    require(policy["schema"] == POLICY_SCHEMA, "producer policy schema")
    _integer(policy["revision"], 1, "policy revision")
    require(
        type(policy["producers"]) is list and bool(policy["producers"]), "producer rows required"
    )
    seen: set[tuple[str, str]] = set()
    for value in policy["producers"]:
        row = closed(
            value,
            {"protocol", "source_revision", "bridge_sha256", "painter_side_sha256"},
            "producer row fields",
        )
        require(row["protocol"] == PROTOCOL, "producer protocol")
        require(
            type(row["source_revision"]) is str
            and SOURCE_REVISION.fullmatch(row["source_revision"]) is not None,
            "source revision must be full lowercase commit",
        )
        _hash(row["bridge_sha256"], "bridge hash")
        _hash(row["painter_side_sha256"], "Painter-side hash")
        pair = (row["bridge_sha256"], row["painter_side_sha256"])
        require(pair not in seen, "duplicate producer pair")
        seen.add(pair)
    return policy


def parse_validation_report(data: bytes) -> dict[str, Any]:
    """Validate report structure; this does not establish that a validator ran."""
    report = closed(
        parse_document(data),
        {
            "schema",
            "protocol",
            "artifacts",
            "producer",
            "signature_sha256",
            "metadata_sha256",
            "capture_context_sha256",
            "scalar_raster_sha256",
            "validator",
        },
        "native report fields",
    )
    require(
        report["schema"] == REPORT_SCHEMA and report["protocol"] == PROTOCOL,
        "native report schema or protocol",
    )
    validate_artifact_slots(report["artifacts"])
    producer = closed(
        report["producer"], {"bridge_sha256", "painter_side_sha256"}, "report producer fields"
    )
    for field, value in producer.items():
        _hash(value, field)
    validator = closed(
        report["validator"], {"revision", "code_sha256", "binary_sha256"}, "report validator fields"
    )
    require(validator["revision"] == VALIDATOR_REVISION, "validator revision")
    _hash(validator["code_sha256"], "validator code hash")
    _hash(validator["binary_sha256"], "validator binary hash")
    for field in (
        "signature_sha256",
        "metadata_sha256",
        "capture_context_sha256",
        "scalar_raster_sha256",
    ):
        _hash(report[field], field)
    return report


def parse_admission_document(data: bytes) -> dict[str, Any]:
    """Check stored-document shape and capture ID, without granting admission or trust."""
    document = closed(
        parse_document(data),
        {
            "schema",
            "protocol",
            "capture_id",
            "producer_policy",
            "artifacts",
            "provenance",
            "validation",
            "admitted_at",
        },
        "admission document fields",
    )
    require(
        document["schema"] == ADMISSION_SCHEMA and document["protocol"] == PROTOCOL,
        "admission schema or protocol",
    )
    _hash(document["capture_id"], "capture ID")
    require(document["capture_id"] == capture_id(document["artifacts"]), "capture ID differs")
    policy = closed(document["producer_policy"], {"revision", "sha256"}, "admission policy fields")
    _integer(policy["revision"], 1, "policy revision")
    _hash(policy["sha256"], "policy hash")
    provenance = closed(
        document["provenance"], {"basis", "execution_attestation"}, "provenance fields"
    )
    require(
        provenance == {"basis": "owner_local_submission", "execution_attestation": "none"},
        "unsupported provenance claim",
    )
    validation = closed(
        document["validation"],
        {
            "validator_revision",
            "validator_code_sha256",
            "validator_binary_sha256",
            "signature_sha256",
            "capture_context_sha256",
            "scalar_raster_sha256",
        },
        "admission validation fields",
    )
    require(validation["validator_revision"] == VALIDATOR_REVISION, "validator revision")
    for field, value in validation.items():
        if field != "validator_revision":
            _hash(value, field)
    stamp = document["admitted_at"]
    require(
        type(stamp) is str and UTC_TIMESTAMP.fullmatch(stamp) is not None, "admission UTC timestamp"
    )
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        raise ValueError("invalid admission timestamp") from None
    require(parsed.utcoffset() == timedelta(0), "admission timestamp must be UTC")
    return document

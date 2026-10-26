"""Authored structural cases only; no private H, subprocess, native validation or store writes."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.parity.store import snapshot_contract as contract


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def artifacts() -> dict[str, Any]:
    def ref(record_id: str, kind: str, byte: str, size: int) -> dict[str, Any]:
        return {"record_id": record_id, "kind": kind, "sha256": byte * 64, "size_bytes": size}

    return {
        "receipt": ref("receipt", "snapshot_receipt", "1", 100),
        "request": ref("request", "snapshot_request", "2", 50),
        "environment": None,
        "environment_binding": None,
        "scalar_exports": [ref(f"r{i}-scalar", "snapshot_scalar_export", "3", 256) for i in (1, 2)],
        "rgb_exports": [ref(f"r{i}-rgb", "snapshot_rgb_export", "4", 768) for i in (1, 2)],
    }


def policy() -> dict[str, Any]:
    return {
        "schema": contract.POLICY_SCHEMA,
        "revision": 1,
        "producers": [
            {
                "protocol": contract.PROTOCOL,
                "source_revision": "a" * 40,
                "bridge_sha256": "b" * 64,
                "painter_side_sha256": "c" * 64,
            }
        ],
    }


def report() -> dict[str, Any]:
    return {
        "schema": contract.REPORT_SCHEMA,
        "protocol": contract.PROTOCOL,
        "artifacts": artifacts(),
        "producer": {"bridge_sha256": "b" * 64, "painter_side_sha256": "c" * 64},
        "signature_sha256": "5" * 64,
        "metadata_sha256": "6" * 64,
        "capture_context_sha256": "7" * 64,
        "scalar_raster_sha256": "8" * 64,
        "validator": {
            "revision": contract.VALIDATOR_REVISION,
            "code_sha256": "9" * 64,
            "binary_sha256": "a" * 64,
        },
    }


def admission() -> dict[str, Any]:
    slots = artifacts()
    return {
        "schema": contract.ADMISSION_SCHEMA,
        "protocol": contract.PROTOCOL,
        "capture_id": contract.capture_id(slots),
        "artifacts": slots,
        "producer_policy": {"revision": 1, "sha256": "b" * 64},
        "provenance": {"basis": "owner_local_submission", "execution_attestation": "none"},
        "validation": {
            "validator_revision": contract.VALIDATOR_REVISION,
            "validator_code_sha256": "9" * 64,
            "validator_binary_sha256": "a" * 64,
            "signature_sha256": "5" * 64,
            "capture_context_sha256": "7" * 64,
            "scalar_raster_sha256": "8" * 64,
        },
        "admitted_at": "2026-10-26T01:02:03.123456Z",
    }


@pytest.mark.parametrize(
    "factory,parser",
    [
        (policy, contract.parse_policy),
        (artifacts, contract.parse_artifact_slots),
        (report, contract.parse_validation_report),
        (admission, contract.parse_admission_document),
    ],
)
def test_authored_shapes_roundtrip_without_claiming_trust(
    factory: Callable[[], dict[str, Any]], parser: Callable[[bytes], dict[str, Any]]
) -> None:
    value = factory()
    assert parser(encoded(value)) == value


def test_reviewed_public_policy_has_four_explicit_producer_pairs() -> None:
    value = contract.parse_policy(Path("parity/snapshot-producer-policy-v1.json").read_bytes())
    assert value["revision"] == 1 and len(value["producers"]) == 4
    assert {p["source_revision"] for p in value["producers"]} == {
        "65095c000c9bd5bb3ac8f6b3aa1f0f53ddeef2e8"
    }


@pytest.mark.parametrize(
    "data",
    [
        b'{"x":1,"x":2}',
        b'{"nested":{"x":1,"x":2}}',
        b'{"x":9223372036854775808}',
        b'{"x":-9223372036854775809}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e309}',
        b'{"x":1e-999}',
        b'{"x":-1e-999}',
        b"[]",
        b'{"x":"\\ud800"}',
        '{"x":1}'.encode("utf-16"),
    ],
)
def test_shared_parser_refuses_lossy_or_ambiguous_json(data: bytes) -> None:
    with pytest.raises(ValueError):
        contract.parse_document(data)


def test_parser_and_hash_keep_numeric_types_and_signed_zero() -> None:
    values = contract.parse_document(
        b'{"integer":1,"double":1.0,"positive":0.0,"negative":-0.0,"minimum":-9223372036854775808,"maximum":9223372036854775807}'
    )
    assert type(values["integer"]) is int and type(values["double"]) is float
    assert math.copysign(1, values["negative"]) == -1
    assert contract.typed_hash({"v": 1}) != contract.typed_hash({"v": 1.0})
    assert contract.typed_hash({"v": 0.0}) != contract.typed_hash({"v": -0.0})


def test_capture_id_binds_roles_and_bytes_but_not_admission_time() -> None:
    slots = artifacts()
    expected = hashlib.sha256(
        encoded({"protocol": "paired-scalar-rgb", "artifacts": slots})
    ).hexdigest()
    assert contract.capture_id(slots) == expected
    assert len(contract.parse_artifact_slots(encoded(slots))["scalar_exports"]) == 2
    slots["request"]["sha256"] = "f" * 64
    assert contract.capture_id(slots) != expected
    doc = admission()
    doc["admitted_at"] = "2026-10-27T01:02:03+00:00"
    assert contract.parse_admission_document(encoded(doc))["capture_id"] == expected


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, -0.0, 1 << 63, "1"])
def test_policy_revision_is_positive_exact_int64(value: Any) -> None:
    doc = policy()
    doc["revision"] = value
    with pytest.raises(ValueError):
        contract.parse_policy(encoded(doc))


@pytest.mark.parametrize("value", ["a" * 39, "A" * 40, "g" * 40, "main", 1, None])
def test_source_revision_is_full_lowercase_commit(value: Any) -> None:
    doc = policy()
    doc["producers"][0]["source_revision"] = value
    with pytest.raises(ValueError):
        contract.parse_policy(encoded(doc))


def test_duplicate_policy_pairs_refuse_even_with_other_revision() -> None:
    doc = policy()
    doc["producers"].append(deepcopy(doc["producers"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        contract.parse_policy(encoded(doc))
    doc["producers"][1]["source_revision"] = "d" * 40
    with pytest.raises(ValueError, match="duplicate"):
        contract.parse_policy(encoded(doc))


@pytest.mark.parametrize(
    "mutation",
    [
        "swapped",
        "kind",
        "id",
        "missing_round",
        "extra_round",
        "environment",
        "binding",
        "same_hash_size",
    ],
)
def test_artifact_role_round_and_null_environment_contract(mutation: str) -> None:
    doc = artifacts()
    if mutation == "swapped":
        doc["scalar_exports"].reverse()
    elif mutation in {"kind", "id"}:
        field = "kind" if mutation == "kind" else "record_id"
        doc["scalar_exports"][0][field] = doc["rgb_exports"][0][field]
    elif mutation == "missing_round":
        doc["rgb_exports"].pop()
    elif mutation == "extra_round":
        doc["rgb_exports"].append(deepcopy(doc["rgb_exports"][0]))
    elif mutation in {"environment", "binding"}:
        doc["environment" if mutation == "environment" else "environment_binding"] = {}
    else:
        doc["scalar_exports"][1]["size_bytes"] += 1
    with pytest.raises(ValueError):
        contract.parse_artifact_slots(encoded(doc))


@pytest.mark.parametrize("value", [True, -1, 0.0, -0.0, 1 << 63, "100"])
def test_artifact_size_is_nonnegative_exact_int64(value: Any) -> None:
    doc = artifacts()
    doc["receipt"]["size_bytes"] = value
    with pytest.raises(ValueError):
        contract.parse_artifact_slots(encoded(doc))


@pytest.mark.parametrize(
    "factory,parser,path",
    [
        (policy, contract.parse_policy, ()),
        (policy, contract.parse_policy, ("producers", 0)),
        (artifacts, contract.parse_artifact_slots, ()),
        (artifacts, contract.parse_artifact_slots, ("receipt",)),
        (report, contract.parse_validation_report, ()),
        (report, contract.parse_validation_report, ("producer",)),
        (report, contract.parse_validation_report, ("validator",)),
        (admission, contract.parse_admission_document, ()),
        (admission, contract.parse_admission_document, ("producer_policy",)),
        (admission, contract.parse_admission_document, ("provenance",)),
        (admission, contract.parse_admission_document, ("validation",)),
    ],
)
@pytest.mark.parametrize("operation", ["extra", "missing"])
def test_every_contract_object_is_closed(
    factory: Callable[[], dict[str, Any]],
    parser: Callable[[bytes], dict[str, Any]],
    path: tuple[Any, ...],
    operation: str,
) -> None:
    doc = factory()
    target: Any = doc
    for part in path:
        target = target[part]
    if operation == "extra":
        target["unknown"] = True
    else:
        target.pop(next(iter(target)))
    with pytest.raises(ValueError):
        parser(encoded(doc))


@pytest.mark.parametrize(
    "mutation",
    [
        "capture_id",
        "artifact",
        "attestation",
        "basis",
        "validator",
        "date",
        "offset",
        "naive",
        "hash",
    ],
)
def test_admission_shape_never_accepts_unlinked_or_invented_claims(mutation: str) -> None:
    doc = admission()
    if mutation == "capture_id":
        doc["capture_id"] = "0" * 64
    elif mutation == "artifact":
        doc["artifacts"]["request"]["sha256"] = "f" * 64
    elif mutation == "attestation":
        doc["provenance"]["execution_attestation"] = "authenticated"
    elif mutation == "basis":
        doc["provenance"]["basis"] = "synthetic_bypass"
    elif mutation == "validator":
        doc["validation"]["validator_revision"] = "a" * 40
    elif mutation in {"date", "offset", "naive"}:
        doc["admitted_at"] = {
            "date": "2026-02-30T01:02:03Z",
            "offset": "2026-10-26T01:02:03-03:00",
            "naive": "2026-10-26T01:02:03",
        }[mutation]
    else:
        doc["validation"]["validator_binary_sha256"] = "A" * 64
    with pytest.raises(ValueError):
        contract.parse_admission_document(encoded(doc))


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", "snapshot-capture-validator-v1"),
        ("revision", "a" * 40),
        ("code_sha256", "a" * 63),
        ("binary_sha256", True),
    ],
)
def test_native_report_pins_are_closed_structural_claims(field: str, value: Any) -> None:
    doc = report()
    doc["validator"][field] = value
    with pytest.raises(ValueError):
        contract.parse_validation_report(encoded(doc))

"""Authored files and mocked processes only; no native build, capture or admission."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.parity.test_snapshot_host_transport import PINS, record
from tools.parity.snapshot_host_transport import RecorderProvenance, host_transport
from tools.parity.store import snapshot_validator as validator
from tools.parity.store.snapshot_contract import (
    POLICY_SCHEMA,
    PROTOCOL,
    REPORT_SCHEMA,
    VALIDATOR_REVISION,
    typed_hash,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    work = record(tmp_path / "unicod\u00e9")
    binary = tmp_path / "approved.exe"
    binary.write_bytes(b"authored executable stand-in; never executed")
    revision = "1" * 40
    policy = {
        "schema": POLICY_SCHEMA,
        "revision": 1,
        "producers": [{"protocol": PROTOCOL, "source_revision": revision, **PINS}],
    }
    policy_bytes = json.dumps(policy).encode()
    options: dict[str, Any] = {
        "binary": binary,
        "approved_binary_sha256": digest(binary.read_bytes()),
        "approved_code_sha256": "2" * 64,
        "policy_bytes": policy_bytes,
        "approved_policy_sha256": digest(policy_bytes),
        "approved_policy_revision": 1,
        "repo": tmp_path,
    }
    transport = host_transport(work)
    artifacts = {key: value for key, value in transport.section.items() if key != "protocol"}
    refs = [
        artifacts["receipt"],
        artifacts["request"],
        *artifacts["scalar_exports"],
        *artifacts["rgb_exports"],
    ]
    for ref, record_id in zip(
        refs, ("receipt", "request", "r1-scalar", "r2-scalar", "r1-rgb", "r2-rgb"), strict=True
    ):
        ref["record_id"] = record_id
    receipt = json.loads((work / "capture.json").read_bytes())
    report = {
        "schema": REPORT_SCHEMA,
        "protocol": PROTOCOL,
        "artifacts": artifacts,
        "producer": dict(PINS),
        "signature_sha256": typed_hash(receipt["signature"]),
        "metadata_sha256": "3" * 64,
        "capture_context_sha256": typed_hash(receipt["readback"]),
        "scalar_raster_sha256": "4" * 64,
        "validator": {
            "revision": VALIDATOR_REVISION,
            "code_sha256": options["approved_code_sha256"],
            "binary_sha256": options["approved_binary_sha256"],
        },
    }
    result: dict[str, Any] = {
        "work": work,
        "options": options,
        "report": report,
        "calls": [],
        "provenance": [],
    }

    def provenance(pins: Any, approved: str, repo: Path) -> RecorderProvenance:
        result["provenance"].append((pins, approved, repo))
        return RecorderProvenance(approved, {"bridge_sha256": "lf", "painter_side_sha256": "lf"})

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        result["calls"].append((args, kwargs))
        if result.get("timeout"):
            raise subprocess.TimeoutExpired(args, 120)
        if "change" in result:
            result["change"].write_bytes(b"changed during invocation")
        stdout = result.get("stdout", json.dumps(result["report"]).encode())
        return subprocess.CompletedProcess(
            args, result.get("returncode", 0), stdout, b"private detail"
        )

    monkeypatch.setattr(validator, "recorder_pin_provenance", provenance)
    monkeypatch.setattr(subprocess, "run", run)
    return result


def invoke(case: dict[str, Any]) -> validator.SnapshotValidation:
    return validator.validate_snapshot_capture(case["work"], **case["options"])


def test_invocation_joins_explicit_pins_and_preserves_six_unicode_paths(
    case: dict[str, Any],
) -> None:
    result = invoke(case)
    assert result.report == case["report"]
    assert result.producer_policy_sha256 == case["options"]["approved_policy_sha256"]
    assert case["provenance"] == [(PINS, "1" * 40, case["options"]["repo"])]
    [(args, kwargs)] = case["calls"]
    assert args == [str(case["options"]["binary"]), "snapshot-capture-validate", "--input-stdin"]
    assert {key: value for key, value in kwargs.items() if key != "input"} == {
        "capture_output": True,
        "timeout": 120,
        "check": False,
    }
    request = json.loads(kwargs["input"])
    assert request == {
        "schema": validator.INPUT_SCHEMA,
        "protocol": PROTOCOL,
        "receipt": {"path": str(case["work"] / "capture.json")},
        "request": {"path": str(case["work"] / "request.json")},
        "scalar_exports": [
            {"path": str(case["work"] / f"export{i}" / "user0.exr")} for i in (1, 2)
        ],
        "rgb_exports": [{"path": str(case["work"] / f"export{i}" / "user1.exr")} for i in (1, 2)],
    }
    assert "unicod\u00e9".encode() in kwargs["input"]
    assert "report" not in repr(result)


@pytest.mark.parametrize(
    "pin", ["approved_binary_sha256", "approved_policy_sha256", "approved_policy_revision"]
)
def test_wrong_trusted_pin_prevents_execution(case: dict[str, Any], pin: str) -> None:
    case["options"][pin] = 9 if pin == "approved_policy_revision" else "9" * 64
    with pytest.raises(validator.ValidationRefused):
        invoke(case)
    assert case["calls"] == []


@pytest.mark.parametrize("revision", [True, 1.0, 0, 1 << 63])
def test_policy_revision_requires_positive_exact_int(case: dict[str, Any], revision: Any) -> None:
    case["options"]["approved_policy_revision"] = revision
    with pytest.raises(validator.ValidationRefused, match="invalid approved policy revision"):
        invoke(case)
    assert case["calls"] == []


def test_relative_binary_prevents_execution(case: dict[str, Any]) -> None:
    case["options"]["binary"] = Path("approved.exe")
    with pytest.raises(validator.ValidationRefused, match="absolute"):
        invoke(case)
    assert case["calls"] == []


@pytest.mark.parametrize("field", ["code_sha256", "binary_sha256"])
def test_native_identity_must_match_approved_pin(case: dict[str, Any], field: str) -> None:
    case["report"]["validator"][field] = "9" * 64
    with pytest.raises(validator.ValidationRefused):
        invoke(case)


@pytest.mark.parametrize("field", ["capture_context_sha256", "producer", "artifacts"])
def test_native_report_must_join_inputs(case: dict[str, Any], field: str) -> None:
    if field == "producer":
        case["report"][field]["bridge_sha256"] = "9" * 64
    elif field == "artifacts":
        case["report"][field]["receipt"]["sha256"] = "9" * 64
    else:
        case["report"][field] = "9" * 64
    with pytest.raises(validator.ValidationRefused):
        invoke(case)


@pytest.mark.parametrize("bad", [b'{"schema":', b"{} trailing", b"\xff", b"{}\n{}"])
def test_truncated_or_non_json_stdout_refused(case: dict[str, Any], bad: bytes) -> None:
    case["stdout"] = bad
    with pytest.raises(validator.ValidationRefused):
        invoke(case)


def test_duplicate_stdout_fields_refused(case: dict[str, Any]) -> None:
    case["stdout"] = (
        json.dumps(case["report"])
        .encode()
        .replace(
            b'"protocol": "paired-scalar-rgb"',
            b'"protocol": "paired-scalar-rgb", "protocol": "paired-scalar-rgb"',
        )
    )
    with pytest.raises(validator.ValidationRefused):
        invoke(case)


@pytest.mark.parametrize(
    "target",
    [
        "binary",
        "capture.json",
        "request.json",
        "export1/user0.exr",
        "export2/user0.exr",
        "export1/user1.exr",
        "export2/user1.exr",
        "context.json",
        "mesh.obj",
    ],
)
def test_changes_during_process_refused(case: dict[str, Any], target: str) -> None:
    case["change"] = case["options"]["binary"] if target == "binary" else case["work"] / target
    with pytest.raises(validator.ValidationRefused, match="changed during"):
        invoke(case)


@pytest.mark.parametrize("returncode", [2, 1, -1])
def test_success_shaped_stdout_cannot_override_failed_process(
    case: dict[str, Any], returncode: int
) -> None:
    case["returncode"] = returncode
    with pytest.raises(validator.ValidationRefused, match="refused or failed"):
        invoke(case)


def test_timeout_refused(case: dict[str, Any]) -> None:
    case["timeout"] = True
    with pytest.raises(validator.ValidationRefused, match="timed out"):
        invoke(case)


def test_input_size_checked_before_process(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validator, "INPUT_LIMIT", 1)
    with pytest.raises(validator.ValidationRefused, match="64 KiB"):
        invoke(case)
    assert case["calls"] == []


def test_git_provenance_refusal_prevents_process(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any) -> Any:
        raise ValueError("unapproved Git source")

    monkeypatch.setattr(validator, "recorder_pin_provenance", refuse)
    with pytest.raises(validator.ValidationRefused):
        invoke(case)
    assert case["calls"] == []


def test_pinned_policy_still_needs_matching_producer(case: dict[str, Any]) -> None:
    policy = json.loads(case["options"]["policy_bytes"])
    policy["producers"][0]["bridge_sha256"] = "9" * 64
    data = json.dumps(policy).encode()
    case["options"]["policy_bytes"] = data
    case["options"]["approved_policy_sha256"] = digest(data)
    with pytest.raises(validator.ValidationRefused, match="producer absent"):
        invoke(case)
    assert case["calls"] == []


def test_existing_success_is_never_reused(case: dict[str, Any]) -> None:
    previous = deepcopy(invoke(case).report)
    case["returncode"] = 2
    with pytest.raises(validator.ValidationRefused):
        invoke(case)
    assert previous == case["report"]
    assert len(case["calls"]) == 2


@pytest.mark.parametrize("amount,normalized", [(1.0, 1), (-0.0, 0)])
def test_native_snapshot_key_is_not_raw_typed_signature(
    case: dict[str, Any], amount: float, normalized: int
) -> None:
    work = case["work"]
    receipt = json.loads((work / "capture.json").read_bytes())
    request = json.loads((work / "request.json").read_bytes())
    context = json.loads((work / "context.json").read_bytes())
    request["parameters"]["amount"] = amount
    for source in receipt["readback"]["sources"]:
        source["parameters"]["amount"] = amount
    receipt["signature"]["params"]["amount"] = amount
    receipt["signature"]["settings"]["resolution"] = 128.0
    context["settings"]["resolution"] = 128.0
    for name, document in (
        ("capture.json", receipt),
        ("request.json", request),
        ("context.json", context),
    ):
        (work / name).write_bytes(json.dumps(document).encode())
    for slot, name in (("receipt", "capture.json"), ("request", "request.json")):
        data = (work / name).read_bytes()
        case["report"]["artifacts"][slot].update(sha256=digest(data), size_bytes=len(data))
    # Explicit expected values for these two authored vectors, not a Python ParamJson codec.
    normalized_signature = deepcopy(receipt["signature"])
    normalized_signature["params"]["amount"] = normalized
    normalized_signature["settings"]["resolution"] = 128
    snapshot_key = digest(
        json.dumps(normalized_signature, sort_keys=True, separators=(",", ":")).encode()
    )
    assert snapshot_key != typed_hash(receipt["signature"])
    case["report"]["signature_sha256"] = snapshot_key
    case["report"]["capture_context_sha256"] = typed_hash(receipt["readback"])
    assert invoke(case).report["signature_sha256"] == snapshot_key


@pytest.mark.parametrize("target", ["context.json", "mesh.obj"])
def test_transport_read_aba_refused_before_process(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    original = Path.read_bytes
    path = case["work"] / target
    baseline = original(path)

    def transient_read(self: Path) -> bytes:
        data = original(self)
        # Simulate reading B while disk fingerprints before/after still observe A.
        return data + b" " if self == path else data

    monkeypatch.setattr(Path, "read_bytes", transient_read)
    with pytest.raises(validator.ValidationRefused, match="input bytes changed during transport"):
        invoke(case)
    assert original(path) == baseline
    assert case["calls"] == []


def test_second_receipt_read_aba_refused_before_parse(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_bytes
    path = case["work"] / "capture.json"
    baseline = original(path)
    reads = 0

    def transient_read(self: Path) -> bytes:
        nonlocal reads
        data = original(self)
        if self == path:
            reads += 1
            if reads == 2:
                return data + b" "
        return data

    monkeypatch.setattr(Path, "read_bytes", transient_read)
    with pytest.raises(validator.ValidationRefused, match="receipt bytes changed during read"):
        invoke(case)
    assert reads == 2 and original(path) == baseline
    assert case["calls"] == []

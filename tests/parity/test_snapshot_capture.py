"""Authored admission/storage cases with mocked trusted invocation; no real native run."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.parity.test_snapshot_host_transport import PINS, record
from tools.parity.snapshot_host_transport import host_transport
from tools.parity.store import cli, manifest
from tools.parity.store import snapshot_capture as capture
from tools.parity.store.snapshot_contract import (
    POLICY_SCHEMA,
    REPORT_SCHEMA,
    VALIDATOR_REVISION,
    capture_id,
)
from tools.parity.store.snapshot_validator import SnapshotValidation
from tools.parity.store.store import (
    OracleStore,
    Status,
    StoreError,
    publish_no_replace,
    sha256_file,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    work = record(tmp_path / "authored")
    store = OracleStore.init(tmp_path / "store")
    policy_bytes = json.dumps(
        {
            "schema": POLICY_SCHEMA,
            "revision": 1,
            "producers": [{"protocol": "paired-scalar-rgb", "source_revision": "1" * 40, **PINS}],
        }
    ).encode()
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
    report = {
        "schema": REPORT_SCHEMA,
        "protocol": "paired-scalar-rgb",
        "artifacts": artifacts,
        "producer": PINS,
        "signature_sha256": "2" * 64,
        "metadata_sha256": "3" * 64,
        "capture_context_sha256": "4" * 64,
        "scalar_raster_sha256": "5" * 64,
        "validator": {
            "revision": VALIDATOR_REVISION,
            "code_sha256": "6" * 64,
            "binary_sha256": "7" * 64,
        },
    }
    options = {
        "binary": tmp_path / "never-run.exe",
        "approved_binary_sha256": "7" * 64,
        "approved_code_sha256": "6" * 64,
        "policy_bytes": policy_bytes,
        "approved_policy_sha256": digest(policy_bytes),
        "approved_policy_revision": 1,
    }
    state: dict[str, Any] = {
        "store": store,
        "work": work,
        "options": options,
        "report": report,
        "calls": [],
    }

    def validate(work: Path, **kwargs: Any) -> SnapshotValidation:
        state["calls"].append((work, kwargs))
        if state.get("refuse"):
            raise ValueError("authored native refusal")
        answer = deepcopy(state["report"])
        answer["validator"]["code_sha256"] = kwargs["approved_code_sha256"]
        if state.get("conflict") and kwargs["approved_code_sha256"] == "9" * 64:
            answer["signature_sha256"] = "a" * 64
        if barrier := state.get("barrier"):
            barrier.wait(timeout=10)
        return SnapshotValidation(answer, digest(policy_bytes), 1, "1" * 40)

    monkeypatch.setattr(capture, "validate_snapshot_capture", validate)
    return state


def admit(case: dict[str, Any]) -> dict[str, Any]:
    return capture.admit_snapshot_capture(case["store"], case["work"], **case["options"])


def resolve(case: dict[str, Any], identifier: str | None = None) -> capture.CaptureResolution:
    return capture.resolve_snapshot_capture(
        case["store"],
        identifier or capture_id(case["report"]["artifacts"]),
        approved_policy_sha256=case["options"]["approved_policy_sha256"],
        approved_policy_revision=1,
    )


def overwrite(path: Path, data: bytes) -> None:
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    path.write_bytes(data)


def test_admit_resolve_and_idempotent_revalidation_retains_original_identity(
    case: dict[str, Any],
) -> None:
    first = admit(case)
    assert resolve(case).document == first
    assert case["store"].check() == []
    case["options"]["approved_code_sha256"] = "9" * 64
    second = admit(case)
    assert second == first
    assert second["validation"]["validator_code_sha256"] == "6" * 64
    assert len(case["calls"]) == 2
    assert case["options"]["approved_policy_sha256"] not in case["store"].index()
    ref = first["artifacts"]["scalar_exports"][0]
    assert (
        capture.resolve_snapshot_artifact(
            case["store"],
            first["capture_id"],
            ref,
            approved_policy_sha256=case["options"]["approved_policy_sha256"],
            approved_policy_revision=1,
        ).status
        is Status.AVAILABLE
    )


def test_bare_correct_blobs_never_admit(case: dict[str, Any]) -> None:
    for path in case["work"].rglob("*.exr"):
        case["store"].put_blob(path, sha256_file(path)[0])
    assert resolve(case).status is Status.ORACLE_UNAVAILABLE


@pytest.mark.parametrize(
    "field,value",
    [
        ("record_id", "r3-scalar"),
        ("kind", "snapshot_rgb_export"),
        ("sha256", "9" * 64),
        ("size_bytes", 1),
        ("size_bytes", True),
    ],
)
def test_artifact_requires_exact_member(case: dict[str, Any], field: str, value: Any) -> None:
    document = admit(case)
    ref = dict(document["artifacts"]["scalar_exports"][0])
    ref[field] = value
    result = capture.resolve_snapshot_artifact(
        case["store"],
        document["capture_id"],
        ref,
        approved_policy_sha256=case["options"]["approved_policy_sha256"],
        approved_policy_revision=1,
    )
    assert result.status is Status.ORACLE_UNAVAILABLE


@pytest.mark.parametrize("mutation", ["capture", "policy", "kind", "size", "round", "signature"])
def test_corrupt_or_conflicting_winner_refuses_retry(case: dict[str, Any], mutation: str) -> None:
    original = admit(case)
    document = deepcopy(original)
    path = capture.admission_path(
        case["store"], original["capture_id"], case["options"]["approved_policy_sha256"]
    )
    if mutation == "capture":
        document["capture_id"] = "9" * 64
    elif mutation == "policy":
        document["producer_policy"]["sha256"] = "9" * 64
    elif mutation == "signature":
        document["validation"]["signature_sha256"] = "9" * 64
    else:
        ref = document["artifacts"]["scalar_exports"][0]
        ref[{"kind": "kind", "size": "size_bytes", "round": "record_id"}[mutation]] = {
            "kind": "snapshot_rgb_export",
            "size": 1,
            "round": "r2-scalar",
        }[mutation]
    corrupt = json.dumps(document).encode()
    overwrite(path, corrupt)
    with pytest.raises(StoreError):
        admit(case)
    assert path.read_bytes() == corrupt
    if mutation != "signature":
        assert resolve(case).status is Status.ORACLE_UNAVAILABLE
        assert case["store"].check()


@pytest.mark.parametrize("target", ["blob", "policy"])
def test_corrupt_dependency_makes_whole_capture_unavailable(
    case: dict[str, Any], target: str
) -> None:
    document = admit(case)
    if target == "blob":
        path = case["store"].blob_path(document["artifacts"]["request"]["sha256"])
    else:
        path = (
            case["store"].root
            / "snapshot-producer-policies"
            / f"{case['options']['approved_policy_sha256']}.json"
        )
    overwrite(path, b"corrupt")
    assert resolve(case).status is Status.ORACLE_UNAVAILABLE
    with pytest.raises(StoreError):
        admit(case)
    assert case["store"].check()


def test_wrong_policy_pin_or_revision_unavailable(case: dict[str, Any]) -> None:
    document = admit(case)
    for sha, revision in (
        ("9" * 64, 1),
        (case["options"]["approved_policy_sha256"], 2),
        (case["options"]["approved_policy_sha256"], True),
    ):
        assert (
            capture.resolve_snapshot_capture(
                case["store"],
                document["capture_id"],
                approved_policy_sha256=sha,
                approved_policy_revision=revision,
            ).status
            is Status.ORACLE_UNAVAILABLE
        )


def test_fresh_native_refusal_has_no_store_writes(case: dict[str, Any]) -> None:
    case["refuse"] = True
    before = set(case["store"].root.rglob("*"))
    with pytest.raises(StoreError):
        admit(case)
    assert set(case["store"].root.rglob("*")) == before


def test_changed_source_before_copy_refuses_before_store_writes(case: dict[str, Any]) -> None:
    (case["work"] / "request.json").write_bytes(b"changed")
    before = set(case["store"].root.rglob("*"))
    with pytest.raises(StoreError, match="source changed"):
        admit(case)
    assert set(case["store"].root.rglob("*")) == before


def test_source_changes_during_copy_preserve_partial_without_admission(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = OracleStore.put_blob

    def changed(store: OracleStore, source: Path, sha: str) -> int:
        source.write_bytes(b"changed after preflight")
        return original(store, source, sha)

    monkeypatch.setattr(OracleStore, "put_blob", changed)
    with pytest.raises(StoreError, match="changed while"):
        admit(case)
    assert list(case["store"].root.glob(".staging-*.partial"))
    assert resolve(case).status is Status.ORACLE_UNAVAILABLE


def test_interrupted_last_publication_preserves_staging_and_orphans(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = publish_no_replace

    def interrupt(staging: Path, target: Path) -> bool:
        if target.parent.parent.name == "snapshot-captures":
            raise OSError("authored interrupted publication")
        return original(staging, target)

    monkeypatch.setattr(capture, "publish_no_replace", interrupt)
    with pytest.raises(StoreError):
        admit(case)
    assert case["store"].index()
    assert list(case["store"].root.glob(".staging-*.partial"))
    assert resolve(case).status is Status.ORACLE_UNAVAILABLE
    assert case["store"].check() == []


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_admission_is_no_overwrite(case: dict[str, Any], conflicting: bool) -> None:
    case["barrier"] = threading.Barrier(2)
    case["conflict"] = conflicting

    def submit(code: str) -> dict[str, Any] | None:
        options = {**case["options"], "approved_code_sha256": code}
        try:
            return capture.admit_snapshot_capture(case["store"], case["work"], **options)
        except StoreError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["6" * 64, "9" * 64]))
    winners = [result for result in results if result is not None]
    assert len(winners) == (1 if conflicting else 2)
    if not conflicting:
        assert winners[0] == winners[1]
    assert resolve(case).document == winners[0]
    assert case["store"].check() == []


def test_all_index_updates_are_serialized_across_processes(tmp_path: Path) -> None:
    store = OracleStore.init(tmp_path / "store")
    inputs = []
    for index in range(12):
        path = tmp_path / f"source-{index}"
        path.write_bytes(f"authored concurrent blob {index}".encode())
        inputs.append((str(store.root), str(path), sha256_file(path)[0]))
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                store.put_blob, [Path(item[1]) for item in inputs], [item[2] for item in inputs]
            )
        )
    assert store.index() == {item[2] for item in inputs}
    assert store.check() == []
    assert (store.root / ".index.lock").exists()


def test_generic_snapshot_kinds_refused_before_reads_or_writes(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = case["store"]
    missing = case["work"] / "absent"
    before = set(store.root.rglob("*"))
    with pytest.raises(StoreError, match="dedicated"):
        manifest.record_file(store, missing, "receipt", "snapshot_receipt", missing)
    with pytest.raises(StoreError, match="dedicated"):
        store.add_record(
            "build", "golden", "receipt", "snapshot_future", missing, "1" * 64, "capture.json"
        )
    with pytest.raises(StoreError, match="dedicated"):
        manifest._merge(
            store,
            {"private_records": []},
            [manifest._Pending({"kind": "snapshot_request"}, missing, "")],
        )
    monkeypatch.setattr(
        manifest,
        "load_manifest",
        lambda _: {"private_records": [{"kind": "snapshot_scalar_export"}]},
    )
    ready = case["work"] / "READY"
    ready.write_bytes(b"")
    with pytest.raises(StoreError, match="dedicated"):
        manifest.record_run(store, missing, case["work"])
    assert set(store.root.rglob("*")) == before
    assert not any(kind.startswith("snapshot_") for kind in cli.RECORD_KINDS)


def test_cli_requires_explicit_pins_and_calls_trusted_path(
    case: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_bytes(case["options"]["policy_bytes"])
    options = case["options"]
    args = [
        "--store",
        str(case["store"].root),
        "admit-snapshot-capture",
        str(case["work"]),
        "--producer-policy",
        str(policy),
        "--approved-policy-sha256",
        options["approved_policy_sha256"],
        "--approved-policy-revision",
        "1",
        "--validator-binary",
        str(options["binary"]),
        "--approved-binary-sha256",
        options["approved_binary_sha256"],
        "--approved-code-sha256",
        options["approved_code_sha256"],
    ]
    assert cli.main(args) == 0
    assert "admitted" in capsys.readouterr().out
    assert len(case["calls"]) == 1
    with pytest.raises(SystemExit) as error:
        cli.main(args[:-2])
    assert error.value.code == 2


def test_publication_never_deletes_files(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbid(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("deletion forbidden")

    monkeypatch.setattr(Path, "unlink", forbid)
    monkeypatch.setattr(os, "remove", forbid)
    monkeypatch.setattr(os, "unlink", forbid)
    assert admit(case) == admit(case)

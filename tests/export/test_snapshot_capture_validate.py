"""Test-only native H diagnostic `snapshot-capture-validate --input-stdin` through its real CLI
(stdin and stdout) on an authored recording whose recorder pins are an approved pair of the
pinned producer policy (public Git sources); no Painter, no private capture. Its report satisfies
the frozen Python contract, and the wrapper and store admit the recording into an external pytest
store."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.export.conftest import export_tests as export_tests
from tools.parity.store.snapshot_capture import resolve_snapshot_capture
from tools.parity.store.snapshot_contract import (
    VALIDATOR_REVISION,
    capture_id,
    parse_document,
    parse_validation_report,
    typed_hash,
)
from tools.parity.store.store import OracleStore, Status

REPO = Path(__file__).resolve().parents[2]
PREFIX = "SNAPSHOT_CAPTURE_FIXTURE: "
SOURCES_DOMAIN = b"uzpainter/snapshot-capture-validator-sources/1\0"
SOURCES = (
    "tests/export/snapshot_capture_validate.h",
    "tests/export/snapshot_capture_validate.cpp",
    "src/procedural/filter_observation_import_v2.h",
    "src/procedural/filter_observation_import_v2.cpp",
    "src/procedural/snapshot_recording.h",
    "src/procedural/snapshot_recording.cpp",
    "src/store/snapshots.h",
    "src/store/snapshots.cpp",
)
POLICY = REPO / "parity/snapshot-producer-policy-v1.json"
POLICY_SHA256 = "17ea078d57d88eeb1759a8010d3b304afc3a8a7192d4baf9ac71847e68cdf4ce"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def policy_pins() -> dict[str, str]:
    """An approved recorder pair of the full pinned producer policy (revision 1)."""
    data = POLICY.read_bytes()
    assert sha(data) == POLICY_SHA256
    policy = json.loads(data)
    assert policy["revision"] == 1
    row = policy["producers"][0]
    return {key: row[key] for key in ("bridge_sha256", "painter_side_sha256")}


def fixture(binary: Path, work: Path, amount: str = "0.5") -> tuple[dict[str, Any], str]:
    """The authored recording `work/h-capture`: its stdin input and the store's snapshot key."""
    pins = policy_pins()
    proc = subprocess.run(
        [
            str(binary),
            "snapshot-capture-fixture",
            str(work),
            amount,
            pins["bridge_sha256"],
            pins["painter_side_sha256"],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.startswith(PREFIX)]
    assert len(lines) == 1, proc.stdout
    key = json.loads(lines[0][len(PREFIX) :])["signature_sha256"]
    return json.loads((work / "input.json").read_bytes()), key


def validate(binary: Path, data: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(binary), "snapshot-capture-validate", "--input-stdin"],
        input=data,
        capture_output=True,
        timeout=120,
        check=False,
    )


def encode(request: dict[str, Any]) -> bytes:
    return json.dumps(request, ensure_ascii=False).encode("utf-8")


def slot(path: str, record_id: str, kind: str) -> dict[str, Any]:
    data = Path(path).read_bytes()
    return {"record_id": record_id, "kind": kind, "sha256": sha(data), "size_bytes": len(data)}


def expected_slots(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt": slot(request["receipt"]["path"], "receipt", "snapshot_receipt"),
        "request": slot(request["request"]["path"], "request", "snapshot_request"),
        "environment": None,
        "environment_binding": None,
        "scalar_exports": [
            slot(item["path"], f"r{i}-scalar", "snapshot_scalar_export")
            for i, item in enumerate(request["scalar_exports"], 1)
        ],
        "rgb_exports": [
            slot(item["path"], f"r{i}-rgb", "snapshot_rgb_export")
            for i, item in enumerate(request["rgb_exports"], 1)
        ],
    }


def framed_sources() -> str:
    """The validator code hash, reconstructed independently from the committed framing."""
    framed = bytearray(SOURCES_DOMAIN)
    for name in SOURCES:
        data = (REPO / name).read_bytes()
        framed += len(name.encode()).to_bytes(8, "little") + name.encode()
        framed += len(data).to_bytes(8, "little") + data
    return sha(bytes(framed))


def report_of(binary: Path, request: dict[str, Any]) -> dict[str, Any]:
    proc = validate(binary, encode(request))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stderr == b"" and proc.stdout.count(b"\n") == 1 and proc.stdout.endswith(b"\n")
    return parse_validation_report(proc.stdout)


def test_the_report_names_the_validated_capture(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    request, key = fixture(export_tests, tmp_path)
    report = report_of(export_tests, request)
    receipt = parse_document(Path(request["receipt"]["path"]).read_bytes())
    assert report["artifacts"] == expected_slots(request)
    assert report["producer"] == policy_pins() == receipt["recorder"]
    assert report["signature_sha256"] == key
    assert report["capture_context_sha256"] == typed_hash(receipt["readback"])
    assert report["validator"] == {
        "revision": VALIDATOR_REVISION,
        "code_sha256": framed_sources(),
        "binary_sha256": sha(export_tests.read_bytes()),
    }
    # Repeated rounds hold equal bytes and still keep their own slots.
    scalar = report["artifacts"]["scalar_exports"]
    assert scalar[0]["sha256"] == scalar[1]["sha256"]
    assert [ref["record_id"] for ref in scalar] == ["r1-scalar", "r2-scalar"]


@pytest.mark.parametrize("amount", ["1.0", "-0.0"])
def test_the_signature_key_is_the_native_snapshot_key(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    amount: str,
) -> None:
    request, key = fixture(export_tests, tmp_path, amount)
    report = report_of(export_tests, request)
    receipt = parse_document(Path(request["receipt"]["path"]).read_bytes())
    # The receipt keeps the raw double; the key is the native normalization (numbers by value).
    raw = receipt["signature"]["params"]["amount"]
    assert type(raw) is float and str(raw) == amount
    assert report["signature_sha256"] == key != typed_hash(receipt["signature"])


def test_unicode_paths(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    request, key = fixture(export_tests, tmp_path / "authored")
    moved = tmp_path / "ünïcødé 日本"
    renamed: dict[str, Any] = {"schema": request["schema"], "protocol": request["protocol"]}
    for field in ("receipt", "request"):
        target = moved / Path(request[field]["path"]).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(request[field]["path"], target)
        renamed[field] = {"path": str(target)}
    for field in ("scalar_exports", "rgb_exports"):
        renamed[field] = []
        for item in request[field]:
            source = Path(item["path"])
            target = moved / f"{source.parent.name} ü" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            renamed[field].append({"path": str(target)})
    report = report_of(export_tests, renamed)
    assert report["artifacts"] == expected_slots(request) == expected_slots(renamed)
    assert report["signature_sha256"] == key


Change = Callable[[Path, dict[str, Any]], bytes]


def _rewrite_receipt(request: dict[str, Any], change: Callable[[dict[str, Any]], None]) -> None:
    path = Path(request["receipt"]["path"])
    receipt = json.loads(path.read_bytes())
    change(receipt)
    path.write_bytes(json.dumps(receipt).encode())


def _relink(request: dict[str, Any], field: str, index: int, data: bytes) -> None:
    Path(request[field][index]["path"]).write_bytes(data)
    name = f"export{index + 1}/{'user0' if field == 'scalar_exports' else 'user1'}.exr"
    _rewrite_receipt(request, lambda receipt: receipt["files"].__setitem__(name, sha(data)))


def _oversize(work: Path, request: dict[str, Any]) -> bytes:
    return encode(request) + b" " * 65536


def _not_json(work: Path, request: dict[str, Any]) -> bytes:
    return b"{"


def _not_utf8(work: Path, request: dict[str, Any]) -> bytes:
    return encode(request).replace(b'"protocol"', b'"protocol\xff"')


def _duplicate_key(work: Path, request: dict[str, Any]) -> bytes:
    return b'{"schema": "x", ' + encode(request)[1:]


def _extra_member(work: Path, request: dict[str, Any]) -> bytes:
    return encode({**request, "extra": 1})


def _caller_hash(work: Path, request: dict[str, Any]) -> bytes:
    receipt = {**request["receipt"], "sha256": "0" * 64}
    return encode({**request, "receipt": receipt})


def _other_schema(work: Path, request: dict[str, Any]) -> bytes:
    return encode({**request, "schema": "uzpainter/parity/other/1"})


def _relative_path(work: Path, request: dict[str, Any]) -> bytes:
    return encode({**request, "request": {"path": "request.json"}})


def _nul_path(work: Path, request: dict[str, Any]) -> bytes:
    return encode({**request, "request": {"path": request["request"]["path"] + "\0.json"}})


def _one_round(work: Path, request: dict[str, Any]) -> bytes:
    return encode({**request, "rgb_exports": request["rgb_exports"][:1]})


def _missing_slot(work: Path, request: dict[str, Any]) -> bytes:
    return encode({key: value for key, value in request.items() if key != "request"})


def _missing_file(work: Path, request: dict[str, Any]) -> bytes:
    return encode({**request, "request": {"path": str(work / "absent.json")}})


def _directory(work: Path, request: dict[str, Any]) -> bytes:
    directory = Path(request["scalar_exports"][0]["path"]).parent
    return encode({**request, "request": {"path": str(directory)}})


def _swapped_slots(work: Path, request: dict[str, Any]) -> bytes:
    return encode({**request, "receipt": request["request"], "request": request["receipt"]})


def _swapped_roles(work: Path, request: dict[str, Any]) -> bytes:
    swapped = {**request, "scalar_exports": request["rgb_exports"]}
    return encode({**swapped, "rgb_exports": request["scalar_exports"]})


def _changed_export(work: Path, request: dict[str, Any]) -> bytes:
    Path(request["scalar_exports"][1]["path"]).write_bytes(b"not the exported raster")
    return encode(request)


def _invalid_exr(work: Path, request: dict[str, Any]) -> bytes:
    _relink(request, "scalar_exports", 1, b"not an EXR")
    return encode(request)


def _round_difference(work: Path, request: dict[str, Any]) -> bytes:
    _relink(request, "scalar_exports", 1, (work / "other-scalar.exr").read_bytes())
    return encode(request)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (_oversize, "INPUT_INVALID"),
        (_not_json, "INPUT_INVALID"),
        (_not_utf8, "INPUT_INVALID"),
        (_duplicate_key, "INPUT_INVALID"),
        (_extra_member, "INPUT_INVALID"),
        (_caller_hash, "INPUT_INVALID"),
        (_other_schema, "INPUT_INVALID"),
        (_relative_path, "INPUT_INVALID"),
        (_nul_path, "INPUT_INVALID"),
        (_one_round, "INPUT_INVALID"),
        (_missing_slot, "INPUT_INVALID"),
        (_missing_file, "INPUT_INVALID"),
        (_directory, "INPUT_INVALID"),
        (_swapped_slots, "HOST_CAPTURE_INVALID"),
        (_swapped_roles, "HOST_CAPTURE_INVALID"),
        (_changed_export, "HOST_CAPTURE_INVALID"),
        (_invalid_exr, "NATIVE_TRANSPORT_MISMATCH"),
        (_round_difference, "NATIVE_TRANSPORT_MISMATCH"),
    ],
)
def test_a_refused_input_prints_only_a_value_free_reason(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    change: Change,
    code: str,
) -> None:
    request, _ = fixture(export_tests, tmp_path)
    proc = validate(export_tests, change(tmp_path, request))
    assert proc.returncode == 2 and proc.stdout == b""
    assert proc.stderr == f"snapshot-capture-validate refused: {code}\n".encode()


def store_cli(store: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tools.parity.store", "--store", str(store), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("amount", ["0.5", "1.0", "-0.0"])
def test_the_wrapper_admits_the_recording_into_an_external_store(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    amount: str,
) -> None:
    request, key = fixture(export_tests, tmp_path / "authored", amount)
    work = tmp_path / "authored" / "h-capture"
    root = tmp_path / "store"
    assert store_cli(root, "init").returncode == 0
    admit = [
        "admit-snapshot-capture",
        str(work),
        "--producer-policy",
        str(POLICY),
        "--approved-policy-sha256",
        POLICY_SHA256,
        "--approved-policy-revision",
        "1",
        "--validator-binary",
        str(export_tests),
        "--approved-binary-sha256",
        sha(export_tests.read_bytes()),
        "--approved-code-sha256",
        framed_sources(),
    ]
    artifacts = expected_slots(request)
    identifier = capture_id(artifacts)
    first = store_cli(root, *admit)
    assert first.returncode == 0, first.stdout + first.stderr
    assert first.stdout == f"snapshot capture {identifier} admitted\n"

    store = OracleStore.open(root)
    resolution = resolve_snapshot_capture(
        store, identifier, approved_policy_sha256=POLICY_SHA256, approved_policy_revision=1
    )
    assert resolution.status is Status.AVAILABLE
    document = resolution.document
    assert document is not None
    assert document["artifacts"] == artifacts
    assert document["validation"]["signature_sha256"] == key
    assert document["validation"]["validator_code_sha256"] == framed_sources()
    assert document["validation"]["validator_binary_sha256"] == sha(export_tests.read_bytes())
    assert {ref["sha256"] for ref in (artifacts["receipt"], artifacts["request"])} <= store.index()
    exports = [*artifacts["scalar_exports"], *artifacts["rgb_exports"]]
    assert {ref["sha256"] for ref in exports} <= store.index()
    assert store.check() == []
    # The stored receipt keeps the raw double and the original capture's project and revision.
    receipt_ref = artifacts["receipt"]
    stored = store.load(receipt_ref["sha256"], receipt_ref["size_bytes"])
    assert stored is not None
    receipt = parse_document(stored)
    context = json.loads((work / "context.json").read_bytes())
    assert str(receipt["signature"]["params"]["amount"]) == amount
    assert (receipt["project_uuid"], receipt["revision"]) == (
        context["project_uuid"],
        context["revision"],
    )

    # An identical retry revalidates and keeps the original document, timestamp and identity.
    second = store_cli(root, *admit)
    assert second.returncode == 0, second.stdout + second.stderr
    again = resolve_snapshot_capture(
        store, identifier, approved_policy_sha256=POLICY_SHA256, approved_policy_revision=1
    )
    assert again.document == document

    # A corrupted authored blob makes the whole capture unavailable.
    blob = store.blob_path(artifacts["scalar_exports"][1]["sha256"])
    blob.chmod(stat.S_IREAD | stat.S_IWRITE)
    blob.write_bytes(b"corrupted authored blob")
    after = resolve_snapshot_capture(
        store, identifier, approved_policy_sha256=POLICY_SHA256, approved_policy_revision=1
    )
    assert after.status is Status.ORACLE_UNAVAILABLE
    assert store.check()

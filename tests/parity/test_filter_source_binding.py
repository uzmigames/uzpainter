"""J1-J4 source binding between an authored admitted F capture and an authored admitted H
capture in one real pytest oracle store; no private evidence, Painter or native run (the H
admission uses the authored trusted-validator double of tests/parity/test_snapshot_capture.py)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import tests.parity.test_painter_filter_context as context_world
from tests.parity.test_filter_context_run import Painter, load, record_with
from tests.parity.test_snapshot_host_transport import PINS, record
from tools.parity import filter_context_validation as validation
from tools.parity import filter_source_binding as binding
from tools.parity.filter_context_contract import MISSING_SETTINGS
from tools.parity.filter_context_producer_policy import APPROVED_F_PRODUCER
from tools.parity.recorder.environment import (
    ENVIRONMENT_KIND,
    ENVIRONMENT_RECORD_ID,
    colour_configuration_sha256,
    envelope_sha256,
)
from tools.parity.recorder.output import GOLDEN_RECORD_ID
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.snapshot_host_transport import host_transport
from tools.parity.store import snapshot_capture as capture
from tools.parity.store.snapshot_contract import (
    POLICY_SCHEMA,
    REPORT_SCHEMA,
    VALIDATOR_REVISION,
    capture_id,
)
from tools.parity.store.snapshot_validator import SnapshotValidation
from tools.parity.store.store import OracleStore
from tools.parity.tier0_semantics import filter_context_control as control
from tools.parity.tier0_semantics.source_substance_control import RESOURCE_URL

PARAMETERS = {"signed": -0.0, "integer": 1, "double": 1.0}
PARTS = {
    "context": "starter_assets",
    "name": "grunge_brushed/grunge_brushed",
    "version": RESOURCE_URL.split("?version=")[1],
}
OTHER_URL = "resource://starter_assets/other/other?version=1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def recipe_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """The authored context world's source names recipe A's step-5 resource."""
    for key, value in PARTS.items():
        monkeypatch.setattr(context_world.ResourceID, key, value)
    monkeypatch.setattr(context_world.ResourceID, "url", lambda self: RESOURCE_URL)


def admit_f(
    store: OracleStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    painter: Painter,
    change: Callable[[dict[str, Any]], None] | None = None,
) -> bytes:
    """An authored F recording admitted into `store` with its environment and input."""
    rec = load(record_with(painter, tmp_path / "f-run"))
    if change is not None:
        change(rec)
    manifest = control.request()
    manifest["software"]["painter"] = deepcopy(rec["key"]["painter_build"])
    environment = {
        "schema": "uzpainter/parity/oracle-environment/1",
        "basis": "recorded",
        "painter_build": rec["key"]["painter_build"]["build_id"],
        "gpu_model": "authored GPU",
        "driver_version": "authored driver",
        "os_build": "authored OS",
        "colour_configuration_sha256": colour_configuration_sha256(validation.LEGACY),
        "recorder_version": APPROVED_F_PRODUCER.recorder_version,
    }
    rec["environment"] = environment
    registry = {
        "painter_build": environment["painter_build"],
        "envelope_sha256": envelope_sha256(environment),
        "equivalent_envelopes": [],
    }
    monkeypatch.setattr(
        validation, "registry_snapshot", lambda: (b"authored registry", deepcopy(registry))
    )
    build = manifest["software"]["painter"]["build_id"]
    refs = []
    for identity, kind, value in (
        (GOLDEN_RECORD_ID, "private_oracle_record", rec),
        (ENVIRONMENT_RECORD_ID, ENVIRONMENT_KIND, environment),
    ):
        data = json.dumps(value).encode()
        source = tmp_path / f"{identity}.json"
        source.write_bytes(data)
        store.add_record(
            build, manifest["golden_id"], identity, kind, source, sha(data), source.name
        )
        refs.append(
            {"record_id": identity, "kind": kind, "sha256": sha(data), "size_bytes": len(data)}
        )
    manifest["private_records"] = refs
    job = probe_job_from_manifest(control.request())
    for item in manifest["inputs"]:
        store.add_input(job.inputs[item["input_id"]], item["sha256"], item["path"])
    return json.dumps(manifest).encode()


def h_source(url: str = RESOURCE_URL, parts: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "resource": url,
        "resource_id": {"url": url, **(parts or PARTS)},
        "parameters": deepcopy(PARAMETERS),
        "inputs": [],
        "outputs": ["scalar"],
        "active_output": "scalar",
        "resolution": {"mode": "Auto", "value": [128, 128], "log2_offset": 0},
        "opacity": 1,
        "blending": "Normal",
    }


def admit_h(
    store: OracleStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: dict[str, Any],
) -> tuple[str, str]:
    """An authored H recording of `source`, admitted with the trusted-validator double."""
    url = source["resource"]

    def mutate(work: Path, context: Any, request: dict[str, Any], receipt: dict[str, Any]) -> None:
        request["resource"], request["parameters"] = url, {}
        receipt["resource"] = url
        receipt["readback"]["sources"] = [deepcopy(source), deepcopy(source)]
        receipt["signature"]["asset"] = "uzasset://snapshot/" + sha(url.encode())
        receipt["signature"]["params"] = deepcopy(source["parameters"])

    work = record(tmp_path / "h", mutate)
    transport = host_transport(work)
    artifacts = {k: v for k, v in transport.section.items() if k != "protocol"}
    refs = [artifacts["receipt"], artifacts["request"], *artifacts["scalar_exports"]]
    refs += artifacts["rgb_exports"]
    ids = ("receipt", "request", "r1-scalar", "r2-scalar", "r1-rgb", "r2-rgb")
    for ref, identity in zip(refs, ids, strict=True):
        ref["record_id"] = identity
    policy = json.dumps(
        {
            "schema": POLICY_SCHEMA,
            "revision": 1,
            "producers": [{"protocol": "paired-scalar-rgb", "source_revision": "1" * 40, **PINS}],
        }
    ).encode()
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
    monkeypatch.setattr(
        capture,
        "validate_snapshot_capture",
        lambda work, **kwargs: SnapshotValidation(report, sha(policy), 1, "1" * 40),
    )
    capture.admit_snapshot_capture(
        store,
        work,
        binary=tmp_path / "never-run.exe",
        approved_binary_sha256="7" * 64,
        approved_code_sha256="6" * 64,
        policy_bytes=policy,
        approved_policy_sha256=sha(policy),
        approved_policy_revision=1,
    )
    return capture_id(artifacts), sha(policy)


def bind(
    store: OracleStore, manifest: bytes, h: tuple[str, str], policy: str | None = None
) -> dict[str, Any]:
    return binding.bind_filter_source(
        store=store,
        f_manifest=manifest,
        h_capture_id=h[0],
        approved_policy_sha256=policy or h[1],
        approved_policy_revision=1,
    )


def toggled(extra: dict[int, Any] | None = None) -> Painter:
    """Steps 13 and 15 of both rounds read the state the pre16 boundary reads."""
    answers: dict[Any, Any] = {
        13: {"value": deepcopy(PARAMETERS)},
        15: {"value": deepcopy(PARAMETERS)},
    }
    return Painter({**answers, **(extra or {})})


def refused(kind: str) -> dict[str, Any]:
    return {"value": None, "raised": {"type": kind, "message": "authored"}}


def test_admitted_f_and_h_bind_their_source_without_authorizing_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = OracleStore.init(tmp_path / "store")
    manifest = admit_f(store, tmp_path, monkeypatch, toggled())
    h = admit_h(store, tmp_path, monkeypatch, h_source())
    report = bind(store, manifest, h)
    assert report["status"] == "source_bound" and report["joins"] == dict.fromkeys(
        ("J1", "J2", "J3", "J4"), True
    )
    assert report["acceptance"] == {
        "importer": "not_authorized",
        "missing_effective_settings": list(MISSING_SETTINGS),
    }
    assert report["f"]["resolution_value_kinds"] == ["tuple", "tuple"]
    assert report["f"]["toggle_bool_writes"] == [{"outcome": "succeeded"}] * 2
    assert report["h"]["capture_id"] == h[0] and report["f"]["manifest_sha256"] == sha(manifest)
    text = json.dumps(report)
    assert RESOURCE_URL not in text and "grunge" not in text and "signed" not in text


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("other-url", "J1_SOURCE_IDENTITY"),
        ("other-context", "J1_SOURCE_IDENTITY"),
        ("double-for-integer", "J2_PRE16_PARAMETERS"),
        ("unsigned-zero", "J2_PRE16_PARAMETERS"),
        # The committed F context contract keeps source parameters in the /3 scalar domain, so a
        # bool or vector parameter refuses before any join.
        ("bool-in-pre16", "F_CONTEXT_INVALID"),
        ("vector-in-pre16", "F_CONTEXT_INVALID"),
        ("step15-differs", "J3_PRE16_STATE"),
        ("bool-write-other-error", "J3_BOOL_WRITE"),
        ("bool-refused-state-changed", "J3_PRE16_STATE"),
        ("int-write-failed", "J3_INT_WRITE"),
        ("step13-raised", "J3_PRE16_STATE"),
        ("other-outputs", "J4_OUTPUTS"),
        ("other-resolution", "J4_OUTPUTS"),
        ("unknown-container", "J4_OUTPUTS"),
        ("wrong-policy", "H_ADMISSION_UNAVAILABLE"),
        ("unadmitted-f", "F_RECORD_UNBOUND"),
        ("manifest-not-naming-record", "F_RECORD_UNBOUND"),
        ("f-context-invalid", "F_CONTEXT_INVALID"),
    ],
)
def test_each_join_refuses_with_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: str
) -> None:
    store = OracleStore.init(tmp_path / "store")
    painter = toggled()
    source = h_source()
    change = None
    if case == "other-url":
        source = h_source(
            OTHER_URL, {"context": "starter_assets", "name": "other/other", "version": "1"}
        )
    elif case == "other-context":
        source = h_source(parts={**PARTS, "context": "project_instance"})
    elif case == "double-for-integer":
        source["parameters"]["integer"] = 1.0
    elif case == "unsigned-zero":
        source["parameters"]["signed"] = 0.0
    elif case == "bool-in-pre16":
        monkeypatch.setattr(
            context_world.SourceSubstance,
            "get_parameters",
            lambda self: {**PARAMETERS, "integer": True},
        )
    elif case == "vector-in-pre16":
        monkeypatch.setattr(
            context_world.SourceSubstance,
            "get_parameters",
            lambda self: {**PARAMETERS, "vector": [0.25, 0.75]},
        )
    elif case == "step15-differs":
        painter = toggled({15: {"value": {**PARAMETERS, "integer": 2}}})
    elif case == "bool-write-other-error":
        painter = toggled({14: refused("RuntimeError")})
    elif case == "bool-refused-state-changed":
        painter = toggled({14: refused("TypeError"), 15: {"value": {**PARAMETERS, "integer": 0}}})
    elif case == "int-write-failed":
        painter = toggled({12: refused("TypeError")})
    elif case == "step13-raised":
        painter = toggled({13: refused("RuntimeError")})
    elif case == "other-outputs":
        source["outputs"], source["active_output"] = ["other"], "other"
    elif case == "other-resolution":
        source["resolution"]["value"] = [256, 256]
    elif case == "unknown-container":
        monkeypatch.setattr(
            context_world.SourceSubstance,
            "resolution",
            SimpleNamespace(mode=context_world.Mode.Auto, value=range(2), log2_offset=0),
        )
    elif case == "f-context-invalid":

        def change(rec: dict[str, Any]) -> None:
            outputs = rec["recordings"][1]["outputs"]
            rec["recordings"][1]["outputs"] = [
                o for o in outputs if not o["output_id"].startswith("context/after-reopen/")
            ]

    manifest = admit_f(store, tmp_path, monkeypatch, painter, change)
    if case == "unadmitted-f":
        document = json.loads(manifest)
        entry = store.entry_path(
            document["software"]["painter"]["build_id"],
            document["golden_id"],
            ENVIRONMENT_RECORD_ID,
        )
        entry.chmod(0o600)
        entry.unlink()
    if case == "manifest-not-naming-record":
        document = json.loads(manifest)
        document["private_records"][0]["sha256"] = "8" * 64
        manifest = json.dumps(document).encode()
    h = admit_h(store, tmp_path, monkeypatch, source)
    with pytest.raises(binding.SourceBindingRefused, match=f"^{code}$"):
        bind(store, manifest, h, "9" * 64 if case == "wrong-policy" else None)


def drift(monkeypatch: pytest.MonkeyPatch, *, unreadable: bool = False) -> None:
    """The registry the binding reads first, then another one (or none) on every later read."""
    first = validation.registry_snapshot()
    calls = []

    def snapshot() -> tuple[bytes, dict[str, Any]]:
        calls.append(1)
        if len(calls) == 1:
            return first
        if unreadable:
            raise ValueError("authored unreadable registry")
        return b"drifted registry", deepcopy(first[1])

    monkeypatch.setattr(validation, "registry_snapshot", snapshot)


@pytest.mark.parametrize(
    ("case", "original"),
    [
        ("successful-join", None),
        ("failed-join", "J4_OUTPUTS"),
        ("receipt-failure", "F_RECORD_UNBOUND"),
        # The receipt stage reads the registry too, so it refuses first; the drift supersedes it.
        ("unreadable-after", "F_RECORD_UNBOUND"),
    ],
)
def test_registry_drift_refuses_whatever_the_binding_concluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, original: str | None
) -> None:
    store = OracleStore.init(tmp_path / "store")
    manifest = admit_f(store, tmp_path, monkeypatch, toggled())
    source = h_source()
    if case == "failed-join":
        source["resolution"]["value"] = [256, 256]
    if case == "receipt-failure":
        document = json.loads(manifest)
        document["private_records"][0]["sha256"] = "8" * 64
        manifest = json.dumps(document).encode()
    h = admit_h(store, tmp_path, monkeypatch, source)
    drift(monkeypatch, unreadable=case == "unreadable-after")
    with pytest.raises(binding.SourceBindingRefused, match=r"^REGISTRY_DRIFT$") as refused:
        bind(store, manifest, h)
    assert refused.value.original == original
    cause = refused.value.__cause__
    if original is None and case == "successful-join":
        assert cause is None
    if original is not None:
        assert isinstance(cause, binding.SourceBindingRefused) and cause.code == original


def test_a_list_resolution_container_binds_and_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        context_world.SourceSubstance,
        "resolution",
        SimpleNamespace(mode=context_world.Mode.Auto, value=[128, 128], log2_offset=0),
    )
    store = OracleStore.init(tmp_path / "store")
    manifest = admit_f(store, tmp_path, monkeypatch, toggled())
    report = bind(store, manifest, admit_h(store, tmp_path, monkeypatch, h_source()))
    assert report["status"] == "source_bound"
    assert report["f"]["resolution_value_kinds"] == ["list", "list"]


@pytest.mark.parametrize(
    ("stage", "code"),
    [("f-receipt", "F_RECORD_UNBOUND"), ("h-resolution", "BINDING_UNAVAILABLE")],
)
def test_io_failures_refuse_with_a_code_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, code: str
) -> None:
    store = OracleStore.init(tmp_path / "store")
    manifest = admit_f(store, tmp_path, monkeypatch, toggled())
    h = admit_h(store, tmp_path, monkeypatch, h_source())
    secret = str(tmp_path / "PRIVATE_SENTINEL")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError(secret)

    target = validation if stage == "f-receipt" else binding
    monkeypatch.setattr(
        target, "receipt" if stage == "f-receipt" else "resolve_snapshot_capture", fail
    )
    with pytest.raises(binding.SourceBindingRefused) as refused:
        bind(store, manifest, h)
    assert refused.value.code == code and str(refused.value) == code
    assert refused.value.__cause__ is None and refused.value.original is None
    assert "PRIVATE_SENTINEL" not in repr(refused.value.args)


def test_a_bool_write_refused_with_type_error_and_no_state_change_binds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recipe A's bool write is an observation: a TypeError refusal that left steps 13, 15 and
    the pre16 boundary on one typed state binds, and is reported without its message."""
    store = OracleStore.init(tmp_path / "store")
    manifest = admit_f(store, tmp_path, monkeypatch, toggled({14: refused("TypeError")}))
    report = bind(store, manifest, admit_h(store, tmp_path, monkeypatch, h_source()))
    assert report["status"] == "source_bound"
    assert report["f"]["toggle_bool_writes"] == [{"outcome": "refused", "type": "TypeError"}] * 2
    assert "authored" not in json.dumps(report)

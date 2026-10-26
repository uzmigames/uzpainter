"""Authored F receipts and mocked admission only; no private oracle, UI, or Painter process."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.parity.test_filter_context_run import Painter, load, record_with
from tools.parity import filter_context_validation as validation
from tools.parity.filter_context_contract import MISSING_SETTINGS
from tools.parity.recorder.environment import (
    ENVIRONMENT_KIND,
    ENVIRONMENT_RECORD_ID,
    colour_configuration_sha256,
    envelope_sha256,
    recorder_version,
)
from tools.parity.recorder.output import GOLDEN_RECORD_ID
from tools.parity.store.store import Status
from tools.parity.tier0_semantics import filter_context_control as control


@pytest.fixture
def authored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any]]:
    record = load(record_with(Painter(), tmp_path))
    manifest = control.request()
    manifest["software"]["painter"] = deepcopy(record["key"]["painter_build"])
    environment = {
        "schema": "uzpainter/parity/oracle-environment/1",
        "basis": "recorded",
        "painter_build": record["key"]["painter_build"]["build_id"],
        "gpu_model": "authored GPU",
        "driver_version": "authored driver",
        "os_build": "authored OS",
        "colour_configuration_sha256": colour_configuration_sha256(validation.LEGACY),
        "recorder_version": recorder_version(),
    }
    record["environment"] = environment
    registry = {
        "painter_build": environment["painter_build"],
        "envelope_sha256": envelope_sha256(environment),
        "equivalent_envelopes": [],
    }
    monkeypatch.setattr(
        validation, "registry_snapshot", lambda: (b"authored registry", deepcopy(registry))
    )
    return manifest, record


def admitted(manifest: dict[str, Any], record: dict[str, Any]) -> Mock:
    raw = json.dumps(record).encode()
    env = json.dumps(record["environment"]).encode()
    blobs = {validation.digest(raw): raw, validation.digest(env): env}
    manifest["private_records"] = [
        {
            "record_id": identity,
            "kind": kind,
            "sha256": validation.digest(data),
            "size_bytes": len(data),
        }
        for identity, kind, data in (
            (GOLDEN_RECORD_ID, "private_oracle_record", raw),
            (ENVIRONMENT_RECORD_ID, ENVIRONMENT_KIND, env),
        )
    ]
    entries = {r["record_id"]: SimpleNamespace(**r) for r in manifest["private_records"]}
    store = Mock()
    store.entry.side_effect = lambda build, golden, identity: entries.get(identity)
    store.load.side_effect = lambda sha, size=None: blobs.get(sha)
    store.resolve.return_value = SimpleNamespace(status=Status.AVAILABLE)
    return store


def inspect(manifest: dict[str, Any], store: Mock) -> dict[str, Any]:
    return validation.inspect_capture(json.dumps(manifest).encode(), store)


def test_admitted_receipt_and_observable_domain_never_accept_missing_settings(
    authored: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    manifest, record = authored
    store = admitted(manifest, record)
    report = inspect(manifest, store)
    assert "failure" not in report, report.get("failure")
    assert report["capture"]["status"] == report["observable_f_domain"]["status"] == "validated"
    assert report["capture"]["rounds"] == 2 and report["observable_f_domain"]["boundaries"] == 5
    assert report["effective_settings"] == {
        "status": "unverified",
        "missing": list(MISSING_SETTINGS),
    }
    assert report["acceptance"] == {"status": "blocked", "code": validation.SETTINGS_BLOCK}
    assert store.resolve.call_count == len(manifest["inputs"])


@pytest.mark.parametrize(
    "mutation",
    [
        "unadmitted",
        "blob_hash",
        "blob_size",
        "missing_blob",
        "input_bytes",
        "extra_ref",
        "recipe",
        "input_pin",
        "key",
        "record_environment",
        "envelope",
        "legacy",
        "recorder",
        "build",
        "sessions",
        "settings_claim",
        "resource_hashes",
    ],
)
def test_forged_receipt_or_context_refuses_before_domain(
    authored: tuple[dict[str, Any], dict[str, Any]],
    mutation: str,
) -> None:
    manifest, record = authored
    if mutation == "recipe":
        manifest["instruction_sequence"]["steps"][0]["args"]["default_texture_resolution"] = 256
    elif mutation == "input_pin":
        manifest["inputs"][0]["sha256"] = "0" * 64
    elif mutation == "key":
        record["key"]["instruction_sequence_sha256"] = "0" * 64
    elif mutation == "envelope":
        record["environment"]["gpu_model"] = "another GPU"
    elif mutation == "legacy":
        record["key"]["effective_defaults"]["colour_management"]["mode"] = "ocio"
    elif mutation == "recorder":
        record["environment"]["recorder_version"] = "invented/1"
    elif mutation == "build":
        manifest["software"]["painter"]["version"] = "1.0.0"
    elif mutation == "sessions":
        record["recordings"][1]["session_id"] = "other-session"
    elif mutation == "settings_claim":
        record["key"]["project_settings"]["workflow"] = "Default"
    elif mutation == "resource_hashes":
        record["key"]["resource_hashes"] = ["0" * 64]
    store = admitted(manifest, record)
    if mutation == "unadmitted":
        store.entry.side_effect = None
        store.entry.return_value = None
    elif mutation == "blob_hash":
        store.load.side_effect = lambda *args: b"{}"
    elif mutation == "blob_size":
        manifest["private_records"][0]["size_bytes"] += 1
    elif mutation == "missing_blob":
        store.load.side_effect = lambda *args: None
    elif mutation == "input_bytes":
        store.resolve.return_value = SimpleNamespace(status=Status.ORACLE_UNAVAILABLE)
    elif mutation == "extra_ref":
        manifest["private_records"].append(deepcopy(manifest["private_records"][0]))
    elif mutation == "record_environment":
        changed = deepcopy(record["environment"])
        changed["os_build"] = "other OS"
        data = json.dumps(changed).encode()
        ref = manifest["private_records"][1]
        ref.update(sha256=validation.digest(data), size_bytes=len(data))
        prior_entry, prior_load = store.entry.side_effect, store.load.side_effect
        store.entry.side_effect = lambda build, golden, identity: (
            SimpleNamespace(**ref)
            if identity == ENVIRONMENT_RECORD_ID
            else prior_entry(build, golden, identity)
        )
        store.load.side_effect = lambda sha, size=None: (
            data if sha == ref["sha256"] else prior_load(sha, size)
        )
    report = inspect(manifest, store)
    assert report["capture"]["status"] == "refused", report
    assert report["observable_f_domain"]["status"] == "not_checked"
    assert report["acceptance"]["status"] == "blocked"
    assert report["effective_settings"]["missing"] == list(MISSING_SETTINGS)
    if mutation in ("unadmitted", "extra_ref", "recipe", "input_pin", "blob_size"):
        store.load.assert_not_called()


@pytest.mark.parametrize("mutation", ["missing_context", "host_opacity", "lookup"])
def test_domain_refusal_preserves_verified_capture(
    authored: tuple[dict[str, Any], dict[str, Any]],
    mutation: str,
) -> None:
    manifest, record = authored
    outputs = record["recordings"][0]["outputs"]
    if mutation == "missing_context":
        outputs[:] = [o for o in outputs if not o["output_id"].startswith("context/after-setup6/")]
    else:
        row = next(
            o
            for o in outputs
            if o["output_id"].startswith("context/after-setup6/")
            and o["call"].endswith(
                ".get_opacity" if mutation == "host_opacity" else ".get_node_by_uid"
            )
            and o["args"]["selector"].get("path") == [["Root", 0]]
        )
        if mutation == "host_opacity":
            row["value"] = 0.5
        else:
            row["value"]["name"] = "contradictory"
    report = inspect(manifest, admitted(manifest, record))
    assert report["capture"]["status"] == "validated", report.get("failure")
    assert report["observable_f_domain"]["status"] == "refused"
    assert report["failure"]["stage"] == "observable_f_domain"
    assert report["acceptance"]["status"] == "blocked"


@pytest.mark.parametrize("data", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e-999}', b"[]"])
def test_strict_decode_refuses_ambiguous_or_unrepresentable_json(data: bytes) -> None:
    with pytest.raises(ValueError):
        validation.decode(data)


@pytest.mark.parametrize("domain_refuses", [False, True])
def test_registry_drift_refuses_capture_even_after_domain_failure(
    authored: tuple[dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    domain_refuses: bool,
) -> None:
    manifest, record = authored
    if domain_refuses:
        outputs = record["recordings"][0]["outputs"]
        outputs[:] = [o for o in outputs if not o["output_id"].startswith("context/after-setup6/")]
    before, current = validation.registry_snapshot()
    snapshots = iter([(before, current), (b"changed registry", current)])
    monkeypatch.setattr(validation, "registry_snapshot", lambda: next(snapshots))
    report = inspect(manifest, admitted(manifest, record))
    assert report["capture"]["status"] == "refused"
    assert report["capture"]["registry_sha256"] == validation.digest(before)
    assert report["acceptance"]["status"] == "blocked"
    if domain_refuses:
        assert report["failure"]["stage"] == "observable_f_domain"
        assert report["additional_failures"][0]["stage"] == "receipt_registry"
    else:
        assert report["failure"]["stage"] == "receipt_registry"


def test_cli_private_report_write_once_and_stdout_only_hashes_counts(
    authored: tuple[dict[str, Any], dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, record = authored
    store = admitted(manifest, record)
    manifest_file, output = tmp_path / "manifest.json", tmp_path / "validation.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(validation, "locate", lambda: store)
    monkeypatch.setattr(
        sys, "argv", ["validate", "--manifest", str(manifest_file), "--output", str(output)]
    )
    assert validation.main() == 2
    raw = output.read_bytes()
    public = json.loads(capsys.readouterr().out)
    assert public == {
        "report_sha256": validation.digest(raw),
        "rounds": 2,
        "boundaries": 5,
        "failures": 0,
        "acceptances": 0,
    }
    assert validation.main() == 2
    assert output.read_bytes() == raw
    assert json.loads(capsys.readouterr().out) == {"failures": 1, "acceptances": 0}


def test_cli_preserves_private_failure_without_printing_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "failure.json"
    monkeypatch.setattr(validation, "locate", Mock(side_effect=ValueError("PRIVATE_SENTINEL")))
    monkeypatch.setattr(sys, "argv", ["validate", "--manifest", "unused", "--output", str(output)])
    assert validation.main() == 2
    public = capsys.readouterr().out
    report = json.loads(output.read_bytes())
    assert "PRIVATE_SENTINEL" in report["failure"]["traceback"]
    assert "PRIVATE_SENTINEL" not in public and json.loads(public)["failures"] == 1
    assert report["acceptance"]["status"] == "blocked"

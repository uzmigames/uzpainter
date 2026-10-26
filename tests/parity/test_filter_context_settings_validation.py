"""Authored records and mocked oracle admissions; no Painter or private oracle reads."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image

from tests.parity.test_filter_context_run import Painter, load, record_with
from tests.parity.test_filter_context_settings import IMPORT_PATH, MESH
from tests.parity.test_filter_context_settings import authored as panel_record
from tools.parity import filter_context_producer_policy as policy
from tools.parity import filter_context_settings_validation as validation
from tools.parity import filter_context_validation as common
from tools.parity.filter_context_contract import require_effective_settings, typed
from tools.parity.filter_context_settings import SettingsRefused
from tools.parity.recorder.environment import (
    ENVIRONMENT_KIND,
    ENVIRONMENT_RECORD_ID,
    colour_configuration_sha256,
    envelope_sha256,
)
from tools.parity.recorder.output import GOLDEN_RECORD_ID, private_record_refs
from tools.parity.store.store import Status
from tools.parity.tier0_semantics import filter_context_settings_control as control


def png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (2, 3), (17, 31, 47)).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def authored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any]]:
    record = load(record_with(Painter(), tmp_path))
    record["golden_id"] = control.GOLDEN_ID
    source, _ = panel_record()
    panels = {
        output["values"]["boundary"]: output
        for recording in source["recordings"]
        for output in recording["outputs"]
        if output["kind"] == "settings_panel_readback"
    }
    png = png_bytes()
    for recording in record["recordings"]:
        outputs = recording["outputs"]
        amended: list[dict[str, Any]] = []
        index = 0
        while index < len(outputs):
            output = outputs[index]
            if not output["output_id"].startswith("context/"):
                amended.append(output)
                index += 1
                continue
            boundary = output["output_id"].split("/")[1]
            frame = []
            while index < len(outputs) and outputs[index]["output_id"].startswith(
                f"context/{boundary}/"
            ):
                row = outputs[index]
                if row["call"].endswith("project.last_imported_mesh_path"):
                    row["value"] = IMPORT_PATH
                frame.append(row)
                amended.append(row)
                index += 1
            panel = deepcopy(panels[boundary])
            binding = panel["values"]["binding"]
            for side in ("before", "after"):
                binding[side]["session_id"] = recording["session_id"]
            binding["context_before_sha256"] = common.digest(typed(frame))
            binding["context_after_sha256"] = common.digest(typed(frame))
            binding["context_after_outputs"] = deepcopy(frame)
            amended.append(panel)
            amended.extend(
                {
                    "output_id": image["output_id"],
                    "kind": validation.IMAGE_KIND,
                    "panel": "Project Configuration",
                    "blob": {
                        "sha256": common.digest(png),
                        "size_bytes": len(png),
                        "media_type": "image/png",
                    },
                }
                for image in panel["values"]["images"]
            )
        recording["outputs"] = amended
    environment = {
        "schema": "uzpainter/parity/oracle-environment/1",
        "basis": "recorded",
        "painter_build": record["key"]["painter_build"]["build_id"],
        "gpu_model": "authored GPU",
        "driver_version": "authored driver",
        "os_build": "authored OS",
        "colour_configuration_sha256": colour_configuration_sha256(common.LEGACY),
        "recorder_version": policy.APPROVED_SETTINGS_F_PRODUCER.recorder_version,
    }
    record["environment"] = environment
    registry = {
        "painter_build": environment["painter_build"],
        "envelope_sha256": envelope_sha256(environment),
        "equivalent_envelopes": [],
    }
    monkeypatch.setattr(
        common, "registry_snapshot", lambda: (b"authored registry", deepcopy(registry))
    )
    manifest = control.request()
    manifest["software"]["painter"] = deepcopy(record["key"]["painter_build"])
    return manifest, record


def admitted(
    manifest: dict[str, Any], record: dict[str, Any], png: bytes | None = None
) -> tuple[Mock, dict[str, bytes]]:
    image = png_bytes() if png is None else png
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            if output["kind"] == validation.IMAGE_KIND:
                output["blob"]["sha256"] = common.digest(image)
                output["blob"]["size_bytes"] = len(image)
    raw, env = json.dumps(record).encode(), json.dumps(record["environment"]).encode()
    blobs = {common.digest(data): data for data in (raw, env, image, MESH)}
    manifest["private_records"] = private_record_refs(
        raw, record, {common.digest(image): len(image)}
    )
    manifest["private_records"].append(
        {
            "record_id": ENVIRONMENT_RECORD_ID,
            "kind": ENVIRONMENT_KIND,
            "sha256": common.digest(env),
            "size_bytes": len(env),
        }
    )
    build, golden = manifest["software"]["painter"]["build_id"], manifest["golden_id"]
    entries = {
        (build, golden, ref["record_id"]): SimpleNamespace(**deepcopy(ref))
        for ref in manifest["private_records"]
    }
    store = Mock()
    store.entry.side_effect = lambda build, golden, identity: entries.get((build, golden, identity))
    store.load.side_effect = lambda sha, size=None: blobs.get(sha)
    store.resolve.return_value = SimpleNamespace(status=Status.AVAILABLE)
    return store, blobs


def encoded(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest).encode()


def test_complete_admitted_settings_remain_diagnostic(
    authored: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    manifest, record = authored
    store, _ = admitted(manifest, record)
    result = validation.load_settings_capture(encoded(manifest), store)
    assert result.manifest == manifest and result.record == record
    assert len(result.context.contexts) == len(result.settings.panels) == 5
    assert result.settings.effective_cm_per_unit == 1
    with pytest.raises(ValueError, match="F_EFFECTIVE_SETTINGS_UNVERIFIED"):
        require_effective_settings(result.context)
    report = validation.inspect_capture(encoded(manifest), store)
    assert "failure" not in report, report
    assert report["importer"] == "not_authorized" and report["acceptances"] == 0
    assert report["capture"]["screenshots"] == 10
    assert report["capture"]["producer_profile"] == {
        "profile_id": policy.APPROVED_SETTINGS_F_PRODUCER.profile_id,
        "recorder_version": policy.APPROVED_SETTINGS_F_PRODUCER.recorder_version,
        "source_revision": policy.APPROVED_SETTINGS_F_PRODUCER.source_revision,
    }
    assert report["effective_settings"]["status"] == "derived"
    assert "authored-project" not in json.dumps(report) and IMPORT_PATH not in json.dumps(report)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-ref",
        "missing-ref",
        "wrong-kind",
        "wrong-round",
        "historical-golden",
        "recipe",
        "historical-producer",
        "future-producer",
        "unadmitted",
        "missing-png",
        "changed-png",
        "wrong-size",
        "invalid-png",
        "png-crc",
        "mesh-bytes",
        "mesh-unavailable",
        "image-media",
        "panel-identity",
        "extra-operation",
        "record-bytes",
        "environment-bytes",
    ],
)
def test_fresh_admission_refuses_changed_roles_bytes_context_and_policy(
    authored: tuple[dict[str, Any], dict[str, Any]],
    mutation: str,
) -> None:
    manifest, record = authored
    png = None
    if mutation == "historical-producer":
        record["environment"]["recorder_version"] = policy.APPROVED_F_PRODUCER.recorder_version
    elif mutation == "future-producer":
        record["environment"]["recorder_version"] = "uzp-recorder/1+src.ffffffffffffffff"
    elif mutation == "invalid-png":
        png = b"authored non-PNG bytes"
    elif mutation == "png-crc":
        data = bytearray(png_bytes())
        data[29] ^= 1
        png = bytes(data)
    elif mutation == "image-media":
        next(o for o in record["recordings"][0]["outputs"] if o["kind"] == validation.IMAGE_KIND)[
            "blob"
        ]["media_type"] = "application/octet-stream"
    elif mutation == "panel-identity":
        next(
            o for o in record["recordings"][0]["outputs"] if o["kind"] == "settings_panel_readback"
        )["values"]["binding"]["after"]["pid"] += 1
    elif mutation == "extra-operation":
        record["recordings"][0]["outputs"].append(
            {
                "output_id": "invented-operation",
                "kind": "api_readback",
                "call": "unreviewed",
                "args": {},
                "value": None,
            }
        )
    store, blobs = admitted(manifest, record, png)
    image_ref = next(
        ref for ref in manifest["private_records"] if ref["kind"] == validation.IMAGE_KIND
    )
    if mutation == "extra-ref":
        manifest["private_records"].append({**image_ref, "record_id": "extra"})
    elif mutation == "missing-ref":
        manifest["private_records"].remove(image_ref)
    elif mutation == "wrong-kind":
        image_ref["kind"] = "private_oracle_record"
    elif mutation == "wrong-round":
        image_ref["record_id"] = image_ref["record_id"].replace("r1-", "r2-", 1)
    elif mutation == "historical-golden":
        manifest["golden_id"] = "tier0/api-probes/filter-context-a"
    elif mutation == "recipe":
        manifest["instruction_sequence"]["steps"][0]["args"]["default_texture_resolution"] = 64
    elif mutation == "unadmitted":
        store.entry.side_effect = lambda *args: None
    elif mutation == "missing-png":
        blobs.pop(image_ref["sha256"])
    elif mutation == "changed-png":
        blobs[image_ref["sha256"]] += b"changed"
    elif mutation == "wrong-size":
        image_ref["size_bytes"] += 1
    elif mutation == "mesh-bytes":
        blobs[common.digest(MESH)] = b"another mesh"
    elif mutation == "mesh-unavailable":
        store.resolve.return_value.status = Status.ORACLE_UNAVAILABLE
    elif mutation in {"record-bytes", "environment-bytes"}:
        identity = GOLDEN_RECORD_ID if mutation == "record-bytes" else ENVIRONMENT_RECORD_ID
        ref = next(r for r in manifest["private_records"] if r["record_id"] == identity)
        blobs[ref["sha256"]] += b"changed"
    report = validation.inspect_capture(encoded(manifest), store)
    assert report["capture"]["status"] == "refused" and "failure" in report
    assert report["importer"] == "not_authorized"
    if mutation == "unadmitted":
        store.load.assert_not_called()


@pytest.mark.parametrize("refuse_first", [False, True])
def test_registry_rechecked_on_success_and_manifest_refusal(
    authored: tuple[dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    refuse_first: bool,
) -> None:
    manifest, record = authored
    store, _ = admitted(manifest, record)
    initial = common.registry_snapshot()
    snapshots = (
        [initial, (b"changed registry", initial[1])]
        if refuse_first
        else [
            initial,
            initial,
            (b"changed registry", initial[1]),
        ]
    )
    reader = Mock(side_effect=snapshots)
    monkeypatch.setattr(common, "registry_snapshot", reader)
    report = validation.inspect_capture(b"invalid" if refuse_first else encoded(manifest), store)
    assert report["failure"]["code"] == "F_SETTINGS_REGISTRY_DRIFT"
    assert ("original" in report["failure"]) is refuse_first
    assert reader.call_count == len(snapshots)


def test_refusal_does_not_leak_original_exception(
    authored: tuple[dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, record = authored
    store, _ = admitted(manifest, record)
    monkeypatch.setattr(
        validation,
        "split_settings_outputs",
        Mock(side_effect=SettingsRefused("private path C:/private and secret observed value")),
    )
    with pytest.raises(validation.SettingsCaptureRefused) as caught:
        validation.load_settings_capture(encoded(manifest), store)
    assert str(caught.value) == "F_SETTINGS_PANELS"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert "private" not in str(caught.value)


def test_admitted_png_reference_still_must_match_inline_blob(
    authored: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    manifest, record = authored
    store, blobs = admitted(manifest, record)
    ref = next(r for r in manifest["private_records"] if r["kind"] == validation.IMAGE_KIND)
    stream = BytesIO()
    Image.new("RGB", (3, 2), (47, 31, 17)).save(stream, format="PNG")
    replacement = stream.getvalue()
    ref.update(sha256=common.digest(replacement), size_bytes=len(replacement))
    blobs[ref["sha256"]] = replacement
    entries = {r["record_id"]: SimpleNamespace(**r) for r in manifest["private_records"]}
    store.entry.side_effect = lambda build, golden, identity: entries.get(identity)
    report = validation.inspect_capture(encoded(manifest), store)
    assert report["failure"]["code"] == "F_SETTINGS_IMAGE_BINDING"


@pytest.mark.parametrize("missing", ["last-image", "environment"])
def test_every_admission_precedes_any_blob_load(
    authored: tuple[dict[str, Any], dict[str, Any]],
    missing: str,
) -> None:
    manifest, record = authored
    store, _ = admitted(manifest, record)
    identity = (
        ENVIRONMENT_RECORD_ID
        if missing == "environment"
        else [
            ref["record_id"]
            for ref in manifest["private_records"]
            if ref["kind"] == validation.IMAGE_KIND
        ][-1]
    )
    original = store.entry.side_effect
    store.entry.side_effect = lambda build, golden, record_id: (
        None if record_id == identity else original(build, golden, record_id)
    )
    report = validation.inspect_capture(encoded(manifest), store)
    assert report["failure"]["code"] == "F_SETTINGS_RECEIPT"
    store.load.assert_not_called()


def test_reference_inventory_is_unordered_but_record_slots_remain_ordered(
    authored: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    manifest, record = authored
    store, _ = admitted(manifest, record)
    manifest["private_records"].reverse()
    report = validation.inspect_capture(encoded(manifest), store)
    assert "failure" not in report, report


def test_registry_drift_supersedes_domain_refusal_without_private_text(
    authored: tuple[dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, record = authored
    store, _ = admitted(manifest, record)
    initial = common.registry_snapshot()
    monkeypatch.setattr(
        common,
        "registry_snapshot",
        Mock(
            side_effect=[
                initial,
                initial,
                (b"changed", initial[1]),
            ]
        ),
    )
    monkeypatch.setattr(
        validation, "split_settings_outputs", Mock(side_effect=ValueError("private observed data"))
    )
    report = validation.inspect_capture(encoded(manifest), store)
    assert report["failure"] == {
        "code": "F_SETTINGS_REGISTRY_DRIFT",
        "original": "F_SETTINGS_PANELS",
    }


def test_cli_private_write_once_counts_only(
    authored: tuple[dict[str, Any], dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, record = authored
    store, _ = admitted(manifest, record)
    source, output = tmp_path / "manifest.json", tmp_path / "report.json"
    source.write_bytes(encoded(manifest))
    monkeypatch.setattr(validation, "locate", lambda: store)
    monkeypatch.setattr(
        sys, "argv", ["settings-validation", "--manifest", str(source), "--output", str(output)]
    )
    assert validation.main() == 2
    stdout = json.loads(capsys.readouterr().out)
    assert stdout == {
        "report_sha256": common.digest(output.read_bytes()),
        "rounds": 2,
        "boundaries": 5,
        "screenshots": 10,
        "failures": 0,
        "acceptances": 0,
    }
    saved = output.read_bytes()
    assert json.loads(saved)["importer"] == "not_authorized"
    assert validation.main() == 2
    assert json.loads(capsys.readouterr().out) == {"failures": 1, "acceptances": 0}
    assert output.read_bytes() == saved

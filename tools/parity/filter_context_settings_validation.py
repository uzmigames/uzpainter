"""Offline admitted F settings diagnostics; never native import authorization.

Only the fixed settings golden and reviewed producer are accepted. Reports are not
inputs: every invocation reloads admitted record, environment, mesh and PNG bytes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from tools.parity import filter_context_producer_policy as producer_policy
from tools.parity import filter_context_validation as common
from tools.parity.filter_context_contract import (
    A_RECIPE_SHA256,
    BOUNDARIES,
    FContextEvidence,
    typed,
)
from tools.parity.filter_context_settings import (
    EffectiveSettingsEvidence,
    derive_effective_settings,
    split_settings_outputs,
)
from tools.parity.recorder.environment import ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.filter_context_run import _f_evidence_from_record
from tools.parity.recorder.output import GOLDEN_RECORD_ID, ensure_outside_repository, slug
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import OracleStore, Status, load_oracle, locate
from tools.parity.tier0_semantics import filter_context_settings_control as control

SCHEMA = "uzpainter/filter-context-settings-validation/1"
IMAGE_KIND = "settings_panel_evidence"
IMAGE_SUFFIXES = ("configuration-image", "physical-size-image")


class SettingsCaptureRefused(ValueError):
    """Value-free refusal, optionally preserving a refusal superseded by registry drift."""

    def __init__(self, code: str, original: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.original = original


@dataclass(frozen=True)
class SettingsCapture:
    """Python observations, not an authenticated native capability; raw data stays private."""

    manifest: dict[str, Any] = field(repr=False)
    record: dict[str, Any] = field(repr=False)
    context: FContextEvidence = field(repr=False)
    settings: EffectiveSettingsEvidence = field(repr=False)
    registry_sha256: str


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise SettingsCaptureRefused(code)


def _image_slots() -> tuple[tuple[str, str], ...]:
    return tuple(
        ("r1" if boundary in BOUNDARIES[:3] else "r2", f"settings/{boundary}/{suffix}")
        for boundary in BOUNDARIES
        for suffix in IMAGE_SUFFIXES
    )


def _ref_id(round_id: str, output_id: str) -> str:
    return f"{slug(round_id)}-{slug(output_id)}"


def manifest_request(manifest: dict[str, Any]) -> dict[str, Any]:
    """The exact authored settings request and its twelve fixed artifact roles."""
    _require(not validation_errors(manifest, Schema.GOLDEN_PUBLIC), "F_SETTINGS_MANIFEST")
    authored = control.request()

    def invariant(document: dict[str, Any]) -> dict[str, Any]:
        return {
            **{k: v for k, v in document.items() if k not in ("private_records", "software")},
            "software": {k: v for k, v in document["software"].items() if k != "painter"},
        }

    common.equal(invariant(manifest), invariant(authored), "F_SETTINGS_MANIFEST")
    _require(
        common.digest(typed(manifest["instruction_sequence"])) == A_RECIPE_SHA256,
        "F_SETTINGS_RECIPE",
    )
    expected = {
        (GOLDEN_RECORD_ID, "private_oracle_record"),
        (ENVIRONMENT_RECORD_ID, ENVIRONMENT_KIND),
        *((_ref_id(round_id, output_id), IMAGE_KIND) for round_id, output_id in _image_slots()),
    }
    refs = manifest["private_records"]
    _require(
        len(refs) == 12 and {(ref["record_id"], ref["kind"]) for ref in refs} == expected,
        "F_SETTINGS_REFERENCES",
    )
    return authored


def _screenshots(record: dict[str, Any], manifest: dict[str, Any], store: OracleStore) -> None:
    refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
    images = [
        (recording["recording_id"], output)
        for recording in record["recordings"]
        for output in recording["outputs"]
        if output["kind"] == IMAGE_KIND
    ]
    _require(
        tuple((round_id, output["output_id"]) for round_id, output in images) == _image_slots(),
        "F_SETTINGS_IMAGE_INVENTORY",
    )
    for round_id, output in images:
        ref = refs[_ref_id(round_id, output["output_id"])]
        blob = output["blob"]
        _require(
            ref["kind"] == output["kind"] == IMAGE_KIND
            and blob["media_type"] == "image/png"
            and typed([blob["sha256"], blob["size_bytes"]])
            == typed([ref["sha256"], ref["size_bytes"]]),
            "F_SETTINGS_IMAGE_BINDING",
        )
        data = load_oracle(store, ref)
        _require(
            type(data) is bytes
            and common.digest(data) == ref["sha256"]
            and len(data) == ref["size_bytes"],
            "F_SETTINGS_IMAGE_BYTES",
        )
        assert isinstance(data, bytes)
        with Image.open(BytesIO(data)) as image:
            _require(image.format == "PNG", "F_SETTINGS_IMAGE_FORMAT")
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            _require(image.width > 0 and image.height > 0, "F_SETTINGS_IMAGE_FORMAT")


def _mesh_bytes(authored: dict[str, Any], store: OracleStore) -> bytes:
    job = probe_job_from_manifest(authored)
    _require(len(authored["inputs"]) == 1, "F_SETTINGS_INPUTS")
    source = authored["inputs"][0]
    _require(source["input_id"] == "plane", "F_SETTINGS_INPUTS")
    size = job.inputs["plane"].stat().st_size
    resolution = store.resolve("plane", source["sha256"], size)
    _require(resolution.status is Status.AVAILABLE, "F_SETTINGS_INPUT_UNAVAILABLE")
    data = store.load(source["sha256"], size)
    _require(
        type(data) is bytes and len(data) == size and common.digest(data) == source["sha256"],
        "F_SETTINGS_INPUT_BYTES",
    )
    assert isinstance(data, bytes)
    return data


def load_settings_capture(manifest_bytes: bytes, store: OracleStore) -> SettingsCapture:
    """Reload admitted evidence under fixed policy; recheck registry even after refusal."""
    try:
        initial = common.registry_snapshot()
    except Exception:
        raise SettingsCaptureRefused("F_SETTINGS_REGISTRY_UNAVAILABLE") from None
    refused: SettingsCaptureRefused | None = None
    result: SettingsCapture | None = None
    stage = "F_SETTINGS_MANIFEST"
    try:
        manifest = common.decode(manifest_bytes)
        authored = manifest_request(manifest)
        stage = "F_SETTINGS_RECEIPT"
        record, _, _, registry_raw, current = common._receipt_data(manifest, store)
        _require(
            registry_raw == initial[0] and typed(current) == typed(initial[1]),
            "F_SETTINGS_REGISTRY_DRIFT",
        )
        stage = "F_SETTINGS_PRODUCER"
        producer_policy.resolve_settings_producer(record["environment"]["recorder_version"])
        stage = "F_SETTINGS_RECEIPT"
        common._validate_receipt_record(record, manifest, authored, store, current)
        stage = "F_SETTINGS_PANELS"
        core, panels = split_settings_outputs(record)
        stage = "F_SETTINGS_IMAGES"
        _screenshots(record, manifest, store)
        stage = "F_SETTINGS_CONTEXT"
        context = _f_evidence_from_record(
            core, authored["instruction_sequence"], expected_golden_id=control.GOLDEN_ID
        )
        stage = "F_SETTINGS_INPUTS"
        mesh = _mesh_bytes(authored, store)
        stage = "F_SETTINGS_DERIVATION"
        settings = derive_effective_settings(context, panels, mesh)
        result = SettingsCapture(manifest, record, context, settings, common.digest(initial[0]))
    except SettingsCaptureRefused as error:
        refused = SettingsCaptureRefused(error.code, error.original)
    except Exception:
        refused = SettingsCaptureRefused(stage)
    finally:
        try:
            final = common.registry_snapshot()
            _require(
                final[0] == initial[0] and typed(final[1]) == typed(initial[1]),
                "F_SETTINGS_REGISTRY_DRIFT",
            )
        except Exception:
            refused = SettingsCaptureRefused(
                "F_SETTINGS_REGISTRY_DRIFT", refused.code if refused else None
            )
    if refused is not None:
        raise refused from None
    assert result is not None
    return result


def _new_report() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "capture": {"status": "refused"},
        "effective_settings": {"status": "unverified"},
        "importer": "not_authorized",
        "acceptances": 0,
    }


def inspect_capture(manifest_bytes: bytes, store: OracleStore) -> dict[str, Any]:
    report = _new_report()
    try:
        capture = load_settings_capture(manifest_bytes, store)
    except SettingsCaptureRefused as error:
        report["failure"] = {"code": error.code}
        if error.original is not None:
            report["failure"]["original"] = error.original
        return report
    refs = {ref["record_id"]: ref for ref in capture.manifest["private_records"]}
    report["capture"] = {
        "status": "validated",
        "basis": "admitted_receipt_integrity_not_runtime_attestation",
        "producer_profile": asdict(
            producer_policy.resolve_settings_producer(
                capture.record["environment"]["recorder_version"]
            )
        ),
        "manifest_sha256": common.digest(manifest_bytes),
        "record_sha256": refs[GOLDEN_RECORD_ID]["sha256"],
        "environment_sha256": refs[ENVIRONMENT_RECORD_ID]["sha256"],
        "registry_sha256": capture.registry_sha256,
        "recipe_sha256": A_RECIPE_SHA256,
        "rounds": len(capture.record["recordings"]),
        "boundaries": len(capture.context.contexts),
        "screenshots": 10,
    }
    report["effective_settings"] = {
        "status": "derived",
        "tangent_space": capture.settings.tangent_space,
        "workflow": capture.settings.workflow,
        "effective_cm_per_unit": capture.settings.effective_cm_per_unit,
        "provenance_basis": capture.settings.provenance_basis,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        destination = ensure_outside_repository(args.output)
        _require(destination.parent.is_dir(), "F_SETTINGS_OUTPUT")
        with destination.open("xb") as stream:
            try:
                store = locate()
                _require(store is not None, "F_SETTINGS_STORE_UNAVAILABLE")
                assert store is not None
                report = inspect_capture(args.manifest.read_bytes(), store)
            except Exception:
                report = _new_report()
                report["failure"] = {"code": "F_SETTINGS_INPUT_UNAVAILABLE"}
            encoded = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8")
            _require(stream.write(encoded) == len(encoded), "F_SETTINGS_OUTPUT")
            stream.flush()
        print(
            json.dumps(
                {
                    "report_sha256": common.digest(encoded),
                    "rounds": report["capture"].get("rounds", 0),
                    "boundaries": report["capture"].get("boundaries", 0),
                    "screenshots": report["capture"].get("screenshots", 0),
                    "failures": int("failure" in report),
                    "acceptances": 0,
                },
                sort_keys=True,
            )
        )
    except Exception:
        print('{"failures":1,"acceptances":0}')
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

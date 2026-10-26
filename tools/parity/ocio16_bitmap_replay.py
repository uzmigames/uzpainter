"""Shared admission, receipt validation and comparison for authored OCIO bitmap exports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.envelope.ocio import recorded_request_environment_matches
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.recorder.environment import ENVELOPE_FIELDS
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import GOLDEN_RECORD_ID, slug
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.schemas import record_problems
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics import ocio16_bitmap_control as control


@dataclass(frozen=True)
class Candidate:
    source: str
    authored: dict[str, Any]
    spec: dict[str, Any]
    spec_dir: Path
    config: dict[str, Any]
    run_dir: Path
    path: Path
    output_id: str
    step: int


def decoded_exact(left: bytes, right: bytes, report: dict[str, Any] | None = None) -> bool:
    a, b = decode(left), decode(right)
    if report is not None:
        report["decoded_non_finite_candidate"] += int(np.count_nonzero(~np.isfinite(a.values)))
        report["decoded_non_finite_reference"] += int(np.count_nonzero(~np.isfinite(b.values)))
    return (
        a.integer == b.integer
        and a.bits == b.bits
        and a.values.shape == b.values.shape
        and a.values.dtype == b.values.dtype
        and np.array_equal(a.values, b.values, equal_nan=True)
    )


def compare_bytes(data: bytes, expected: bytes, report: dict[str, Any]) -> None:
    report["comparisons"] += 1
    if hashlib.sha256(data).digest() == hashlib.sha256(expected).digest():
        report["encoded_equal"] += 1
        report["pixels_equal"] += 1
    else:
        report["encoded_different"] += 1
        report["pixels_equal" if decoded_exact(data, expected, report) else "pixels_different"] += 1


def require_admitted_refs(store: OracleStore, manifest: dict[str, Any]) -> None:
    build = manifest["software"]["painter"]["build_id"]
    for ref in manifest["private_records"]:
        entry = store.entry(build, manifest["golden_id"], ref["record_id"])
        if entry is None or canonical_json(
            [entry.kind, entry.sha256, entry.size_bytes]
        ) != canonical_json([ref["kind"], ref["sha256"], ref["size_bytes"]]):
            raise ValueError("oracle reference not admitted")


def validate_receipt_context(
    record: dict[str, Any], authored: dict[str, Any], store: OracleStore
) -> None:
    job = probe_job_from_manifest(authored)
    key = record["key"]
    settings = key["project_settings"]
    if (
        key["instruction_sequence_sha256"] != job.instruction_sequence_sha256
        or canonical_json(key["inputs"]) != canonical_json(job.input_hashes())
        or canonical_json(key["painter_build"]) != canonical_json(authored["software"]["painter"])
        or set(settings) != {"create", "colour_management"}
        or canonical_json(settings["create"]) != canonical_json(job.project_settings())
    ):
        raise ValueError("oracle receipt recipe differs")
    colour = settings["colour_management"]
    if (
        set(colour) != {"mode", "OCIO", "PAINTER_ACE_CONFIG"}
        or colour["mode"] != "ocio"
        or type(colour["OCIO"]) is not str
        or not colour["OCIO"].replace("\\", "/").endswith("resources/ocio/substance/config.ocio")
        or colour["PAINTER_ACE_CONFIG"] is not None
        or canonical_json(key["effective_defaults"].get("colour_management"))
        != canonical_json(colour)
    ):
        raise ValueError("oracle receipt colour context differs")
    environment = record.get("environment")
    envelope = current_envelope()
    if (
        type(environment) is not dict
        or environment.get("basis") != "recorded"
        or any(environment.get(field) in (None, "", "unknown") for field in ENVELOPE_FIELDS)
        or canonical_json(environment["painter_build"]) != canonical_json(envelope["painter_build"])
        or not recorded_request_environment_matches(environment, authored, envelope, store)
    ):
        raise ValueError("oracle receipt envelope differs")


def compare_produced(produced: list[tuple[Candidate, bytes]], report: dict[str, Any]) -> None:
    """Compare completed authored candidates against the same admitted export identities."""
    # Reference bytes cannot reach setup or any native invocation.
    report["stage"] = "oracle_comparison"
    store = locate()
    if store is None:
        raise ValueError("oracle unavailable")
    base = manifest_root(current_envelope()) / "tier0/api-probes"
    loaded: dict[str, tuple[dict[str, Any], list[dict[str, Any]], str]] = {}
    for candidate, data in produced:
        if candidate.source not in loaded:
            manifest = json.loads(
                (base / f"{control.request_name(candidate.source)}.json").read_text()
            )
            if any(
                canonical_json(manifest[k]) != canonical_json(candidate.authored[k])
                for k in (
                    "golden_id",
                    "inputs",
                    "instruction_sequence",
                    "applied_settings",
                    "software",
                )
            ):
                raise ValueError("oracle authored context differs")
            refs = manifest["private_records"]
            records = [r for r in refs if r["kind"] == "private_oracle_record"]
            if len(records) != 1 or not records[0]["record_id"].endswith(GOLDEN_RECORD_ID):
                raise ValueError("oracle record identity")
            require_admitted_refs(store, manifest)
            raw = load_oracle(store, records[0])
            if raw is None:
                raise ValueError("oracle record unavailable")
            record = json.loads(raw)
            if record_problems(record) or record["golden_id"] != manifest["golden_id"]:
                raise ValueError("oracle record schema")
            validate_receipt_context(record, candidate.authored, store)
            if len(record["recordings"]) != 2 or [r["condition"] for r in record["recordings"]] != [
                "same_session",
                "after_save_reopen",
            ]:
                raise ValueError("oracle recording conditions")
            loaded[candidate.source] = (
                record,
                refs,
                records[0]["record_id"][: -len(GOLDEN_RECORD_ID)],
            )
        record, refs, prefix = loaded[candidate.source]
        for recording in record["recordings"]:
            matches = [
                o
                for o in recording["outputs"]
                if o["kind"] == "exported_map" and o["output_id"] == candidate.output_id
            ]
            if len(matches) != 1:
                raise ValueError("oracle output identity")
            output = matches[0]
            parameters = candidate.config["exportParameters"][0]["parameters"]
            settings = output["export_settings"]
            if (
                any(
                    canonical_json(settings.get(k)) != canonical_json(v)
                    for k, v in parameters.items()
                )
                or canonical_json(settings.get("step")) != canonical_json(candidate.step)
                or settings.get("map_type") != "documentMap"
                or settings.get("map_channels") != "RGB"
                or output["texture_set"] != "uzp_plane"
            ):
                raise ValueError("oracle export settings differ")
            key = prefix + slug(recording["recording_id"]) + "-" + slug(candidate.output_id)
            references = [r for r in refs if r["record_id"] == key]
            if len(references) != 1 or any(
                references[0][k] != output["blob"][k] for k in ("sha256", "size_bytes")
            ):
                raise ValueError("oracle reference mismatch")
            expected = load_oracle(store, references[0])
            if expected is None:
                raise ValueError("oracle output unavailable")
            compare_bytes(data, expected, report)
    report["stage"] = "complete"
    report["status"] = "equal" if report["pixels_different"] == 0 else "different"


def new_report() -> dict[str, Any]:
    return {
        "schema": "ocio16-native-baselines/1",
        "status": "incomplete",
        "stage": "setup",
        "attempted": 0,
        "candidates": 0,
        "comparisons": 0,
        "encoded_equal": 0,
        "encoded_different": 0,
        "pixels_equal": 0,
        "pixels_different": 0,
        "decoded_non_finite_candidate": 0,
        "decoded_non_finite_reference": 0,
    }

"""Inspect admitted F receipts offline; observable context never authenticates missing settings.

Store admission and source digests establish integrity/provenance, not PID or runtime attestation.
Reports and failure diagnostics stay private and write-once. No capture, import or acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import traceback
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from tools.parity.envelope.ocio import recorded_request_environment_matches
from tools.parity.envelope.registry import envelope, registry_path, registry_problems
from tools.parity.filter_context_contract import (
    A_RECIPE_SHA256,
    MISSING_SETTINGS,
    ContextRefused,
    require_effective_settings,
    typed,
)
from tools.parity.ocio16_bitmap_replay import require_admitted_refs
from tools.parity.recorder.environment import (
    ENVIRONMENT_KIND,
    ENVIRONMENT_RECORD_ID,
    colour_configuration_sha256,
    recorder_version,
)
from tools.parity.recorder.filter_context_run import f_evidence_from_record
from tools.parity.recorder.output import GOLDEN_RECORD_ID, ensure_outside_repository
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.schemas import Schema, environment_problems, record_problems, validation_errors
from tools.parity.store.store import OracleStore, Status, load_oracle, locate
from tools.parity.tier0_semantics import filter_context_control as control

SCHEMA = "uzpainter/filter-context-validation/1"
LEGACY = {"mode": "legacy", "OCIO": None, "PAINTER_ACE_CONFIG": None}
SETTINGS_BLOCK = "F_EFFECTIVE_SETTINGS_UNVERIFIED"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def floating(token: str) -> float:
        number = float(token)
        require(
            math.isfinite(number) and (number != 0 or Decimal(token).is_zero()),
            "unrepresentable JSON number",
        )
        return number

    result = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_float=floating)
    typed(result)
    require(type(result) is dict, "JSON root must be an object")
    return cast(dict[str, Any], result)


def equal(actual: Any, expected: Any, reason: str) -> None:
    require(typed(actual) == typed(expected), reason)


def registry_snapshot() -> tuple[bytes, dict[str, Any]]:
    raw = registry_path().read_bytes()
    document = decode(raw)
    require(not registry_problems(document), "envelope registry schema or identity")
    return raw, envelope(document, document["current"])


def manifest_request(manifest: dict[str, Any]) -> dict[str, Any]:
    require(not validation_errors(manifest, Schema.GOLDEN_PUBLIC), "public manifest schema")
    authored = control.request()

    def invariant(document: dict[str, Any]) -> dict[str, Any]:
        return {
            **{k: v for k, v in document.items() if k not in ("private_records", "software")},
            "software": {k: v for k, v in document["software"].items() if k != "painter"},
        }

    equal(invariant(manifest), invariant(authored), "authored F request differs")
    require(
        digest(typed(manifest["instruction_sequence"])) == A_RECIPE_SHA256,
        "recipe A pin differs",
    )
    refs = manifest["private_records"]
    require(
        len(refs) == 2
        and {(r["record_id"], r["kind"]) for r in refs}
        == {
            (GOLDEN_RECORD_ID, "private_oracle_record"),
            (ENVIRONMENT_RECORD_ID, ENVIRONMENT_KIND),
        },
        "F reference inventory differs",
    )
    return authored


def receipt(
    manifest: dict[str, Any], authored: dict[str, Any], store: OracleStore
) -> tuple[dict[str, Any], bytes, bytes, bytes, dict[str, Any]]:
    registry_raw, current = registry_snapshot()
    # Admission joins precede reads, so a caller-provided hash alone cannot select evidence.
    require_admitted_refs(store, manifest)
    refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
    blobs: dict[str, bytes] = {}
    for identity in (GOLDEN_RECORD_ID, ENVIRONMENT_RECORD_ID):
        data = load_oracle(store, refs[identity])
        require(data is not None, "admitted blob unavailable")
        assert data is not None
        equal(
            [digest(data), len(data)],
            [refs[identity]["sha256"], refs[identity]["size_bytes"]],
            "receipt hash or size differs",
        )
        blobs[identity] = data
    record = decode(blobs[GOLDEN_RECORD_ID])
    environment = decode(blobs[ENVIRONMENT_RECORD_ID])
    require(not record_problems(record), "private record schema")
    require(not environment_problems(environment), "environment schema")
    equal(record.get("environment"), environment, "environment blob differs from record")
    equal([record["golden_id"], record["tier"]], [control.GOLDEN_ID, "0"], "record identity")
    build = manifest["software"]["painter"]
    require(
        build["build_id"] == current["painter_build"]
        and build["version"] == build["build_id"].split("+js-api.")[0]
        and build["product"] == authored["software"]["painter"]["product"],
        "Painter declaration differs from current registry",
    )
    require(
        recorded_request_environment_matches(environment, manifest, current, store),
        "recorded environment differs from current envelope",
    )
    require(environment["recorder_version"] == recorder_version(), "recorder source pin differs")
    require(
        environment["colour_configuration_sha256"] == colour_configuration_sha256(LEGACY),
        "environment is not the declared Legacy configuration",
    )
    job = probe_job_from_manifest(authored)
    key = record["key"]
    equal(key["painter_build"], build, "record Painter build differs")
    equal(key["inputs"], job.input_hashes(), "record input pins differ")
    equal(key["instruction_sequence_sha256"], job.instruction_sequence_sha256, "recipe key differs")
    equal(
        key["project_settings"],
        {"create": job.project_settings(), "colour_management": LEGACY},
        "authored settings or Legacy readback differs",
    )
    equal(key["effective_defaults"].get("colour_management"), LEGACY, "Legacy defaults differ")
    equal(
        [key["resource_hashes"], key["bake_backend"], key["render_state"]],
        [[], None, None],
        "unexpected resource or backend context",
    )
    # probe_job_from_manifest rehashes the public authored files. Rehash admitted input bytes too.
    for item in authored["inputs"]:
        source = job.inputs[item["input_id"]]
        resolution = store.resolve(item["input_id"], item["sha256"], source.stat().st_size)
        require(resolution.status is Status.AVAILABLE, "authored input unavailable in store")
    rounds = record["recordings"]
    equal(
        [[r["recording_id"], r["condition"]] for r in rounds],
        [["r1", "same_session"], ["r2", "after_save_reopen"]],
        "F recording identities differ",
    )
    require(rounds[0]["session_id"] == rounds[1]["session_id"], "recording sessions differ")
    return record, blobs[GOLDEN_RECORD_ID], blobs[ENVIRONMENT_RECORD_ID], registry_raw, current


def new_report() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "capture": {"status": "not_checked"},
        "observable_f_domain": {"status": "not_checked", "boundaries": 0, "context_readbacks": 0},
        "effective_settings": {"status": "unverified", "missing": list(MISSING_SETTINGS)},
        "acceptance": {"status": "blocked", "code": SETTINGS_BLOCK},
    }


def failure(report: dict[str, Any], stage: str, error: Exception) -> None:
    diagnostic = {
        "stage": stage,
        "type": type(error).__name__,
        "message": str(error),
        "traceback": traceback.format_exc(),
    }
    if "failure" in report:
        report.setdefault("additional_failures", []).append(diagnostic)
    else:
        report["failure"] = diagnostic
    field = "observable_f_domain" if stage == "observable_f_domain" else "capture"
    report[field]["status"] = "refused"


def inspect_capture(manifest_bytes: bytes, store: OracleStore) -> dict[str, Any]:
    report = new_report()
    stage = "manifest"
    snapshot: tuple[bytes, dict[str, Any]] | None = None
    try:
        manifest = decode(manifest_bytes)
        authored = manifest_request(manifest)
        stage = "receipt"
        record, raw, environment, registry_raw, current = receipt(manifest, authored, store)
        snapshot = registry_raw, current
        report["capture"] = {
            "status": "validated",
            "basis": "admitted_receipt_integrity_not_runtime_attestation",
            "manifest_sha256": digest(manifest_bytes),
            "record_sha256": digest(raw),
            "environment_sha256": digest(environment),
            "recipe_sha256": A_RECIPE_SHA256,
            "registry_sha256": digest(registry_raw),
            "rounds": len(record["recordings"]),
            "readbacks": sum(len(r["outputs"]) for r in record["recordings"]),
        }
        stage = "observable_f_domain"
        evidence = f_evidence_from_record(record, authored["instruction_sequence"])
        report["observable_f_domain"] = {
            "status": "validated",
            "boundaries": len(evidence.contexts),
            "context_readbacks": sum(len(frame["outputs"]) for frame in evidence.contexts),
        }
        try:
            require_effective_settings(evidence)
        except ContextRefused as error:
            require(str(error).startswith(SETTINGS_BLOCK + ":"), "unexpected settings refusal")
        else:
            raise ValueError("protocol /1 must not authenticate effective settings")
    except Exception as error:
        failure(report, stage, error)
    finally:
        if snapshot is not None:
            try:
                after_raw, after_current = registry_snapshot()
                require(after_raw == snapshot[0], "envelope registry changed during validation")
                equal(after_current, snapshot[1], "current envelope changed during validation")
            except Exception as error:
                failure(report, "receipt_registry", error)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        destination = ensure_outside_repository(args.output)
        require(destination.parent.is_dir(), "private output parent missing")
        # Reserve the one output before reading evidence; existing reports are never overwritten.
        with destination.open("xb") as stream:
            try:
                store = locate()
                require(store is not None, "store unavailable")
                assert store is not None
                report = inspect_capture(args.manifest.read_bytes(), store)
            except Exception as error:
                report = new_report()
                failure(report, "input", error)
            encoded = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8")
            require(stream.write(encoded) == len(encoded), "short report write")
            stream.flush()
        print(
            json.dumps(
                {
                    "report_sha256": digest(encoded),
                    "rounds": report["capture"].get("rounds", 0),
                    "boundaries": report["observable_f_domain"]["boundaries"],
                    "failures": int("failure" in report)
                    + len(report.get("additional_failures", [])),
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

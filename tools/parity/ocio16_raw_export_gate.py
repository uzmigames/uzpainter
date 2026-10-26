"""Authorize one authored Raw export collection from freshly validated V3 capabilities.

This gate reads admitted capability evidence only. It never launches Painter, exports,
admits records or establishes numerical identity. Its audit is not a reusable permit:
call authorize_collection again immediately before every collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.parity import ocio16_raw_readout_admission as capability
from tools.parity.envelope.ocio import recorded_request_environment_matches
from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder.environment import ENVELOPE_FIELDS, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def digest(document: Any) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def authorize_collection(
    export_request: dict[str, Any],
    state: str,
    capability_manifests: Sequence[dict[str, Any]],
    store: OracleStore,
) -> dict[str, Any]:
    """Revalidate exactly three admitted states; return an audit for this request only."""
    capability.require(state in control.STATES, "unknown export state")
    capability.require(len(capability_manifests) == 3, "three capabilities required")
    # Snapshot caller-owned dictionaries; no previous audit/report is accepted as evidence.
    requested = json.loads(canonical_json(export_request))
    manifests = json.loads(canonical_json(list(capability_manifests)))
    envelope = current_envelope()
    authored = control.request(state, exports=True)
    capability.equal(requested, authored, "authored export request differs")
    expected = {control.request(s)["golden_id"]: s for s in control.STATES}
    by_state: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        capability.require(type(manifest) is dict, "capability manifest required")
        identity = manifest.get("golden_id")
        capability.require(type(identity) is str and identity in expected, "V3 capability required")
        found_state = expected[identity]
        capability.require(found_state not in by_state, "duplicate capability state")
        capability.validate_manifest(manifest, found_state)
        by_state[found_state] = manifest
    capability.require(set(by_state) == set(control.STATES), "capability state coverage")
    prerequisites = []
    common_environment: dict[str, Any] | None = None
    for found_state in control.STATES:
        manifest = by_state[found_state]
        validation = capability.inspect_capability(manifest, found_state, store)
        ref = next(
            r for r in manifest["private_records"] if r["record_id"] == ENVIRONMENT_RECORD_ID
        )
        raw = load_oracle(store, ref)
        capability.require(raw is not None, "capability environment unavailable")
        assert raw is not None
        capability.equal(
            [hashlib.sha256(raw).hexdigest(), len(raw)],
            [ref["sha256"], ref["size_bytes"]],
            "capability environment receipt differs",
        )
        environment = json.loads(raw)
        fields = {field: environment[field] for field in ENVELOPE_FIELDS}
        if common_environment is None:
            common_environment = fields
        capability.equal(fields, common_environment, "capability envelopes differ")
        capability.require(
            recorded_request_environment_matches(environment, authored, envelope, store),
            "export request envelope differs",
        )
        prerequisites.append(
            {
                "state": found_state,
                "golden_id": manifest["golden_id"],
                "manifest_canonical_sha256": digest(manifest),
                "request_canonical_sha256": validation["request_sha256"],
                "record_sha256": validation["record_sha256"],
                "private_records": sorted(
                    manifest["private_records"], key=lambda r: r["record_id"]
                ),
            }
        )
    capability.equal(current_envelope(), envelope, "current envelope changed during gate")
    return {
        "schema": "uzpainter/raw-export-collection-gate/1",
        "status": "authorized",
        "collection_authorized": True,
        "scope": "one_authored_export_request",
        "state": state,
        "golden_id": authored["golden_id"],
        "request_canonical_sha256": digest(authored),
        "envelope_id": envelope["envelope_id"],
        "registry_entry_canonical_sha256": digest(envelope),
        "recorded_envelope_sha256": digest(common_environment),
        "prerequisites": prerequisites,
        "readout_identity": "not_established",
        "parity": "not_established",
        "export_bytes_validated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", choices=control.STATES, required=True)
    parser.add_argument("--capability-manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = None
    try:
        destination = ensure_outside_repository(args.output)
        capability.require(
            destination.parent.is_dir() and not destination.exists(), "private output destination"
        )
        store = locate()
        capability.require(store is not None, "store unavailable")
        assert store is not None
        report = authorize_collection(
            json.loads(args.manifest.read_bytes()),
            args.state,
            [json.loads(path.read_bytes()) for path in args.capability_manifest],
            store,
        )
        encoded = canonical_json(report) + b"\n"
        with destination.open("xb") as stream:
            stream.write(encoded)
        print(
            json.dumps(
                {"status": "authorized", "report_sha256": hashlib.sha256(encoded).hexdigest()}
            )
        )
        return 0
    except Exception:
        if destination is not None and destination.parent.is_dir():
            try:
                with destination.with_name(destination.stem + "-failure.json").open(
                    "x", encoding="utf-8"
                ) as stream:
                    json.dump({"status": "refused", "traceback": traceback.format_exc()}, stream)
            except Exception:
                pass
        print('{"status":"refused"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

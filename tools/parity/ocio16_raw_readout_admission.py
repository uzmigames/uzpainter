"""Validate admitted capability-only Raw controls; never captures or compares pixels.

The generated public recipe is authoritative. Store admission, receipt context,
the exact two-round lifecycle, import identity and closed state/topology all
precede approval. Approval covers only the observed capability in this context;
it does not assert identity readout, a Color channel flag, or export conformity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

from tools.parity import ocio16_bitmap_replay as replay
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.environment import ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import GOLDEN_RECORD_ID, ensure_outside_repository
from tools.parity.recorder.probes import GET_NODE_BY_UID, ProbeStep, probe_job_from_manifest
from tools.parity.schemas import Schema, environment_problems, record_problems, validation_errors
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def equal(actual: Any, expected: Any, message: str) -> None:
    require(canonical_json(actual) == canonical_json(expected), message)


def output(recording: dict[str, Any], identity: str) -> dict[str, Any]:
    found = [item for item in recording["outputs"] if item.get("output_id") == identity]
    require(len(found) == 1, "output identity")
    return dict(found[0])


def step_output(recording: dict[str, Any], step: ProbeStep) -> dict[str, Any]:
    found = output(recording, step.output_id)
    require(found.get("kind") == "api_readback" and "raised" not in found, "step outcome")
    equal([found.get("call"), found.get("args")], [step.call, step.args], "step context")
    require("value" in found, "missing step value")
    return found


def validate_manifest(manifest: dict[str, Any], state: str) -> dict[str, Any]:
    authored = control.request(state)
    require(not validation_errors(manifest, Schema.GOLDEN_PUBLIC), "public schema")
    equal(
        {k: v for k, v in manifest.items() if k != "private_records"},
        {k: v for k, v in authored.items() if k != "private_records"},
        "authored capability request differs",
    )
    refs = manifest["private_records"]
    require(
        len(refs) == 2
        and {(ref["kind"], ref["record_id"]) for ref in refs}
        == {
            ("private_oracle_record", GOLDEN_RECORD_ID),
            (ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID),
        },
        "capability references",
    )
    return authored


def validate_record_receipt(
    manifest: dict[str, Any],
    authored: dict[str, Any],
    record_bytes: bytes,
    store: OracleStore,
    *,
    environment_bytes: bytes,
) -> dict[str, Any]:
    """Shared admitted receipt joins; callers first close their public reference inventory."""
    refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
    replay.require_admitted_refs(store, manifest)
    for identity, data in (
        (GOLDEN_RECORD_ID, record_bytes),
        (ENVIRONMENT_RECORD_ID, environment_bytes),
    ):
        equal(
            [refs[identity]["sha256"], refs[identity]["size_bytes"]],
            [hashlib.sha256(data).hexdigest(), len(data)],
            "record receipt differs",
        )
    record: dict[str, Any] = json.loads(record_bytes)
    require(not record_problems(record), "private record schema")
    environment = json.loads(environment_bytes)
    require(not environment_problems(environment), "environment record schema")
    equal(environment, record.get("environment"), "environment record differs")
    equal([record["golden_id"], record["tier"]], [authored["golden_id"], "0"], "record identity")
    replay.validate_receipt_context(record, authored, store)
    return record


def validate_rounds(
    record: dict[str, Any],
    authored: dict[str, Any],
    *,
    export_output_ids: tuple[str, str] | None = None,
) -> None:
    """Shared setup, state, resource and lifecycle checks with a closed per-round inventory."""
    job = probe_job_from_manifest(authored)
    require(not job.events and not job.observed, "Raw observation domain")
    require(len(job.exports) == int(export_output_ids is not None), "Raw export domain")
    equal(record["key"]["resource_hashes"], [], "unexpected resource hashes")
    require(
        record["key"]["bake_backend"] is None and record["key"]["render_state"] is None,
        "unexpected backend state",
    )
    rounds = record["recordings"]
    require(len(rounds) == 2, "round count")
    equal(
        [[r["recording_id"], r["condition"]] for r in rounds],
        [["r1", "same_session"], ["r2", "after_save_reopen"]],
        "round conditions",
    )
    require(
        type(rounds[0]["session_id"]) is str and bool(rounds[0]["session_id"]), "session identity"
    )
    equal(rounds[0]["session_id"], rounds[1]["session_id"], "same process lifecycle")
    insert = [s for s in job.state_steps if s.call == ps.INSERT_FILL]
    imports = [s for s in job.state_steps if s.call == ps.IMPORT_RESOURCE]
    require(len(insert) == len(imports) == 1, "setup identity")
    node = insert[0].step
    for step in job.state_steps:
        step_output(rounds[0], step)
    cleanup = [s for s in job.state_steps if s.args.get("initial_root") is True]
    require(len(cleanup) == 1 and cleanup[0].step == 2, "owned cleanup step")
    receipt = step_output(rounds[0], cleanup[0])["value"]
    require(
        type(receipt) is dict
        and set(receipt)
        == {"created_project_uuid", "current_project_uuid", "before", "after_root_count"},
        "cleanup receipt fields",
    )
    require(
        type(receipt["created_project_uuid"]) is str and bool(receipt["created_project_uuid"]),
        "owned project identity",
    )
    equal(
        receipt["created_project_uuid"], receipt["current_project_uuid"], "cleanup project identity"
    )
    before = receipt["before"]
    require(
        type(before) is dict
        and set(before) == {"uid", "node_type"}
        and type(before["uid"]) is int
        and before["uid"] > 0
        and before["node_type"] == "PaintLayer",
        "cleanup root identity",
    )
    equal(receipt["after_root_count"], 0, "cleanup final roots")
    imported = step_output(rounds[0], imports[0])["value"]
    require(type(imported) is dict and set(imported) == {"resource"}, "import receipt")
    identity = imported["resource"]
    require(
        type(identity) is dict and set(identity) == {"context", "name", "version"},
        "import identity",
    )
    for index, recording in enumerate(rounds):
        required = {"template/texture-sets", f"identity/s{node}"}
        required.update(s.output_id for s in job.probe_steps)
        if export_output_ids is not None:
            required.add(export_output_ids[index])
        if index == 0:
            required.update(s.output_id for s in job.state_steps)
        else:
            required.add("identity/reopen")
        identities = [o.get("output_id") for o in recording["outputs"]]
        require(
            len(identities) == len(set(identities)) and set(identities) == required,
            "closed output inventory",
        )
        for step in job.probe_steps:
            step_output(recording, step)
        node_identity = output(recording, f"identity/s{node}")
        equal(
            node_identity,
            {
                "output_id": f"identity/s{node}",
                "kind": "api_readback",
                "call": GET_NODE_BY_UID,
                "args": {"node_step": node},
                "value": {
                    "present": True,
                    "uid_same_as_recorded": True,
                    "uid_resolves_to_node": True,
                },
            },
            "node lifecycle",
        )
        control.validate_observed_state(
            recording, authored, identity, receipt["created_project_uuid"]
        )
    rebind = output(rounds[1], "identity/reopen")
    equal(
        {k: v for k, v in rebind.items() if k != "value"},
        {
            "output_id": "identity/reopen",
            "kind": "api_readback",
            "call": GET_NODE_BY_UID,
            "args": {},
        },
        "reopen context",
    )
    require(
        type(rebind.get("value")) is dict and set(rebind["value"]) == {"found_by"}, "reopen value"
    )
    found_by = rebind["value"]["found_by"]
    require(
        type(found_by) is dict
        and set(found_by) == {str(node)}
        and found_by[str(node)] in {"uid", "location"},
        "reopen identity",
    )


def validate_capability(
    manifest: dict[str, Any],
    record_bytes: bytes,
    state: str,
    store: OracleStore,
    *,
    environment_bytes: bytes,
) -> dict[str, Any]:
    authored = validate_manifest(manifest, state)
    record = validate_record_receipt(
        manifest, authored, record_bytes, store, environment_bytes=environment_bytes
    )
    validate_rounds(record, authored)
    rounds = record["recordings"]
    return {
        "schema": "uzpainter/ocio16-raw-capability-validation/1",
        "status": "validated",
        "state": state,
        "rounds": 2,
        "readbacks": sum(len(r["outputs"]) for r in rounds),
        "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
        "request_sha256": hashlib.sha256(canonical_json(authored)).hexdigest(),
        "color_channel_flag": "unobserved",
        "readout_identity": "not_established",
        "exports_authorized": False,
    }


def inspect_capability(manifest: dict[str, Any], state: str, store: OracleStore) -> dict[str, Any]:
    # Admission is checked before any record bytes are requested from the store.
    validate_manifest(manifest, state)
    replay.require_admitted_refs(store, manifest)
    refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
    raw = load_oracle(store, refs[GOLDEN_RECORD_ID])
    environment = load_oracle(store, refs[ENVIRONMENT_RECORD_ID])
    require(raw is not None and environment is not None, "record unavailable")
    assert raw is not None and environment is not None
    return validate_capability(manifest, raw, state, store, environment_bytes=environment)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", choices=control.STATES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = None
    try:
        destination = ensure_outside_repository(args.output)
        require(
            destination.parent.is_dir() and not destination.exists(), "private output destination"
        )
        store = locate()
        require(store is not None, "store unavailable")
        assert store is not None
        report = inspect_capability(json.loads(args.manifest.read_bytes()), args.state, store)
        encoded = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
        with destination.open("xb") as stream:
            stream.write(encoded)
        print(
            json.dumps(
                {
                    "status": "validated",
                    "rounds": 2,
                    "report_sha256": hashlib.sha256(encoded).hexdigest(),
                }
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

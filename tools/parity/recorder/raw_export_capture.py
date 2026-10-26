"""Collect one authored Raw export in an owned Painter after a fresh three-capability gate.

Runtime requires coordinator release. No admission or pixel/identity validation occurs here;
the two exported maps and all diagnostics stay private. Capability collection has a separate CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity import ocio16_raw_export_gate as gate
from tools.parity.ocio16_raw_readout_admission import equal, require
from tools.parity.preserve_diagnostic_evidence import file_fingerprint, private_path
from tools.parity.recorder import raw_capability_capture as runtime
from tools.parity.recorder.environment import ENVIRONMENT_KIND, ENVIRONMENT_RECORD_ID
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import GOLDEN_RECORD_ID, private_record_refs
from tools.parity.recorder.probes import ProbeJob, probe_job_from_manifest
from tools.parity.recorder.texture import output_safe
from tools.parity.schemas import (
    REPO_ROOT,
    Schema,
    environment_problems,
    record_problems,
    validation_errors,
)
from tools.parity.store.store import locate
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


@dataclass(frozen=True)
class Request(runtime.Request):
    capability_manifests: tuple[Path, ...]


def prepared(request: runtime.Request) -> ProbeJob:
    require(request.state in control.STATES, "unknown Raw state")
    authored = control.request(request.state, exports=True)
    manifest = json.loads(request.manifest.read_bytes())
    equal(manifest, authored, "authored export request differs")
    job = probe_job_from_manifest(manifest)
    require(
        len(job.exports) == 1 and not job.events and not job.lifecycle, "one export recipe required"
    )
    require(request.painter_exe.is_file(), "Painter executable unavailable")
    return job


def validate_ready(job: ProbeJob, run: Path, manifest: dict[str, Any]) -> None:
    """Check the READY receipt inventory and bytes; pixel conformity is a later gate."""
    require(not validation_errors(manifest, Schema.GOLDEN_PUBLIC), "export public schema")
    equal(
        {k: v for k, v in manifest.items() if k != "private_records"},
        {k: v for k, v in job.manifest.items() if k != "private_records"},
        "export recipe differs",
    )
    refs = manifest["private_records"]
    require(
        len(refs) == 4 and len({r["record_id"] for r in refs}) == 4,
        "four export references required",
    )
    raw = (run / "record.json").read_bytes()
    record = json.loads(raw)
    require(not record_problems(record), "export private schema")
    equal(
        [record["golden_id"], record["tier"]],
        [job.manifest["golden_id"], "0"],
        "export record identity",
    )
    equal(
        record["key"]["instruction_sequence_sha256"],
        job.instruction_sequence_sha256,
        "export instruction receipt",
    )
    equal(record["key"]["inputs"], job.input_hashes(), "export input receipt")
    rounds = record["recordings"]
    equal(
        [[r["recording_id"], r["condition"]] for r in rounds],
        [["r1", "same_session"], ["r2", "after_save_reopen"]],
        "export round inventory",
    )
    for recording in rounds:
        outputs = recording["outputs"]
        require(len({o["output_id"] for o in outputs}) == len(outputs), "duplicate export output")
        maps = [o for o in outputs if o["kind"] == "exported_map"]
        require(
            len(maps) == 1 and sum("blob" in o for o in outputs) == 1, "one exported map per round"
        )
        require(maps[0]["map"] == "user0", "exported map differs")
        templates = [
            o
            for o in outputs
            if o["output_id"] == "template/texture-sets" and o["kind"] == "template_capture"
        ]
        require(len(templates) == 1, "export template inventory")
        sets = templates[0]["values"]["texture_sets"]
        require(
            set(sets) == {"uzp_plane"} and len(sets["uzp_plane"]["stacks"]) == 1,
            "export stack inventory",
        )
        stack = next(iter(sets["uzp_plane"]["stacks"]))
        expected_id = "/".join(
            [
                "uzp_plane",
                *([output_safe(stack)] if stack else []),
                "user0",
                f"step{job.exports[0].step}",
            ]
        )
        equal(
            [maps[0]["output_id"], maps[0]["texture_set"]],
            [expected_id, "uzp_plane" + ("/" + stack if stack else "")],
            "export map inventory",
        )
    blobs: dict[str, int] = {}
    environment_ref = [r for r in refs if r["record_id"] == ENVIRONMENT_RECORD_ID]
    require(
        len(environment_ref) == 1 and environment_ref[0]["kind"] == ENVIRONMENT_KIND,
        "environment reference",
    )
    for ref in refs:
        path = (
            run / "record.json"
            if ref["record_id"] == GOLDEN_RECORD_ID
            else run / "blobs" / ref["sha256"]
        )
        require(
            not path.is_symlink() and path.resolve().is_relative_to(run.resolve()),
            "export blob location",
        )
        equal(
            list(file_fingerprint(path)), [ref["sha256"], ref["size_bytes"]], "export blob receipt"
        )
        if ref["kind"] == "exported_map":
            blobs[ref["sha256"]] = ref["size_bytes"]
    environment_data = (run / "blobs" / environment_ref[0]["sha256"]).read_bytes()
    environment = json.loads(environment_data)
    require(not environment_problems(environment), "export environment schema")
    equal(environment, record.get("environment"), "export environment receipt")
    expected = private_record_refs(raw, record, blobs) + environment_ref
    equal(
        sorted(refs, key=lambda r: r["record_id"]),
        sorted(expected, key=lambda r: r["record_id"]),
        "export references differ",
    )


class ExportPolicy(runtime.CapabilityPolicy):
    schema = "uzpainter/raw-export-capture/1"
    owner = "Astra/uzpainter-raw-export"
    task = "Codex/Raw: one gated authored export capture"
    exports = 2

    def __init__(self, capability_manifests: tuple[Path, ...]) -> None:
        self.capability_manifests = capability_manifests

    def prepare(self, request: runtime.Request) -> ProbeJob:
        require(len(self.capability_manifests) == 3, "three capability manifests required")
        require(
            all(path.is_file() for path in self.capability_manifests),
            "capability manifest unavailable",
        )
        return prepared(request)

    def authorize(
        self, request: runtime.Request, job: ProbeJob, evidence: runtime.Evidence
    ) -> dict[str, Any]:
        store = locate()
        require(store is not None, "store unavailable")
        assert store is not None
        audit = gate.authorize_collection(
            job.manifest,
            request.state,
            [json.loads(path.read_bytes()) for path in self.capability_manifests],
            store,
        )
        path = private_path(
            request.output_prefix.with_name(request.output_prefix.name + ".authorization.json"),
            REPO_ROOT,
        )
        data = canonical_json(audit) + b"\n"
        with path.open("xb") as stream:
            require(stream.write(data) == len(data), "short authorization audit write")
        sha = hashlib.sha256(data).hexdigest()
        evidence.log("collection_authorized", authorization_sha256=sha)
        return {
            "authorization_path": str(path),
            "authorization_sha256": sha,
            "readout_identity": "not_established",
            "parity": "not_established",
            "export_bytes_validated": False,
        }

    def ready(self, job: ProbeJob, run: Path, manifest: dict[str, Any]) -> None:
        validate_ready(job, run, manifest)


def capture(request: Request) -> dict[str, Any]:
    return runtime.run_owned_capture(request, ExportPolicy(request.capability_manifests))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=control.STATES, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--painter-exe", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--capability-manifest", type=Path, action="append", required=True)
    args = vars(parser.parse_args())
    args["capability_manifests"] = tuple(args.pop("capability_manifest"))
    try:
        result = capture(Request(**args))
    except Exception:
        result = {"status": "refused"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())

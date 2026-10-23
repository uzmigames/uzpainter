"""R-131 state contract: bind each comparison to its intended texture set."""

import hashlib
import json

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import job_from_manifest
from tools.parity.recorder.texture import reopen_count
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics.corpus import FIXTURES
from tools.parity.tier0_semantics.recording_requests import (
    ADMITTED,
    ao_mixed_grid_probe,
    ao_mixed_stability_probes,
    request_manifest,
)


def test_ao_mixed_request_pins_operand_state_before_export() -> None:
    steps = ao_mixed_grid_probe().sequence.steps
    assert steps[0]["args"]["default_texture_resolution"] == 256
    channels = [s["args"] for s in steps if s["call"] == ps.ADD_CHANNEL]
    assert channels == [{"channel": "AO", "format": "L16"}]
    resources = {s["args"]["input"]: s["step"] for s in steps if s["call"] == ps.IMPORT_RESOURCE}
    mesh_maps = [s["args"] for s in steps if s["call"] == ps.SET_MESH_MAP]
    assert mesh_maps == [{"usage": "AO", "resource_step": resources["grey-a"]}]
    fills = [s for s in steps if s["call"] == ps.INSERT_FILL]
    assert [s["args"]["texture_set"] for s in fills] == ["s0", "s1", "s2", "s3"]
    for fill, (filtering, opacity) in zip(
        fills,
        [("Nearest", 0.5), ("Nearest", 0.75), ("Nearest", 1.0), ("BilinearHQ", 0.5)],
        strict=True,
    ):
        edits = {
            s["call"]: {k: v for k, v in s["args"].items() if k != "node_step"}
            for s in steps
            if s["args"].get("node_step") == fill["step"]
        }
        assert edits == {
            ps.SET_ACTIVE_CHANNELS: {"channels": ["AO"]},
            ps.SET_SOURCE: {"channel": "AO", "resource_step": resources["grey-b"]},
            ps.SET_PROJECTION: {
                "filtering_mode": filtering,
                "uv_wrapping_mode": "RepeatNone",
                "scale_mode": "Factors",
                "scale": [1.0, 1.0],
                "rotation": 0.0,
                "offset": [0.0, 0.0],
            },
            ps.SET_BLENDING_MODE: {"blending_mode": "Normal", "channel": "AO"},
            ps.SET_OPACITY: {"opacity": opacity, "channel": "AO"},
        }


def test_stability_requests_preserve_grid_and_validate_as_jobs() -> None:
    base = ao_mixed_grid_probe()
    floating, reopened = ao_mixed_stability_probes()
    assert reopened.sequence.steps == base.sequence.steps
    assert reopened.name == "ao-mixed-grid-l16-reopen3"
    assert floating.name == "ao-mixed-grid-l32f"
    for original, changed in zip(base.sequence.steps, floating.sequence.steps, strict=True):
        if original["call"] == ps.ADD_CHANNEL:
            assert changed == {**original, "args": {"channel": "AO", "format": "L32F"}}
        else:
            assert changed == original
    for golden, count in ((floating, 1), (reopened, 3)):
        assert golden.name in ADMITTED
        hashes = {
            name: hashlib.sha256((REPO_ROOT / FIXTURES[name][1]).read_bytes()).hexdigest()
            for name in golden.inputs
        }
        manifest = request_manifest(golden, hashes, current_envelope(REPO_ROOT))
        assert not validation_errors(manifest, Schema.GOLDEN_PUBLIC)
        assert manifest["private_records"] == []
        assert reopen_count(job_from_manifest(manifest)) == count
        path = manifest_root(current_envelope(REPO_ROOT), REPO_ROOT) / "tier0" / "semantics"
        admitted = json.loads((path / f"{golden.name}.json").read_text(encoding="utf-8"))
        assert admitted["private_records"]
        assert {**admitted, "private_records": []} == manifest
    assert ao_mixed_grid_probe().sequence.steps == base.sequence.steps
    assert base.settings == []

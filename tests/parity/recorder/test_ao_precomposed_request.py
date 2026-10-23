"""Decision 131: author the same AO operand through two composition paths."""

from __future__ import annotations

import hashlib
import json

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, job_from_manifest
from tools.parity.recorder.texture import reopen_count
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics.recording_requests import (
    ADMITTED,
    ao_mixed_precomposed_probe,
    fixture,
    preserved_request_dir,
    request_manifest,
)

SOURCE_SHA256 = "d5cdfd94bf239cfdb4630c78cf0bb72f5582ebea8bcc7a7a8f7edb4e474c3d84"


def test_precomposed_pairs_pin_sources_opacities_filters_and_exports() -> None:
    golden = ao_mixed_precomposed_probe()
    steps = golden.sequence.steps
    assert steps[0]["args"]["default_texture_resolution"] == 256
    assert [s["args"] for s in steps if s["call"] == ps.ADD_CHANNEL] == [
        {"channel": "AO", "format": "L32F"}
    ]
    resources = {s["args"]["input"]: s["step"] for s in steps if s["call"] == ps.IMPORT_RESOURCE}
    assert [s["args"] for s in steps if s["call"] == ps.SET_MESH_MAP] == [
        {"usage": "AO", "resource_step": resources["grey-a"]}
    ]
    fills = [s for s in steps if s["call"] == ps.INSERT_FILL]
    assert [s["args"]["texture_set"] for s in fills] == ["s0", "s1", "s2", "s3"]
    for node, source, opacity, filtering in zip(
        fills,
        ("grey-b", "ao-precomposed-half", "grey-b", "ao-precomposed-half"),
        (0.5, 1.0, 0.5, 1.0),
        ("Nearest", "Nearest", "BilinearHQ", "BilinearHQ"),
        strict=True,
    ):
        edits = {s["call"]: s["args"] for s in steps if s["args"].get("node_step") == node["step"]}
        assert edits[ps.SET_SOURCE]["resource_step"] == resources[source]
        assert edits[ps.SET_OPACITY]["opacity"] == opacity
        assert edits[ps.SET_BLENDING_MODE]["blending_mode"] == "Normal"
        assert edits[ps.SET_ACTIVE_CHANNELS]["channels"] == ["AO"]
        assert edits[ps.SET_PROJECTION] == {
            "node_step": node["step"],
            "filtering_mode": filtering,
            "uv_wrapping_mode": "RepeatNone",
            "scale_mode": "Factors",
            "scale": [1.0, 1.0],
            "rotation": 0.0,
            "offset": [0.0, 0.0],
        }
    exports = [s["args"] for s in steps if s["call"] == EXPORT]
    assert len(exports) == 4 and exports[0] == exports[1] and exports[2] == exports[3]
    assert [(e["file_format"], e["bit_depth"]) for e in exports] == [
        ("png", 8),
        ("png", 8),
        ("exr", "32f"),
        ("exr", "32f"),
    ]


def test_precomposed_request_hashes_authorship_schema_and_job() -> None:
    golden = ao_mixed_precomposed_probe()
    assert golden.name in ADMITTED
    hashes = {
        name: hashlib.sha256((REPO_ROOT / fixture(name)[1]).read_bytes()).hexdigest()
        for name in golden.inputs
    }
    expected = request_manifest(golden, hashes, current_envelope(REPO_ROOT))
    manifest = json.loads(
        (preserved_request_dir(REPO_ROOT) / f"{golden.name}.json").read_text(encoding="utf-8")
    )
    assert manifest == expected
    admitted_path = manifest_root(current_envelope(REPO_ROOT), REPO_ROOT) / "tier0" / "semantics"
    admitted = json.loads((admitted_path / f"{golden.name}.json").read_text(encoding="utf-8"))
    assert admitted["private_records"]
    assert {**admitted, "private_records": []} == manifest
    assert manifest["private_records"] == []
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    source = next(item for item in manifest["inputs"] if item["input_id"] == "ao-precomposed-half")
    assert source["sha256"] == SOURCE_SHA256
    assert source["provenance"]["origin"] == "uzmigames_authored"
    assert "request_fixtures.py" in source["provenance"]["note"]
    assert reopen_count(job_from_manifest(manifest)) == 1

"""Authored mesh-storage controls: exact inputs and independently checked recorder protocol."""

from __future__ import annotations

import hashlib
import json
import struct

import numpy as np

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.decode import decode
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, job_from_manifest
from tools.parity.recorder.texture import reopen_count
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics import ao_operand_control as control
from tools.parity.tier0_semantics import recording_requests as rr


def test_authored_mesh_and_product_cover_all_pairs_at_float32_precision() -> None:
    def f32(value: float) -> float:
        return float(struct.unpack("<f", struct.pack("<f", value))[0])

    mesh = decode(control.mesh_values())
    product = decode(control.product_values())
    for result in (mesh, product):
        assert result.bits == 32 and not result.integer
        assert result.values.shape == (256, 256, 1)
    for y in range(256):
        channel = f32(f32(f32(y / 255) - 1) * 0.5 + 1)
        for x in range(256):
            expected_mesh = f32(x / 255)
            assert mesh.values[y, x, 0] == expected_mesh
            assert product.values[y, x, 0] == f32(expected_mesh * channel)
    generate = rr.fixture("ao-precomposed-half-y")[2]
    assert generate is not None
    original = decode(generate()).values[..., 0]
    expected = (mesh.values[..., 0].astype(np.float32) * original.astype(np.float32)).astype(
        np.float32
    )
    np.testing.assert_array_equal(
        product.values[..., 0].astype(np.float32).view(np.uint32), expected.view(np.uint32)
    )


def test_product_enters_mesh_binding_and_unit_controls_have_distinct_layer_state() -> None:
    golden = control.request()
    steps = golden.sequence.steps
    imports = {
        step["step"]: step["args"]["input"] for step in steps if step["call"] == ps.IMPORT_RESOURCE
    }
    bindings = {
        step["args"]["texture_set"]: imports[step["args"]["resource_step"]]
        for step in steps
        if step["call"] == ps.SET_MESH_MAP
    }
    assert bindings == {
        "s0": "grey-a",
        "s1": control.MESH_VALUES,
        "s2": control.PRODUCT_VALUES,
        "s3": control.PRODUCT_VALUES,
    }
    fills = {
        step["args"]["texture_set"]: step["step"]
        for step in steps
        if step["call"] == ps.INSERT_FILL
    }
    assert set(fills) == {"s0", "s1", "s3"}
    sources = {
        step["args"]["node_step"]: step["args"] for step in steps if step["call"] == ps.SET_SOURCE
    }
    for texture_set in ("s0", "s1"):
        assert imports[sources[fills[texture_set]]["resource_step"]] == "ao-precomposed-half-y"
    assert sources[fills["s3"]]["color"] == [1.0, 1.0, 1.0]
    assert sources[fills["s3"]]["color_space"] == "Raw"
    exports = [step["args"] for step in steps if step["call"] == EXPORT]
    assert [(e["file_format"], e["bit_depth"]) for e in exports] == [
        ("png", 8),
        ("png", 8),
        ("exr", "32f"),
        ("exr", "32f"),
    ]
    assert all(e["padding"] == "passthrough" and not e["dithering"] for e in exports)
    assert all(
        e["maps"]
        == [
            "virtualMap/AO_Mixed:L",
            "documentMap/ambientOcclusion:L",
            "meshMap/ambient_occlusion:L",
        ]
        for e in exports
    )


def test_registered_inputs_and_generated_request_match_authored_content() -> None:
    golden = control.request()
    hashes = {}
    for name in golden.inputs:
        _, path, generate = rr.fixture(name)
        content = (REPO_ROOT / path).read_bytes()
        assert generate is not None and content == generate()
        hashes[name] = hashlib.sha256(content).hexdigest()
    expected = rr.request_manifest(golden, hashes, current_envelope(REPO_ROOT))
    committed = json.loads((rr.request_dir(REPO_ROOT) / f"{golden.name}.json").read_text())
    assert committed == expected
    assert validation_errors(committed, Schema.GOLDEN_PUBLIC) == []
    assert committed["private_records"] == []
    assert reopen_count(job_from_manifest(committed)) == 1

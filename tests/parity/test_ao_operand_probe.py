"""Authored AO_Mixed operand probe: exact authored operands and the committed request."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.decode import decode
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, job_from_manifest
from tools.parity.recorder.texture import reopen_count
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics import ao_operand_probe as probe
from tools.parity.tier0_semantics import recording_requests as rr


def test_step_values_cover_every_step_and_its_neighbours() -> None:
    values = probe.step_values().ravel()
    assert values.min() == 0 and values.max() == 1
    steps = (np.arange(1, 4096) / 4096).astype(np.float32)
    present = set(values.view(np.uint32).tolist())
    for k in range(-6, 7):
        assert set(probe.shift(steps, k).view(np.uint32).tolist()) <= present
    # Just below 0.25 one float32 step is 2^-26, so two steps down is 2^-25 below it.
    assert float(probe.shift(np.float32(0.25), -2)) == 0.25 - 2.0**-25


def test_partners_put_the_exact_product_within_four_ulps_of_a_step() -> None:
    for fixed, partner in (probe.LATTICE_MESH_PAIR, probe.LATTICE_CHANNEL_PAIR, probe.FREE_PAIR):
        f = fixed().astype(np.float64).ravel()
        o = partner().astype(np.float64).ravel()
        assert (o > 0).all() and (o <= 1).all()
        product = f * o  # exact: 24 x 24 bits
        step = np.rint(product * 4096) / 4096
        t = (product - step) / np.spacing(step.astype(np.float32)).astype(np.float64)
        assert np.abs(t).max() < 4
        assert np.histogram(t, bins=np.arange(-3.25, 3.3, 0.5))[0].min() > 3000
    lattice = probe.lattice_codes(0).ravel()
    assert (lattice == (np.rint(lattice * 255.0) / 255).astype(np.float32)).all()


def test_blend_sources_hit_the_targeted_steps_exactly() -> None:
    for sources, blend, first in (
        (probe.l16_half_sources(), probe.blend_l16_half, 0.5),
        (probe.l32f_three_quarter_sources(), lambda s: probe.blend_l32f(s, 0.75), 0.25),
    ):
        assert (sources >= 0).all() and (sources <= 1).all()
        out = blend(sources).astype(np.float64).ravel()
        used = sources.ravel() != 1
        offsets = (out - np.rint(out * 4096) / 4096) / np.spacing(out.astype(np.float32))
        assert np.abs(offsets[used]).max() <= 4.5
        assert out[used].min() >= first - 2.0**-20


def test_sets_bind_their_mesh_fill_format_and_opacity() -> None:
    golden = probe.request()
    steps = golden.sequence.steps
    imports = {s["step"]: s["args"]["input"] for s in steps if s["call"] == ps.IMPORT_RESOURCE}
    formats = {
        s["args"]["texture_set"]: s["args"]["format"] for s in steps if s["call"] == ps.ADD_CHANNEL
    }
    meshes = {
        s["args"]["texture_set"]: imports[s["args"]["resource_step"]]
        for s in steps
        if s["call"] == ps.SET_MESH_MAP
    }
    fills = {s["step"]: s["args"]["texture_set"] for s in steps if s["call"] == ps.INSERT_FILL}
    sources = {
        fills[s["args"]["node_step"]]: s["args"] for s in steps if s["call"] == ps.SET_SOURCE
    }
    opacities = {
        fills[s["args"]["node_step"]]: s["args"]["opacity"]
        for s in steps
        if s["call"] == ps.SET_OPACITY
    }
    for texture_set, (fmt, mesh, source, opacity) in probe.SETS.items():
        assert formats[texture_set] == fmt
        assert meshes[texture_set] == mesh
        assert opacities[texture_set] == opacity
        if source is None:
            assert sources[texture_set]["color"] == [1.0, 1.0, 1.0]
            assert sources[texture_set]["color_space"] == "Raw"
        else:
            assert imports[sources[texture_set]["resource_step"]] == source
    exports = [s["args"] for s in steps if s["call"] == EXPORT]
    assert [(e["file_format"], e["bit_depth"]) for e in exports] == [
        ("png", 8),
        ("png", 8),
        ("exr", "32f"),
        ("exr", "32f"),
    ]
    assert all(e["maps"] == probe.MAPS and e["padding"] == "passthrough" for e in exports)
    assert not any(e["dithering"] for e in exports)


def test_registered_inputs_and_generated_request_match_authored_content() -> None:
    golden = probe.request()
    hashes = {}
    for name in golden.inputs:
        _, path, generate = rr.fixture(name)
        content = (REPO_ROOT / path).read_bytes()
        if name in probe.IMAGES:
            assert generate is not None and content == generate()
            decoded = decode(content)
            assert decoded.bits == 32 and not decoded.integer
            np.testing.assert_array_equal(
                decoded.values[..., 0].astype(np.float32).view(np.uint32),
                probe.IMAGES[name]().view(np.uint32),
            )
        hashes[name] = hashlib.sha256(content).hexdigest()
    expected = rr.request_manifest(golden, hashes, current_envelope(REPO_ROOT))
    committed = json.loads((rr.request_dir(REPO_ROOT) / f"{golden.name}.json").read_text())
    assert committed == expected
    assert validation_errors(committed, Schema.GOLDEN_PUBLIC) == []
    assert committed["private_records"] == []
    assert reopen_count(job_from_manifest(committed)) == 1

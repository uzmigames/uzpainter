"""Decision 131 scalar control: authored Y/FLOAT data, no RGB conversion assumption."""

from __future__ import annotations

import hashlib
import json
import struct

import numpy as np

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.decode import decode
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import job_from_manifest
from tools.parity.recorder.texture import reopen_count
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics.recording_requests import (
    ao_mixed_precomposed_probe,
    ao_mixed_precomposed_scalar_probe,
    fixture,
    request_dir,
    request_manifest,
)
from tools.parity.tier0_semantics.request_fixtures import ao_precomposed_half_y, exr_float_y

SOURCE_SHA256 = "942bf2a6e1e809be059f4dcc8e0b36d4d6cb7e6c8dccd6773e9cf13cac0b431e"


def test_scalar_fixture_has_only_y_float_and_exact_authored_rows() -> None:
    content = (REPO_ROOT / fixture("ao-precomposed-half-y")[1]).read_bytes()
    assert content == ao_precomposed_half_y()
    assert hashlib.sha256(content).hexdigest() == SOURCE_SHA256
    channel_header = b"channels\0chlist\0"
    start = content.index(channel_header) + len(channel_header)
    size = struct.unpack_from("<i", content, start)[0]
    assert content[start + 4 : start + 4 + size] == (
        b"Y\0" + struct.pack("<iB3xii", 2, 0, 1, 1) + b"\0"
    )
    decoded = decode(content)
    assert not decoded.integer and decoded.bits == 32
    assert decoded.values.shape == (256, 256, 1)

    def f32(value: float) -> float:
        return float(struct.unpack("<f", struct.pack("<f", value))[0])

    rows = [f32(f32(f32(code / 255) - 1) * 0.5 + 1) for code in range(256)]
    assert all(f32(f32(value - 1) + 1) == value for value in rows)
    expected = np.broadcast_to(np.array(rows, dtype=np.float32)[:, None], (256, 256))
    np.testing.assert_array_equal(
        decoded.values[..., 0].astype(np.float32).view(np.uint32), expected.view(np.uint32)
    )


def test_scalar_writer_keeps_partial_zip_block_and_float_bits() -> None:
    values = np.arange(51, dtype=np.float32).reshape(17, 3) / np.float32(51)
    values[0] = np.array([0x80000000, 1, 0xBF800000], dtype=np.uint32).view(np.float32)
    decoded = decode(exr_float_y(values))
    assert decoded.values.shape == (17, 3, 1) and decoded.bits == 32
    np.testing.assert_array_equal(
        decoded.values[..., 0].astype(np.float32).view(np.uint32), values.view(np.uint32)
    )


def test_scalar_request_preserves_paired_composition_and_operand_exports() -> None:
    scalar = ao_mixed_precomposed_scalar_probe()
    original = ao_mixed_precomposed_probe()
    normalized = json.loads(json.dumps(scalar.sequence.steps))
    for step in normalized:
        if step["call"] == ps.IMPORT_RESOURCE and step["args"]["input"] == "ao-precomposed-half-y":
            step["args"]["input"] = "ao-precomposed-half"
    assert normalized == original.sequence.steps
    assert "single-channel Y/FLOAT" in scalar.description
    assert "inconclusive" in scalar.description
    hashes = {
        name: hashlib.sha256((REPO_ROOT / fixture(name)[1]).read_bytes()).hexdigest()
        for name in scalar.inputs
    }
    expected = request_manifest(scalar, hashes, current_envelope(REPO_ROOT))
    request = json.loads((request_dir(REPO_ROOT) / f"{scalar.name}.json").read_text())
    assert request == expected
    assert validation_errors(request, Schema.GOLDEN_PUBLIC) == []
    assert reopen_count(job_from_manifest(request)) == 1
    assert request["private_records"] == []

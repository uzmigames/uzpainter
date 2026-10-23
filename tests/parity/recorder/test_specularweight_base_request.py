"""Empty-channel controls must not accidentally measure a fill or a converted format."""

import hashlib

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, job_from_manifest
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics.recording_requests import (
    ALPHA_BLEND,
    request_manifest,
    specularweight_base_probes,
)


def test_each_empty_specularweight_format_starts_fresh_and_repeats_exports() -> None:
    probes = specularweight_base_probes()
    assert len({p.name for p in probes}) == 6
    seen = set()
    entry = current_envelope()
    hashes = {
        "plane": hashlib.sha256(
            (REPO_ROOT / "parity/fixtures/meshes/plane.obj").read_bytes()
        ).hexdigest()
    }
    for probe in probes:
        steps = probe.sequence.steps
        assert [s["call"] for s in steps] == [
            "substance_painter.project.create",
            ps.ADD_CHANNEL,
            EXPORT,
            EXPORT,
            EXPORT,
            EXPORT,
        ]
        create, add = (s["args"] for s in steps[:2])
        assert create["mesh"] == "plane" and create["default_texture_resolution"] == 256
        assert add["channel"] == "SpecularWeight"
        seen.add((create.get("template"), add["format"]))
        assert steps[2]["args"] == steps[3]["args"]
        assert steps[4]["args"] == steps[5]["args"]
        for step, container in zip(
            steps[2:], [("exr", "32f")] * 2 + [("png", 16)] * 2, strict=True
        ):
            assert step["args"] == {
                "maps": ["documentMap/specularweight:L"],
                "file_format": container[0],
                "bit_depth": container[1],
                "padding": "infinite",
                "dithering": False,
            }
        manifest = request_manifest(probe, hashes, entry)
        assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
        assert manifest["private_records"] == []
        assert len(job_from_manifest(manifest).exports) == 4
    assert seen == {
        (template, fmt) for template in (None, ALPHA_BLEND) for fmt in ("L8", "L16", "L32F")
    }

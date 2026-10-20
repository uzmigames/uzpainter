"""Independent R-131 operand coverage checks over the committed fixture bytes."""

from __future__ import annotations

import hashlib
import json

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.capture import decode_png
from tools.parity.recorder.job import EXPORT
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR, FIXTURES
from tools.parity.tier0_semantics.recording_requests import (
    ADMITTED,
    ao_mixed_grid_probe,
    request_manifest,
)


def test_r131_committed_request_matches_generator_and_input_bytes() -> None:
    golden = ao_mixed_grid_probe()
    hashes = {
        name: hashlib.sha256((REPO_ROOT / FIXTURES[name][1]).read_bytes()).hexdigest()
        for name in golden.inputs
    }
    # Admitted on 2026-10-20: the manifest moved from `requests/` to `manifests/` and gained its
    # private records; its authored part must still be the generator's.
    assert golden.name in ADMITTED
    entry = current_envelope(REPO_ROOT)
    path = manifest_root(entry, REPO_ROOT) / "tier0" / "semantics" / "ao-mixed-grid.json"
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed["private_records"]
    expected = request_manifest(golden, hashes, entry)
    assert {**committed, "private_records": []} == expected


def test_r131_inputs_cover_every_operand_pair_exactly_once() -> None:
    mesh = decode_png(REPO_ROOT / FIXTURE_DIR / "bitmaps/grey-a.png")
    channel = decode_png(REPO_ROOT / FIXTURE_DIR / "bitmaps/grey-b.png")
    assert (mesh.width, mesh.height, mesh.channels) == (256, 256, 1)
    assert (channel.width, channel.height, channel.channels) == (256, 256, 1)
    pairs = []
    for index, (a, b) in enumerate(zip(mesh.pixels, channel.pixels, strict=True)):
        y, x = divmod(index, 256)
        assert a == (x * 257,) and b == (y * 257,)
        pairs.append((a[0] // 257, b[0] // 257))
    assert len(pairs) == len(set(pairs)) == 65536
    assert set(pairs) == {(a, b) for a in range(256) for b in range(256)}


def test_r131_each_set_covers_the_whole_uv_square_without_overlapping_triangles() -> None:
    lines = (REPO_ROOT / FIXTURE_DIR / "meshes/grid2x2.obj").read_text().splitlines()
    uv = [tuple(map(float, line.split()[1:])) for line in lines if line.startswith("vt ")]
    faces: dict[str, list[list[str]]] = {}
    material = ""
    for line in lines:
        if line.startswith("usemtl "):
            material = line.split()[1]
            faces[material] = []
        elif line.startswith("f "):
            faces[material].append(line.split()[1:])
    assert set(faces) == {"s0", "s1", "s2", "s3"}
    assert set(uv) == {(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)}
    for group in faces.values():
        triangles = [tuple(uv[int(vertex.split("/")[1]) - 1] for vertex in face) for face in group]
        assert len(triangles) == 2 and all(len(triangle) == 3 for triangle in triangles)
        shared = set(triangles[0]) & set(triangles[1])
        assert len(shared) == 2
        p, q = sorted(shared)
        assert abs(p[0] - q[0]) == abs(p[1] - q[1]) == 1
        for a, b, c in triangles:
            area_twice = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            assert area_twice == 1


def test_r131_repeat_exports_preserve_state_and_operand_readbacks() -> None:
    steps = ao_mixed_grid_probe().sequence.steps
    first_export = next(i for i, step in enumerate(steps) if step["call"] == EXPORT)
    captures = steps[first_export:]
    assert len(captures) == 4 and all(step["call"] == EXPORT for step in captures)
    assert captures[0]["args"] == captures[1]["args"]
    assert captures[2]["args"] == captures[3]["args"]
    assert [(step["args"]["file_format"], step["args"]["bit_depth"]) for step in captures] == [
        ("png", 8),
        ("png", 8),
        ("exr", "32f"),
        ("exr", "32f"),
    ]
    for step in captures:
        assert step["args"]["maps"] == [
            "virtualMap/AO_Mixed:L",
            "documentMap/ambientOcclusion:L",
            "meshMap/ambient_occlusion:L",
        ]
        assert step["args"]["dithering"] is False
        assert step["args"]["padding"] == "passthrough"

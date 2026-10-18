"""Requested Tier 0 goldens of Phase 1 (decision 100): manifests prepared before the Painter
session under the current envelope's `requests/` root, and their authored fixtures."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

import pytest

from tools.parity.envelope.registry import current_envelope
from tools.parity.guard.guard import load_index, run_guard, worktree_snapshot
from tools.parity.recorder.capture import decode_png
from tools.parity.recorder.job import load_job
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR
from tools.parity.tier0_semantics.recording_requests import (
    OCIO_SETTING,
    REQUEST_FIXTURES,
    ocio_goldens,
    probe_groups,
    request_dir,
    request_root,
    requested_goldens,
    srgb_bitmap_variants,
)


def request_paths() -> list[Path]:
    return sorted(request_dir(REPO_ROOT).glob("*.json"))


def test_every_requested_golden_is_committed_once() -> None:
    assert sorted(p.stem for p in request_paths()) == sorted(g.name for g in requested_goldens())
    assert ocio_goldens() == {"export-ocio-encode", "export-presets-ocio"}


@pytest.mark.parametrize("path", request_paths(), ids=lambda p: p.stem)
def test_request_validates_names_no_record_and_is_a_recorder_job(path: Path) -> None:
    manifest = load_json(path)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["private_records"] == []
    assert manifest["golden_id"] == f"tier0/semantics/{path.stem}"
    assert manifest["software"]["painter"]["build_id"] == current_envelope()["painter_build"]
    job = load_job(path)
    assert job.exports or job.export_probes
    ocio = OCIO_SETTING in manifest["applied_settings"]
    assert ocio == (path.stem in ocio_goldens())


def test_requests_live_beside_the_envelope_manifests() -> None:
    root = request_root(REPO_ROOT)
    assert root.name == "requests"
    assert (root.parent / "manifests").is_dir()


def obj_uvs(name: str) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]], list[str]]:
    text = (REPO_ROOT / FIXTURE_DIR / "meshes" / f"{name}.obj").read_text(encoding="ascii")
    lines = text.splitlines()
    vertices = [tuple(float(v) for v in ln.split()[1:]) for ln in lines if ln.startswith("v ")]
    uvs = [tuple(float(v) for v in ln.split()[1:]) for ln in lines if ln.startswith("vt ")]
    return vertices, uvs, [ln for ln in lines if ln.startswith("f ")]


def test_islands_mesh_has_the_requested_gaps() -> None:
    """R1: one island on the left border, gaps of 1 and 3 texels, a turned island ~20 away."""
    _, uvs, faces = obj_uvs("islands")
    assert len(uvs) == 16 and len(faces) == 8
    texels = [(u * 256.0, v * 256.0) for u, v in uvs]
    boxes = [
        (min(x for x, _ in q), max(x for x, _ in q), min(y for _, y in q), max(y for _, y in q))
        for q in (texels[i : i + 4] for i in range(0, 16, 4))
    ]
    assert boxes[0][0] == 0.0
    assert math.isclose(boxes[1][0] - boxes[0][1], 1.0, abs_tol=1e-4)
    assert math.isclose(boxes[2][0] - boxes[1][1], 3.0, abs_tol=1e-4)
    assert 19.0 < boxes[0][2] - boxes[3][3] < 22.0
    assert all(0.0 <= x <= 256.0 and 0.0 <= y <= 256.0 for x, y in texels)


def test_seam_mesh_shares_one_3d_edge_across_two_islands() -> None:
    """R-090 P9: two quads share two vertices; their UVs form two disjoint islands, A on the
    tile's left border, B turned 90 degrees at another scale."""
    vertices, uvs, faces = obj_uvs("seam")
    assert len(vertices) == 6 and len(uvs) == 8 and len(faces) == 4
    corners = [
        {int(c.split("/")[0]) for f in faces[i : i + 2] for c in f.split()[1:]} for i in (0, 2)
    ]
    shared = corners[0] & corners[1]
    assert len(shared) == 2 and all(vertices[i - 1][0] == 10.0 for i in shared)
    a, b = uvs[:4], uvs[4:]
    assert min(u for u, _ in a) == 0.0
    assert max(u for u, _ in a) < min(u for u, _ in b)
    assert max(u for u, _ in a) < rf.SEAM_SIDE_COLUMN / 256.0 < min(u for u, _ in b)
    span = (
        max(u for u, _ in a) - min(u for u, _ in a),
        max(u for u, _ in b) - min(u for u, _ in b),
    )
    assert span == pytest.approx((0.375, 0.25))


def bitmap(name: str) -> tuple[int, int, int, list[tuple[int, ...]]]:
    path = REPO_ROOT / FIXTURE_DIR / "bitmaps" / f"{name}.png"
    image = decode_png(path)
    depth = path.read_bytes()[24]  # IHDR bit depth
    return image.width, image.height, depth, [tuple(t) for t in image.pixels]


def test_slow_ramps_cross_only_a_few_8bit_steps() -> None:
    """R3: R spans about four 8-bit steps across the tile; B stays inside one step."""
    width, height, depth, texels = bitmap("slow-ramp")
    assert (width, height, depth) == (256, 256, 16)
    reds = [t[0] for t in texels[:256]]
    assert 3 <= (max(reds) - min(reds)) / 257 <= 5
    assert {t[2] // 257 for t in texels} == {127}
    _, _, _, grey = bitmap("slow-ramp-grey")
    assert [g[0] for g in grey] == [t[0] for t in texels]


def test_impulse_half_steps_and_srgb8_ramp() -> None:
    _, _, _, impulse = bitmap("impulse-texel")
    hits = [i for i, t in enumerate(impulse) if t != (0, 0, 0)]
    x, y = rf.IMPULSE_TEXEL
    assert hits == [y * 256 + x] and impulse[hits[0]] == (65535, 65535, 65535)
    _, _, _, half = bitmap("half-steps")
    assert half[10] == (10 * 257 + 128, 10 * 257 + 129, 0)
    width, _, depth, ramp = bitmap("srgb8-ramp")
    assert (width, depth) == (256, 8) and ramp[257] == (1, 1, 254)


def test_probe_configurations_leave_the_export_path_to_the_recorder() -> None:
    for group, probes in probe_groups().items():
        for probe, config in probes.items():
            data = (REPO_ROOT / REQUEST_FIXTURES[f"probe-{group}-{probe}"][1]).read_bytes()
            assert json.loads(data) == config
            assert "exportPath" not in config
            assert config["exportList"]


def test_the_requests_and_their_fixtures_pass_the_guard() -> None:
    snapshot = worktree_snapshot(
        REPO_ROOT,
        (request_root(REPO_ROOT).relative_to(REPO_ROOT).as_posix(), FIXTURE_DIR),
    )
    assert snapshot.checked
    store = locate()
    index = None if store is None else load_index(store.root / "index.json")
    assert [str(f) for f in run_guard(REPO_ROOT, snapshot, index)] == []


def test_srgb8_grey_ramp_holds_every_code() -> None:
    """Decision 145 s0: 8-bit grey, column x holds code x."""
    width, height, depth, texels = bitmap("srgb8-grey-ramp")
    assert (width, height, depth) == (256, 256, 8)
    assert [t[0] for t in texels[:256]] == list(range(256))
    assert all(texels[y * 256 + x][0] == x for y in (0, 255) for x in range(256))


# Decision 129 fixes the P-ramp meshes by SHA-256 (phase 0, +0.25/1024, +0.75/1024).
P_RAMP_SHA256 = {
    "r1": (
        "be463fa73ab3ddba7e6d536d1b9e366b9b987dd42494a53a7535af830b33c95e",
        "a9300f4531619c51d931054b0634da0a6d38ba3d1577767b988cad5c4d504074",
        "e68e4c014bf51b2016ba5f5c0daf12afa509a866fac5073ba218d18f3256832f",
    ),
    "r2": (
        "50376d51b0dbcdecbb9aa4e77051dcf9d3763669d7553209e002afa6f2a0b100",
        "d2dee8be1567e62c2ff8c674a7d636f985779c3827b5f6c61e3ce8734bf53c9d",
        "b8b4a1ab1574c874d33db00128c0d33d9405afc222c067e22b080a540ea69d87",
    ),
    "r15": (
        "ca9b86387b8bd14ba15766c37c4c4037f20c85f5c689125496e728569137bc62",
        "ebf2bc7a92ece0d4e17f263c4579d7f1145a0364cb28f55224fe27e13acf8c59",
        "821c625e8e3cb90401b22116e719742a11aee234222db426d3b6ed24504b7553",
    ),
}


def test_p_ramp_meshes_are_the_ones_decision_129_fixes() -> None:
    for mesh, hashes in P_RAMP_SHA256.items():
        for phase, want in zip(rf.RAMP_PHASES, hashes, strict=True):
            path = REPO_ROOT / FIXTURE_DIR / "meshes" / f"seam-ramp-{mesh}-{phase}.obj"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == want, (mesh, phase)


def test_tie_mesh_has_three_axis_aligned_islands() -> None:
    _, uvs, faces = obj_uvs("tie")
    assert len(uvs) == 12 and len(faces) == 6
    for corner, quad in zip(rf.TIE_CORNERS, (uvs[i : i + 4] for i in (0, 4, 8)), strict=True):
        assert (min(u for u, _ in quad), min(v for _, v in quad)) == corner
        assert max(u for u, _ in quad) - corner[0] == rf.TIE_SIDE


def test_ring_sign_probe_meshes_move_only_the_bounding_box() -> None:
    """Decision 210 section 5: tie-box16 keeps tie's UVs and faces in a box centred at the
    origin with half-extent 16; seam-ramp-r1-p0-box17 keeps r1-p0's in a box of largest extent
    34 (decision 216)."""
    for moved, base, low, high in (
        ("tie-box16", "tie", (-16.0, 0.0, -5.0), (16.0, 0.0, 5.0)),
        ("seam-ramp-r1-p0-box17", "seam-ramp-r1-p0", (0.0, 0.0, 0.0), (34.0, 0.0, 17.0)),
    ):
        vertices, uvs, faces = obj_uvs(moved)
        _, base_uvs, base_faces = obj_uvs(base)
        assert (uvs, faces) == (base_uvs, base_faces)
        assert tuple(min(c) for c in zip(*vertices, strict=True)) == low
        assert tuple(max(c) for c in zip(*vertices, strict=True)) == high


def exr_rgb(path: Path) -> tuple[int, int, list[tuple[float, float, float]]]:
    """Decode the authored ZIP float EXR (channels B, G, R) without OpenEXR."""
    data = path.read_bytes()
    header_end = data.index(b"screenWindowWidth") + len(b"screenWindowWidth\0float\0") + 8 + 1
    box = data.index(b"dataWindow\0box2i\0") + len(b"dataWindow\0box2i\0") + 4
    x0, y0, x1, y1 = struct.unpack("<iiii", data[box : box + 16])
    width, height = x1 - x0 + 1, y1 - y0 + 1
    blocks = (height + 15) // 16
    offsets = struct.unpack(f"<{blocks}Q", data[header_end : header_end + 8 * blocks])
    pixels: list[tuple[float, float, float]] = []
    for offset in offsets:
        y, size = struct.unpack("<ii", data[offset : offset + 8])
        lines = min(16, height - y)
        packed = data[offset + 8 : offset + 8 + size]
        raw_size = lines * width * 3 * 4
        if size < raw_size:
            split = bytearray(zlib.decompress(packed))
            for i in range(1, len(split)):
                split[i] = (split[i - 1] + split[i] - 128) & 0xFF
            half = (len(split) + 1) // 2
            raw = bytearray(len(split))
            raw[0::2], raw[1::2] = split[:half], split[half:]
        else:
            raw = bytearray(packed)
        for line in range(lines):
            row = struct.unpack(f"<{3 * width}f", raw[line * width * 12 : (line + 1) * width * 12])
            b, g, r = row[:width], row[width : 2 * width], row[2 * width :]
            pixels += list(zip(r, g, b, strict=True))
    return width, height, pixels


def test_uv_ramps_are_float32_texel_centres() -> None:
    """Decision 129: R = (x + 0.5)/N, G = (y + 0.5)/N (y from the top row), B = 0.5."""
    width, height, pixels = exr_rgb(REPO_ROOT / FIXTURE_DIR / "bitmaps" / "uv-ramp-512.exr")
    assert (width, height) == (512, 512)
    for y in (0, 17, 511):
        for x in (0, 300, 511):
            r, g, b = pixels[y * 512 + x]
            assert (r, g, b) == (
                struct.unpack("<f", struct.pack("<f", (x + 0.5) / 512))[0],
                struct.unpack("<f", struct.pack("<f", (y + 0.5) / 512))[0],
                0.5,
            )
    for name, size in (
        ("uv-ramp-1024", 1024),
        ("uv-ramp-2048", 2048),
        ("uv-ramp-n1024", 1024),
        ("uv-ramp-n2048", 2048),
    ):
        data = (REPO_ROOT / FIXTURE_DIR / "bitmaps" / f"{name}.exr").read_bytes()
        assert data == rf.uv_ramp(size)


def test_no_requested_bitmap_reads_as_a_udim_tile() -> None:
    """Decision 160: Painter took a file stem ending in a number from 1001 up as a UDIM tile
    and the bitmap never reached the 0-1 tile, so no requested golden imports one (decision
    166)."""
    for golden in requested_goldens():
        for name in golden.inputs:
            kind, path, _ = REQUEST_FIXTURES.get(name, ("", "", None))
            tail = Path(path).stem.rsplit("-", 1)[-1]
            assert kind != "image" or not (tail.isdigit() and int(tail) >= 1001), (golden, name)


def test_srgb_variants_attempt_the_user_channel_spaces() -> None:
    """Decision 166: s4 sets each user channel's bitmap, then attempts set_color_space(sRGB), so
    Painter's refusal on a non-sRGB8 channel is recorded instead of refusing the golden."""
    steps = srgb_bitmap_variants().sequence.steps
    attempted = [
        s["args"]["channel"]
        for s in steps
        if s["call"] == "substance_painter.source.SourceBitmap.set_color_space"
    ]
    assert attempted == ["User1", "User2", "User3", "User4", "User5", "User7", None]
    assert not any(
        s["args"].get("color_space") and str(s["args"].get("channel")).startswith("User")
        for s in steps
        if s["call"] != "substance_painter.source.SourceBitmap.set_color_space"
    )


def test_kernel_code_bitmaps_one_hot_every_class_and_hold_the_controls() -> None:
    """Decision 266: User0-User2 give the texel (x, y) the one slot x mod 3 + 3 (y mod 3) of 9;
    d and e are k/256 with a 17 x 13 period, f = (d + e)/2 and g = 1 - d exactly."""
    bitmaps = REPO_ROOT / FIXTURE_DIR / "bitmaps"
    slots = [exr_rgb(bitmaps / f"kernel-onehot-{p}-n256.exr")[2] for p in rf.KERNEL_ONEHOT]
    for y in (0, 1, 2, 100, 255):
        for x in (0, 1, 2, 37, 255):
            hot = [v for part in slots for v in part[y * 256 + x]]
            assert hot == [1.0 if k == x % 3 + 3 * (y % 3) else 0.0 for k in range(9)], (x, y)
    d, e, f, g = (exr_rgb(bitmaps / f"kernel-code-{n}-n256.exr")[2] for n in rf.KERNEL_CODES)
    columns, rows = rf.KERNEL_PERIOD
    for i in range(0, 256 * 256, 97):
        x, y = i % 256, i // 256
        assert d[i] == d[(y % rows) * 256 + x % columns]
        assert all(0 < c < 1 and (c * 256).is_integer() for c in d[i] + e[i])
        assert f[i] == tuple((a + b) / 2 for a, b in zip(d[i], e[i], strict=True))
        assert g[i] == tuple(1 - a for a in d[i])


def covered_centres(uvs: list[tuple[float, float]]) -> set[tuple[int, int]]:
    """Texel centres (column, row from the top) strictly inside a convex UV polygon given in
    texels; a centre on an edge fails the test."""
    cells = set()
    for x in range(math.floor(min(c for c, _ in uvs)), math.ceil(max(c for c, _ in uvs))):
        for y in range(math.floor(min(r for _, r in uvs)), math.ceil(max(r for _, r in uvs))):
            sides = [
                (q[0] - p[0]) * (y + 0.5 - p[1]) - (q[1] - p[1]) * (x + 0.5 - p[0])
                for p, q in zip(uvs, uvs[1:] + uvs[:1], strict=True)
            ]
            assert 0.0 not in sides, ("texel centre on an edge", x, y)
            if all(s > 0 for s in sides) or all(s < 0 for s in sides):
                cells.add((x, y))
    return cells


def test_kernel_atlas_covers_its_configurations_apart_at_every_resolution() -> None:
    """Decision 266: every item covers its declared texel centres, items lie 8 texels apart;
    the meshes at 512, 1024 and 2048 differ only in u = column / N, v = 1 - row / N, the box is
    exactly [-256, 256] cm in x and z, and the moved mesh scales it by 1.7."""
    items = {item.name: item.covers for item in rf.atlas_items()}
    covered = {}
    for name, faces in rf.atlas_faces():
        covered[name] = set().union(*(covered_centres(uvs) for _, uvs in faces))
        assert len(covered[name]) == items.get(name, 0), name
    names = sorted(covered)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert all(
                max(abs(x - u), abs(y - v)) >= rf.ATLAS_GAP
                for x, y in covered[a]
                for u, v in covered[b]
            ), (a, b)
    meshes = {n: obj_uvs(f"kernel-atlas-n{n}") for n in rf.ATLAS_RESOLUTIONS}
    vertices, uvs, face_lines = meshes[512]
    for n, (v_n, uv_n, f_n) in meshes.items():
        assert (v_n, f_n) == (vertices, face_lines)
        texels = [c for u, v in uv_n for c in (u * n, (1 - v) * n)]
        # Dyadic UVs are exact; the 30-degree seam's are written with 9 decimals.
        assert texels == pytest.approx(
            [c for u, v in uvs for c in (u * 512, (1 - v) * 512)], abs=1e-5
        )
    low = tuple(min(c) for c in zip(*vertices, strict=True))
    high = tuple(max(c) for c in zip(*vertices, strict=True))
    assert (low[0], low[2], high[0], high[2]) == (-256.0, -256.0, 256.0, 256.0)
    moved, moved_uvs, moved_faces = obj_uvs("kernel-atlas-n1024-moved")
    assert (moved_uvs, moved_faces) == meshes[1024][1:]
    offset = rf.ATLAS_MOVED_OFFSET
    for p, q in zip(vertices, moved, strict=True):
        assert q == pytest.approx(
            [c * rf.ATLAS_MOVED_SCALE + o for c, o in zip(p, offset, strict=True)]
        )

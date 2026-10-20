"""Requested Tier 0 goldens of Phase 1 (decision 100): manifests prepared before the Painter
session under the current envelope's `requests/` root, and their authored fixtures."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from fractions import Fraction
from pathlib import Path

import numpy as np
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
    padding_normal_combine_probe,
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
    assert ocio_goldens() == {
        "export-ocio-encode",
        "export-presets-ocio",
        "export-presets-gltf-ocio",
    }


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


@pytest.mark.parametrize("family", rf.SWEEP_FAMILIES)
def test_tie_sweep_copies_are_apart_and_the_boxes_differ_only_as_designed(family: str) -> None:
    """Decision 272: every copy covers its unit's texel centres with none on an edge, copies lie
    at least 7 texels apart in UV and apart in 3D; the centred box is exactly [-256, 256] in x
    and z, offcentre moves every vertex by (256, 0, 256) (rounded to float32) and box320 only
    moves the anchors to +-320, all three with the same UVs and faces."""
    expected = {"row-8": 8, "row-16": 16, "column-8": 8, "column-16": 16, "seam": 80, "vgap": 32}
    owner: dict[tuple[int, int], int] = {}
    placed, _ = rf.sweep_layout(family)
    for index, (copy, (oc, orow)) in enumerate(placed):
        cells = [covered_centres([(c + oc, r + orow) for c, r in uvs]) for _, uvs in copy.tris]
        union = set().union(*cells)
        assert sum(map(len, cells)) == len(union) == expected[copy.unit], copy.name
        owner |= dict.fromkeys(union, index)
    for (x, y), index in owner.items():
        near = {owner.get((x + dx, y + dy), index) for dx in range(-6, 7) for dy in range(-6, 7)}
        assert near == {index}, placed[index][0].name
    bounds = [copy.bounds() for copy, _ in placed]
    for i, (lo, hi) in enumerate(bounds):
        for lo2, hi2 in bounds[i + 1 :]:
            assert any(hi[a] < lo2[a] or hi2[a] < lo[a] for a in range(3)), placed[i][0].name
    meshes = {box: obj_uvs(f"tie-sweep-{family}-{box}") for box in rf.SWEEP_BOXES}
    vertices, uvs, faces = meshes["centred"]
    low = tuple(min(c) for c in zip(*vertices, strict=True))
    high = tuple(max(c) for c in zip(*vertices, strict=True))
    assert (low, high) == ((-256.0, -64.0, -256.0), (256.0, 64.0, 256.0))
    moved, moved_uvs, moved_faces = meshes["offcentre"]
    assert (moved_uvs, moved_faces) == (uvs, faces)
    for p, q in zip(vertices, moved, strict=True):
        assert q == tuple(float(np.float32(c + s)) for c, s in zip(p, (256, 0, 256), strict=True))
    wide, wide_uvs, wide_faces = meshes["box320"]
    assert (wide_uvs, wide_faces) == (uvs, faces)
    changed = [(p, q) for p, q in zip(vertices, wide, strict=True) if p != q]
    assert len(changed) == 6
    for p, q in changed:
        shift = 64.0 if p[0] > 0 else -64.0
        assert q == (p[0] + shift, p[1], p[2] + shift)


@pytest.mark.parametrize("probe", rf.FOLD_PROBES)
def test_fold_copies_share_their_seam_and_fold_by_their_angle(probe: str) -> None:
    """Decision 278: A covers 16 texel centres and B 4 per texel of depth, none on an edge; the
    copies lie at least 7 texels apart in UV and apart in 3D; each copy's A and B share the two
    seam vertices in the mesh, and the written float32 positions fold B by the copy's angle,
    on the side of A's normal when it is positive (concave); the box is [-256, 256] x
    [-64, 64] x [-256, 256]."""
    owner: dict[tuple[int, int], int] = {}
    placed, _ = rf.fold_layout(probe)
    for index, (copy, (oc, orow), _) in enumerate(placed):
        cells = [covered_centres([(c + oc, r + orow) for c, r in uvs]) for _, uvs in copy.tris]
        union = set().union(*cells)
        assert sum(map(len, cells)) == len(union) == 16 + 4 * copy.depth, copy.name
        owner |= dict.fromkeys(union, index)
    for (x, y), index in owner.items():
        near = {owner.get((x + dx, y + dy), index) for dx in range(-6, 7) for dy in range(-6, 7)}
        assert near == {index}, placed[index][0].name
    bounds = [
        tuple(tuple(b + o for b, o in zip(corner, offset, strict=True)) for corner in copy.bounds())
        for copy, _, offset in placed
    ]
    for i, (lo, hi) in enumerate(bounds):
        for lo2, hi2 in bounds[i + 1 :]:
            assert any(hi[a] < lo2[a] or hi2[a] < lo[a] for a in range(3)), placed[i][0].name
    vertices, _, faces = obj_uvs(f"concave-fold-{probe}")
    low = tuple(min(c) for c in zip(*vertices, strict=True))
    high = tuple(max(c) for c in zip(*vertices, strict=True))
    assert (low, high) == ((-256.0, -64.0, -256.0), (256.0, 64.0, 256.0))
    triangles = [
        [np.array(vertices[int(ref.split("/")[0]) - 1]) for ref in line.split()[1:]]
        for line in faces
    ]
    for index, (copy, _, _) in enumerate(placed):
        a, a2, *bs = triangles[4 * index : 4 * index + 4]
        [(b, shared)] = [
            (b, s)
            for b in bs
            if len(s := [i for i, p in enumerate(b) if any((p == q).all() for q in a + a2)]) == 2
        ]
        normal = np.cross(a[1] - a[0], a[2] - a[0])
        normal /= np.linalg.norm(normal)
        far = b[3 - sum(shared)]
        other = np.cross(b[1] - b[0], b[2] - b[0])
        cos = normal @ other / np.linalg.norm(other)
        assert math.degrees(math.acos(min(cos, 1.0))) == pytest.approx(abs(copy.angle), abs=1e-3)
        lift = normal @ (far - b[shared[0]])
        assert (lift > 1e-6) == (copy.angle > 0) and (lift < -1e-6) == (copy.angle < 0), copy.name


@pytest.mark.parametrize("probe", rf.HINGE_PROBES)
def test_hinge_copies_share_their_hinges_and_bend_by_their_angles(probe: str) -> None:
    """Decision 289: each copy's A and B cover 16 texel centres each, none on an edge; the
    copies lie at least 7 texels apart in UV and apart in 3D; across every designed hinge (the
    seam first) the two planar faces share exactly two mesh vertices, and the written float32
    positions bend the far face by the hinge's angle, on the near face's normal side exactly
    when it is positive (concave); the box is [-256, 256] x [-64, 64] x [-256, 256]."""
    owner: dict[tuple[int, int], int] = {}
    placed, _ = rf.hinge_layout(probe)
    for index, (copy, (oc, orow), _) in enumerate(placed):
        cells = [covered_centres([(c + oc, r + orow) for c, r in uvs]) for _, uvs in copy.tris]
        union = set().union(*cells)
        assert sum(map(len, cells)) == len(union) == 32, copy.name
        owner |= dict.fromkeys(union, index)
    for (x, y), index in owner.items():
        near = {owner.get((x + dx, y + dy), index) for dx in range(-6, 7) for dy in range(-6, 7)}
        assert near == {index}, placed[index][0].name
    bounds = [
        tuple(tuple(b + o for b, o in zip(corner, offset, strict=True)) for corner in copy.bounds())
        for copy, _, offset in placed
    ]
    for i, (lo, hi) in enumerate(bounds):
        for lo2, hi2 in bounds[i + 1 :]:
            assert any(hi[a] < lo2[a] or hi2[a] < lo[a] for a in range(3)), placed[i][0].name
    vertices, _, faces = obj_uvs(f"hinge-{probe}")
    low = tuple(min(c) for c in zip(*vertices, strict=True))
    high = tuple(max(c) for c in zip(*vertices, strict=True))
    assert (low, high) == ((-256.0, -64.0, -256.0), (256.0, 64.0, 256.0))
    refs = [[int(ref.split("/")[0]) - 1 for ref in line.split()[1:]] for line in faces]
    first = 0
    for copy, _, _ in placed:
        if isinstance(copy, rf.HingeCopy):
            groups, hinges = copy.faces, copy.hinges
        else:
            groups, hinges = [[0, 1], [2, 3]], [(0, 1, copy.angle)]
        assert sum(map(len, groups)) == len(copy.tris)
        tris = refs[first : first + len(copy.tris)]
        first += len(copy.tris)
        for inner, outer, angle in hinges:
            a = {v for t in groups[inner] for v in tris[t]}
            b = {v for t in groups[outer] for v in tris[t]}
            assert len(a & b) == 2, (copy.name, inner, outer)
            p = [np.array(vertices[v]) for v in tris[groups[inner][0]]]
            normal = np.cross(p[1] - p[0], p[2] - p[0])
            normal /= np.linalg.norm(normal)
            for t in groups[outer]:
                r = [np.array(vertices[v]) for v in tris[t]]
                other = np.cross(r[1] - r[0], r[2] - r[0])
                cos = normal @ other / np.linalg.norm(other)
                bend = math.degrees(math.acos(min(cos, 1.0)))
                # Thin bands (0.1875 cm) carry up to about 2e-3 degrees of float32 rounding.
                assert bend == pytest.approx(abs(angle), abs=5e-3), (copy.name, inner, outer)
            lift = max((normal @ (np.array(vertices[v]) - p[0]) for v in b - a), key=abs)
            # A flat hinge's off-hinge vertices sit within float32 rounding of the near plane.
            assert (lift > 1e-4) == (angle > 0) and (lift < -1e-4) == (angle < 0), copy.name
    assert first == len(refs) - 2  # the two box anchors


def _through(
    texel: list[list[tuple[float, float]]],
    point: list[list[np.ndarray]],
    src: int,
    dst: int,
    at: np.ndarray,
) -> np.ndarray:
    """`at` in flat triangle `src`'s texel space, mapped through 3D to triangle `dst`'s texels."""
    u = np.array(texel[src])
    w = np.linalg.solve(np.array([u[1] - u[0], u[2] - u[0]]).T, at - u[0])
    p = (
        point[src][0]
        + w[0] * (point[src][1] - point[src][0])
        + w[1] * (point[src][2] - point[src][0])
    )
    g = np.array(point[dst])
    k = np.linalg.solve(np.array([g[1] - g[0], g[2] - g[0]]).T, p - g[0])
    v = np.array(texel[dst])
    result: np.ndarray = v[0] + k[0] * (v[1] - v[0]) + k[1] * (v[2] - v[0])
    return result


def test_window_side_copies_put_far_points_on_window_boundaries() -> None:
    """Decision 289 for decision 291: each copy's islands cover their texel centres, none within
    1/64 texel of an edge; copies lie at least 7 texels apart in UV and apart in 3D; A and B are
    flat and share the two seam vertices; each target ring texel's far point lies exactly on a
    u or v window boundary (f - 1/2 an integer) in exact arithmetic, and within 1e-4 texel of it
    through the written mesh (float UVs that are not all dyadic)."""
    owner: dict[tuple[int, int], int] = {}
    placed, _ = rf.side_layout()
    for index, (copy, (oc, orow), _) in enumerate(placed):
        assert rf.side_margin(copy) >= rf.SIDE_MARGIN, copy.name
        cells = [covered_centres([(c + oc, r + orow) for c, r in uvs]) for _, uvs in copy.tris]
        union = set().union(*cells)
        assert sum(map(len, cells)) == len(union), copy.name
        assert min(len(cells[0] | cells[1]), len(cells[2] | cells[3])) >= 15, copy.name
        owner |= dict.fromkeys(union, index)
    for (x, y), index in owner.items():
        near = {owner.get((x + dx, y + dy), index) for dx in range(-6, 7) for dy in range(-6, 7)}
        assert near == {index}, placed[index][0].name
    bounds = [
        tuple(tuple(b + o for b, o in zip(corner, offset, strict=True)) for corner in copy.bounds())
        for copy, _, offset in placed
    ]
    for i, (lo, hi) in enumerate(bounds):
        for lo2, hi2 in bounds[i + 1 :]:
            assert any(hi[a] < lo2[a] or hi2[a] < lo[a] for a in range(3)), placed[i][0].name
    vertices, uvs, faces = obj_uvs("window-side")
    refs = [
        [tuple(int(i) - 1 for i in ref.split("/")[:2]) for ref in ln.split()[1:]] for ln in faces
    ]
    first = 0
    oblique = 0
    for copy, (oc, orow), _ in placed:
        tris = refs[first : first + 4]
        first += 4
        a_v = {v for t in tris[:2] for v, _ in t}
        b_v = {v for t in tris[2:] for v, _ in t}
        assert len(a_v & b_v) == 2 and len({vertices[v][1] for v in a_v | b_v}) == 1, copy.name
        texel = [
            [(uvs[t][0] * 512 - oc, (1 - uvs[t][1]) * 512 - orow) for _, t in tri] for tri in tris
        ]
        point = [[np.array(vertices[v])[[0, 2]] for v, _ in tri] for tri in tris]
        exact = copy.uv_exact
        written = [corner for tri in texel for corner in tri]
        assert all(
            min(math.hypot(w[0] - float(e[0]), w[1] - float(e[1])) for e in exact) < 1e-6
            for w in written
        )
        oblique += any((c * (1 << 24)) % 1 for tri in tris for _, t in tri for c in uvs[t])

        for (cx, cy), axis, f in copy.targets:
            assert (f - Fraction(1, 2)).denominator == 1, copy.name
            got = _through(texel, point, 0, 2, np.array([cx + 0.5, cy + 0.5]))[int(axis == "v")]
            assert abs(got - float(f)) < 1e-4, (copy.name, axis, got, f)
    assert oblique == len(placed)


def test_corner_copies_bend_at_v_and_put_the_target_past_the_far_edge() -> None:
    """Decision 298: each copy's triangles cover disjoint texel centres, none on an edge, F1, F2
    and B2 some, an empty B1 none; the copies lie at least 7 texels apart in UV and apart in
    3D; the target T is uncovered beside e1 with its left neighbour in F1, `across` texels from
    e1 and `reach` from V, past e2's end V; e1 and e2 meet at V bent by the copy's angle (exactly
    straight at 0); across every designed hinge the two pieces share exactly two mesh vertices
    and the written float32 positions bend the far piece by its angle, on the near piece's
    normal side exactly when it is positive; the box is [-256, 256] x [-64, 64] x [-256, 256]."""
    owner: dict[tuple[int, int], int] = {}
    placed, _ = rf.corner_layout()
    covered = 0
    for index, (copy, (oc, orow), _) in enumerate(placed):
        uv = [[(c + oc, r + orow) for c, r in uvs] for _, uvs in copy.tris]
        cells = [covered_centres(t) for t in uv]
        union = set().union(*cells)
        assert sum(map(len, cells)) == len(union), copy.name
        assert cells[0] and cells[1] and cells[-2] | cells[-1], copy.name
        if len(copy.tris) == 6:
            assert bool(cells[2] | cells[3]) == (copy.gate == "g"), copy.name
        covered += len(union)
        owner |= dict.fromkeys(union, index)
        tx, ty = oc + copy.target[0], orow + copy.target[1]
        assert (tx, ty) not in union and (tx - 1, ty) in cells[0], copy.name
        v, w1, w2 = np.array(uv[0][0]), np.array(uv[0][1]), np.array(uv[1][2])
        t = np.array([tx + 0.5, ty + 0.5]) - v
        e1, e2 = w1 - v, w2 - v
        assert np.linalg.norm(t) == pytest.approx(copy.reach, abs=1e-9), copy.name
        cross = e1[0] * t[1] - e1[1] * t[0]  # rows down: T on e1's right
        assert cross / np.linalg.norm(e1) == pytest.approx(copy.across, abs=1e-9), copy.name
        assert 0 < t @ e1 < e1 @ e1 and t @ e2 < 0, copy.name
        bend = math.degrees(math.atan2(e2[0] * e1[1] - e2[1] * e1[0], -e2 @ e1))
        assert bend == pytest.approx(copy.bend, abs=1e-9), copy.name
    assert covered == 10_767
    for (x, y), index in owner.items():
        near = {owner.get((x + dx, y + dy), index) for dx in range(-6, 7) for dy in range(-6, 7)}
        assert near == {index}, placed[index][0].name
    bounds = [
        tuple(tuple(b + o for b, o in zip(corner, offset, strict=True)) for corner in copy.bounds())
        for copy, _, offset in placed
    ]
    for i, (lo, hi) in enumerate(bounds):
        for lo2, hi2 in bounds[i + 1 :]:
            assert any(hi[a] < lo2[a] or hi2[a] < lo[a] for a in range(3)), placed[i][0].name
    vertices, uvs, faces = obj_uvs("corner-reach")
    low = tuple(min(c) for c in zip(*vertices, strict=True))
    high = tuple(max(c) for c in zip(*vertices, strict=True))
    assert (low, high) == ((-256.0, -64.0, -256.0), (256.0, 64.0, 256.0))
    refs = [[ref.split("/") for ref in line.split()[1:]] for line in faces]
    first = 0
    for copy, _, _ in placed:
        tris = [[int(r[0]) - 1 for r in t] for t in refs[first : first + len(copy.tris)]]
        if copy.bend == 0:  # e1 and e2 exactly collinear in the written UVs
            corner = [uvs[int(r[1]) - 1] for r in refs[first][:2] + refs[first + 1][2:]]
            assert len({u for u, _ in corner}) == 1, copy.name
        first += len(copy.tris)
        for inner, outer, angle in copy.hinges:
            a = {v for t in copy.faces[inner] for v in tris[t]}
            b = {v for t in copy.faces[outer] for v in tris[t]}
            assert len(a & b) == 2, (copy.name, inner, outer)
            p = [np.array(vertices[v]) for v in tris[copy.faces[inner][0]]]
            normal = np.cross(p[1] - p[0], p[2] - p[0])
            normal /= np.linalg.norm(normal)
            for t in copy.faces[outer]:
                r = [np.array(vertices[v]) for v in tris[t]]
                other = np.cross(r[1] - r[0], r[2] - r[0])
                cos = normal @ other / np.linalg.norm(other)
                bent = math.degrees(math.acos(min(cos, 1.0)))
                # Float32 rounding: up to about 3.4e-4 degree (an empty B1 is 0.375 cm deep).
                assert bent == pytest.approx(abs(angle), abs=1e-3), (copy.name, inner, outer)
            lift = max((normal @ (np.array(vertices[v]) - p[0]) for v in b - a), key=abs)
            assert (lift > 1e-4) == (angle > 0) and (lift < -1e-4) == (angle < 0), copy.name
    assert first == len(refs) - 2  # the two box anchors


def test_normal_combine_probe_separates_the_mesh_map_height_and_channel() -> None:
    """Decision 293: the two sets share four texel-aligned 48 x 48 islands, one per quadrant,
    at least 40 texels from the tile border; only uzp_nc_mesh binds the 16-bit mesh map; the
    Height has no gradient but on the right-hand islands past their top and left 24 texels; the
    channel's mask is exactly 1 on the bottom quadrants and 0 elsewhere; the mesh map's
    quadrants share no normal."""
    _, uvs, faces = obj_uvs("normal-combine")
    assert len(uvs) == 32 and len(faces) == 16
    texels = [(u * 256.0, (1.0 - v) * 256.0) for u, v in uvs]
    assert texels[:16] == texels[16:]  # the free set repeats the mesh set's UVs exactly
    for index in range(4):
        corners = texels[index * 4 : index * 4 + 4]
        x0, y0 = rf.combine_island(index % 2, index // 2)
        assert {c for c, _ in corners} == {x0, x0 + 48} and {r for _, r in corners} == {y0, y0 + 48}
        assert min(x0, y0) >= 40 and max(x0, y0) + 48 <= 216
    steps = padding_normal_combine_probe().sequence.steps
    bound = [s["args"] for s in steps if s["call"].endswith("set_mesh_map_resource")]
    assert bound == [{"usage": "Normal", "resource_step": 2, "texture_set": "uzp_nc_mesh"}]

    _, _, depth, height = bitmap("normal-combine-height")
    h = np.asarray(height, np.int64).reshape(256, 256)
    assert depth == 16
    gx, gy = np.diff(h, axis=1), np.diff(h, axis=0)
    for qx in (0, 1):
        for qy in (0, 1):
            x0, y0 = rf.combine_island(qx, qy)
            ramp = qx == 1
            # Every tap a covered Sharp stencil reads (left, up), and two texels beyond, is flat
            # in the bands; past them the ramp tilts.
            assert not gx[y0 - 2 : y0 + 48, x0 - 3 : x0 + 24].any()
            assert not gy[y0 - 3 : y0 + 24, x0 - 2 : x0 + 48].any()
            assert bool(gx[y0 + 25 : y0 + 48, x0 + 24 : x0 + 47].all()) == ramp
            assert bool(gy[y0 + 24 : y0 + 47, x0 + 25 : x0 + 48].all()) == ramp
    _, _, _, mask = bitmap("normal-combine-mask")
    m = np.asarray(mask, np.int64).reshape(256, 256)
    assert (m[:128] == 0).all() and (m[128:] == 65535).all()
    _, _, depth, mesh_map = bitmap("normal-combine-mesh-map")
    f = np.asarray(mesh_map, np.int64).reshape(256, 256, 3)
    assert depth == 16
    quadrants = [
        {tuple(t) for t in f[r : r + 128, c : c + 128].reshape(-1, 3)}
        for r in (0, 128)
        for c in (0, 128)
    ]
    assert all(not (a & b) for i, a in enumerate(quadrants) for b in quadrants[i + 1 :])

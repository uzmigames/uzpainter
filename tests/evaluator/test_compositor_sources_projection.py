"""Tests of phase1.8_compositor-sources-projection (P1-COMPOSITOR,
`docs/architecture/04-layer-stack-and-compositing.md` §1, §4, §5; `src/evaluator/sources.h`,
`projection_uv.h`).

Native cases run `uzp-evaluator-tests.exe`: `sources` and `tables` on the CPU anywhere;
`projection-gpu-vs-cpu` and `srgb8-hardware` need the DX12 adapter and skip under `UZP_NO_GPU=1`
(hosted CI, decision 028). The Tier 0 comparisons read the private oracle store through
`tools.parity` and skip on a machine without it; the local run report
(`parity/reports/phase1/compositor-sources-projection.md`) is their evidence. Every comparison is
value for value against both recordings (CONTRACT §3: no tolerance).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.evaluator.test_compositor_tile_dag import (
    MANIFESTS,
    backends,
    evaluate,
    needs_store,
    raster,
    run_case,
    spec_from_manifest,
)
from tests.evaluator.union_run import observe
from tests.export.encoders_tier0 import LIFTED_COLOUR_SETS
from tools.parity.fit.oracle import Golden
from tools.parity.schemas import load_json

RAMP_SETS = 24
RESAMPLE_SETS = {"s0": "BilinearHQ", "s1": "BilinearSharp", "s2": "Nearest", "s3": "BilinearHQ"}


# ── Native cases ─────────────────────────────────────────────────────────────


def test_sources_on_the_cpu(evaluator_tests: Path) -> None:
    """2.1-2.4, 3.5: fill sources on every channel format, the UV transform, filters and wrap
    modes, LAY-13 bindings, explicit failures and the resolution in the cache keys."""
    passed, _ = run_case(evaluator_tests, "sources")
    for bits, kind, formats in (
        ("16", "colour", "three-channel format"),
        ("8", "colour", "three-channel format"),
        ("16", "grey", "channel format"),
    ):
        for name in ("BilinearHQ", "BilinearSharp", "Nearest"):
            assert (
                f"a 1:1 {bits}-bit {kind} bitmap under {name} stores each code as a linear value "
                f"with the write rule of every {formats}"
            ) in passed
    # A colour bitmap on a one-channel tile: P20-A's grey texture, else refused (decision 218).
    assert {
        "a colour bitmap on an L8 or L16F channel is read as the binary16 of its texels' mean "
        "(decision 218)",
        "a colour bitmap on a one-channel tile outside P20-A (another format, 16-bit, Nearest, "
        "minified) fails with unsupported_source naming item 2.9 (decision 218)",
    } <= set(passed)
    assert {
        "the Fill projection matches the bitmap to the UV tile (a 1:1 copy)",
        "Nearest: a whole-texel offset with Repeat moves the bitmap towards +u and +v, wrapping",
        "BilinearHQ: a whole-texel offset with Repeat moves the bitmap towards +u and +v, wrapping",
        "Nearest at scale 0.5 magnifies the centre of the bitmap by two",
        "BilinearHQ half a texel off weighs both texels 128/256 through the GPU's linear filter "
        "and stores it with the write rule",
        "the bilinear filter aligns the weighed texels to the largest one's exponent with 28 bits "
        "(the resample-uv near-tie rounds down; a 256/256 texel is unchanged)",
        "RepeatNone leaves the texels outside the UV square to the value below the fill",
        "RepeatHorizontally wraps along u and leaves the texels outside [0, 1) in v uncovered",
        "Nearest with a 90 degree rotation turns the bitmap a quarter turn about the UV centre",
        "bilinear minification at rotations 0, 90, 180 and 270 evaluates through the texture unit",
        "bilinear minification at a rotation that is not a multiple of 90 degrees fails with "
        "unsupported_source (release gap)",
        "bilinear minification of a bitmap that is not square fails with unsupported_source "
        "(release gap)",
        "Nearest evaluates at any scale",
        "a physical-size scale mode fails with unsupported_source",
        "an OCIO project without Painter's substance config fails with unsupported_source",
        "under Painter's OCIO config a uniform evaluates and a Raw bitmap on an RGB16 channel "
        "fails with unsupported_source",
        "a UV projection on a non-power-of-two set fails with unsupported_source",
        "bytes that are not a PNG fail to decode with unsupported_source",
        "a resource whose bytes do not hash to its key is unavailable",
        "two fills binding different bytes under the alias M_piping each evaluate to their own "
        "bytes (LAY-13)",
        "after a resolution change the same evaluator re-evaluates every tile at the new size (no "
        "stale cache hit)",
        "on an sRGB8 channel the double-precision and the GPU's float32 sRGB decode store the "
        "same code for each of the 65 536 16-bit codes",
        "the sRGB8 decode of each 8-bit code stores the code itself",
        "a bitmap in Working or Legacy Linear is read as in Raw, in Legacy sRGB as in sRGB",
        "an sRGB bitmap on a channel that is not sRGB8, an 8-bit sRGB bitmap minified by a "
        "bilinear filter, and an unknown bitmap colour space fail with unsupported_source",
        "Nearest at a tie takes the right texel across and the upper texel down the rows",
        # phase1.15_compositor-colour-fits item 2.8 (decision 208): an L8 material channel.
        "a grey 8- or 16-bit sRGB bitmap at 1:1 on an L8 BaseColor, Specular or Emissive stores "
        "Painter's codes of export-l8-material (the IEC rounding but one code lower at 13 8-bit "
        "and 10 16-bit codes)",
        "an sRGB bitmap on an L8 material channel that is colour or resampled, and on another "
        "channel or format that is not sRGB8, fails with unsupported_source (not recorded, "
        "decision 208; Painter's refusal on a user channel, decision 174)",
    } <= passed
    # phase1.15_compositor-colour-fits items 2.2 and 2.5 (decisions 174, 203): sRGB bitmaps of
    # every kind, 1:1, magnified and under Nearest; 16-bit ones minified.
    for kind in ("16-bit colour", "8-bit colour", "16-bit grey", "8-bit grey"):
        assert (
            f"a {kind} sRGB bitmap at 1:1 stores the sRGB8 code of the sRGB decode of each code"
        ) in passed
        minified = (
            (("BilinearHQ", "2.000000"), ("BilinearSharp", "4.000000"))
            if kind.startswith("16-bit")
            else ()
        )
        for name, scale in (
            ("BilinearHQ", "1.000000"),
            ("BilinearHQ", "0.500000"),
            ("Nearest", "0.500000"),
            ("Nearest", "2.000000"),
            *minified,
        ):
            assert (
                f"a {kind} sRGB bitmap under {name} at scale {scale} stores the sRGB8 code of its "
                "projected decoded texels"
            ) in passed


def test_order_case_stores_bitmaps_on_srgb8(evaluator_tests: Path) -> None:
    """2.2: a 1:1 16-bit bitmap on an sRGB8 channel is stored through the sRGB8 conversion."""
    passed, _ = run_case(evaluator_tests, "order")
    assert (
        "a 1:1 16-bit bitmap on sRGB8 stores each code as a linear value through the sRGB8 "
        "conversion"
    ) in passed


def test_projection_kernel_equals_cpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.4: the projection kernel equals the CPU reference bit for bit on random stacks (every
    filter, wrap mode, transform, 8/16-bit grey and colour bitmap, nine formats, two tiles), and
    on sRGB bitmaps decoded to float32 texels on an sRGB8 channel (decision 174), 16-bit ones
    minified too (decision 203), on an L8 BaseColor, Specular and Emissive (decision 208), and a
    colour bitmap's grey texture on L8 and L16F (decision 218)."""
    passed, _ = run_case(evaluator_tests, "projection-gpu-vs-cpu", str(tmp_path), needs_gpu=True)
    assert any(p.startswith("every random projection stack") for p in passed)
    assert any(p.startswith("every random minifying projection stack") for p in passed)
    assert any(p.startswith("every random sRGB projection stack") for p in passed)
    assert any(p.startswith("every random minifying 16-bit sRGB projection stack") for p in passed)
    assert any(
        p.startswith("a grey 8- and 16-bit sRGB bitmap at 1:1 on an L8 BaseColor, Specular and")
        for p in passed
    )
    assert any(
        p.startswith("a colour 8-bit bitmap magnified on an L8 and an L16F channel evaluates to")
        for p in passed
    )
    assert (
        "GPU: after a resolution change the same evaluator re-evaluates at the new size" in passed
    )
    assert {
        "GPU: after a legacy evaluation an OCIO evaluation of an sRGB bitmap at scale 2 fails as "
        "on a fresh evaluator (no stale cache hit)",
        "GPU: after a legacy evaluation an OCIO evaluation of a Raw bitmap at 1:1 stores the OCIO "
        "codes of a fresh evaluator, not the legacy ones",
    } <= passed


@pytest.mark.parametrize(
    ("stem", "texture_set"),
    [(stem, s) for stem, sets in LIFTED_COLOUR_SETS.items() for s in sets],
)
def test_lifted_colour_fits_gpu_equals_cpu(
    evaluator_tests: Path, tmp_path: Path, stem: str, texture_set: str
) -> None:
    """phase1.15_compositor-colour-fits items 3.1 and 4.1: every texture set whose files the
    colour fits made byte-identical to Painter's on the CPU store (decisions 145, 152, 174, 190
    and 208; `tests/export/test_export_encoders.py`), its spec as `WriteExport` evaluates it, gives
    the same bytes on the DX12 store as on the CPU store in every channel of its stack."""
    from tests.export.encoders_tier0 import lifted_colour_spec

    needs_store()
    spec = lifted_colour_spec(stem, texture_set, tmp_path)
    cpu = evaluate(evaluator_tests, spec, tmp_path, "cpu")
    gpu = evaluate(evaluator_tests, spec, tmp_path, "gpu")
    assert sorted(cpu["channels"]) == sorted(gpu["channels"]) == sorted(spec["outputs"])
    for channel in spec["outputs"]:
        assert raster(gpu, channel).shape == raster(cpu, channel).shape, channel
        ours, theirs = (
            np.frombuffer((Path(r["_dir"]) / r["channels"][channel]["file"]).read_bytes(), np.uint8)
            for r in (gpu, cpu)
        )
        differing = int(np.count_nonzero(ours != theirs))
        assert differing == 0, f"{stem} {texture_set} {channel}: {differing} bytes differ"


def test_bilinear_filter_equals_the_gpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.1: `BilinearFilter` (projection_uv.h) is the GPU's linear filter of float32 texels,
    measured at every 8-bit weight pair on 64 taps and four channels (16 777 216 samples, operands
    beside 1.0 and 0 included), and the GPU rounds the `resample-uv` near-tie down as Painter
    does."""
    passed, output = run_case(evaluator_tests, "bilinear-hardware", str(tmp_path), needs_gpu=True)
    if "RTX 4090" not in output:
        pytest.skip("the bilinear filter was measured on the recording GPU (RTX 4090)")
    assert any(
        p.startswith("the GPU's linear filter of float32 texels equals BilinearFilter")
        for p in passed
    )
    assert (
        "the GPU's linear filter of float32 texels rounds the resample-uv near-tie down" in passed
    )


def test_srgb8_tables_equal_the_recording_gpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.2: the sRGB8 decode and store tables of `arith.h` are the conversions of the GPU the
    goldens were recorded on (re-measured here: owner's RTX 4090)."""
    passed, output = run_case(evaluator_tests, "srgb8-hardware", str(tmp_path), needs_gpu=True)
    if "RTX 4090" not in output:
        pytest.skip("the sRGB8 tables were measured on the recording GPU (RTX 4090)")
    assert {
        "the GPU's sRGB8 decode equals the operand table of every code",
        "the smallest float32 of every sRGB8 code on the GPU equals the store thresholds",
    } <= passed
    assert any(p.startswith("the GPU's sRGB8 encode equals Srgb8Store") for p in passed)


@pytest.fixture(scope="module")
def srgb8_decode(evaluator_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> np.ndarray:
    """The sRGB8 operand of every code (float32 values), from the `tables` case."""
    work = tmp_path_factory.mktemp("tables")
    run_case(evaluator_tests, "tables", str(work))
    document = json.loads((work / "tables.json").read_text(encoding="utf-8"))
    bits = np.asarray(document["srgb8_decode_bits"], np.uint32)
    return bits.view(np.float32).astype(np.float64)


# ── Exports ──────────────────────────────────────────────────────────────────


def write16(values: np.ndarray) -> np.ndarray:
    """The 16-bit UNORM write rule on float32 values: truncate to 20 fractional bits, nearest,
    ties down."""
    v = np.clip(values.astype(np.float32).astype(np.float64), 0.0, 1.0)
    j = np.floor(v * (1 << 20)).astype(np.int64)
    result: np.ndarray = (j * 65535 + (1 << 19) - 1) >> 20
    return result


def export16(stored: np.ndarray, fmt: str, decode: np.ndarray) -> np.ndarray:
    """What a 16-bit PNG export of a channel holds: 16-bit codes unchanged, 8-bit codes times 257,
    sRGB8 codes as their linear operand through the write rule (srgb8-export, now exact)."""
    if fmt in ("RGB16", "L16"):
        return stored
    if fmt in ("RGB8", "L8"):
        result: np.ndarray = stored * 257
        return result
    if fmt == "sRGB8":
        return write16(decode[stored])
    raise AssertionError(f"no 16-bit export rule for {fmt}")


def compare_export(
    ours: np.ndarray, fmt: str, decode: np.ndarray, golden: Golden, map_name: str
) -> None:
    expected = export16(ours, fmt, decode)
    for recording in ("r1", "r2"):
        theirs = golden.map(recording, map_name).values.astype(np.int64)
        theirs = theirs.reshape(expected.shape)
        observe(golden, map_name, recording, "16-bit code value", expected, theirs)
        differing = int(np.count_nonzero(expected != theirs))
        worst = int(np.abs(expected - theirs).max()) if differing else 0
        assert differing == 0, (
            f"{map_name} {recording} {fmt}: {differing} differing values, max |delta| {worst}"
        )


def channel_formats(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        s["args"]["channel"]: s["args"]["format"]
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"].endswith("Stack.add_channel")
    }


# ── Tier 0 goldens (owner's machine: private store, decision 028) ────────────


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("space", ["srgb", "working", "raw"])
def test_uniform_colour_ramps_equal_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, space: str, backend: str
) -> None:
    """3.1, 3.2: `colour-ramps-<space>`: 288 uniform colours per documented colour space on RGB16
    (User0-3) and sRGB8 (User4-7) channels. RGB16 stores round(v 65535); sRGB8 stores the
    recording GPU's float-to-sRGB8 conversion, and its 16-bit export is the GPU's decode through
    the write rule: every exported value equals both recordings."""
    ctx = needs_store()
    golden = ctx.golden(f"semantics/colour-ramps-{space}")
    manifest = load_json(MANIFESTS / "semantics" / f"colour-ramps-{space}.json")
    formats = channel_formats(manifest)
    users = [f"User{i}" for i in range(8)]
    for index in range(RAMP_SETS):
        texture_set = f"s{index}"
        spec = spec_from_manifest(manifest, texture_set, tmp_path / texture_set, users)
        result = evaluate(evaluator_tests, spec, tmp_path / texture_set, backend)
        for user in users:
            compare_export(
                raster(result, user),
                formats[user],
                srgb8_decode,
                golden,
                f"{texture_set}/{user.lower()}",
            )


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1"])
def test_bitmap_import_equals_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """2.3, 3.2: `blend-inputs` s0 (field A) and s1 (field B), 16-bit bitmaps holding every
    16-bit code, alone at opacity 1 on RGB16 (User0, User1), sRGB8 (User2, User3), RGB8 (User4)
    and L16 (User6, grey field): each code is taken as a linear value and stored with the
    channel's write rule. s2 (opacity 0.5) is an unstable golden (r1 and r2 differ, not admitted,
    `tier0-stability.md` §4) and is not compared."""
    ctx = needs_store()
    golden = ctx.golden("semantics/blend-inputs")
    manifest = load_json(MANIFESTS / "semantics" / "blend-inputs.json")
    formats = channel_formats(manifest)
    users = ["User0", "User1", "User2", "User3", "User4", "User6"]
    spec = spec_from_manifest(manifest, texture_set, tmp_path, users)
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    for user in users:
        compare_export(
            raster(result, user),
            formats[user],
            srgb8_decode,
            golden,
            f"{texture_set}/{user.lower()}",
        )


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", sorted(RESAMPLE_SETS))
def test_uv_projection_equals_the_golden(
    evaluator_tests: Path, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """2.4, 3.1, 3.3: `resample-uv`: the 64 x 64 pattern and the 256 x 256 field A UV-projected at
    scales 1, 0.73, 1.37 x 2.11, rotation 30, offsets (0.123, 0.456) and half a texel, with
    `BilinearHQ`/`Repeat` (s0), `BilinearSharp` (s1), `Nearest` (s2) and `BilinearHQ`/
    `RepeatNone` (s3), on RGB16. Equal value for value, the near-tie of s0 and s1 user2 (texel
    (175, 18), green: the GPU's linear filter keeps 28 bits below the largest texel's exponent,
    which puts it below the float32 midpoint) included. User6 (scale 3.3, held out of every fit)
    minifies: through the texture unit under the bilinear filters (decision 084)."""
    ctx = needs_store()
    golden = ctx.golden("semantics/resample-uv")
    manifest = load_json(MANIFESTS / "semantics" / "resample-uv.json")
    users = list(range(8))
    spec = spec_from_manifest(manifest, texture_set, tmp_path, [f"User{u}" for u in users])
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    for user in users:
        ours = raster(result, f"User{user}")
        for recording in ("r1", "r2"):
            theirs = golden.map(recording, f"{texture_set}/user{user}").values.astype(np.int64)
            observe(
                golden, f"{texture_set}/user{user}", recording, "16-bit code value", ours, theirs
            )
            differing = np.argwhere(ours != theirs)
            assert len(differing) == 0, (
                f"{texture_set}/user{user} {recording}: {len(differing)} differing values"
            )


# The minifying goldens of decisions 048 and 078 (pattern64 and impulse64 on 256 x 256 sets):
# sets s0 BilinearHQ/Repeat, s1 BilinearSharp/Repeat, s2 BilinearHQ/RepeatNone, s3
# BilinearSharp/RepeatNone; per golden the users whose rotation is not a multiple of 90 degrees
# (refused: the texture unit's rotated footprints are not modelled, decision 084).
MINIFYING = {
    "resample-uv-minify": (8, {7}),
    "resample-uv-impulse": (8, set()),
    "resample-uv-anisotropic": (10, set()),
    "resample-uv-anisotropic-impulse": (10, set()),
    "resample-uv-lod": (8, set()),
    "resample-uv-lod-boundaries": (10, set()),
    "resample-uv-rotation": (10, {0, 1, 2, 3, 4}),
}


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
@pytest.mark.parametrize("stem", sorted(MINIFYING))
def test_minification_equals_the_golden(
    evaluator_tests: Path, tmp_path: Path, stem: str, texture_set: str, backend: str
) -> None:
    """2.2, 2.3, 3.1, 4.1: bilinear minification through the recording GPU's texture unit
    (texture_unit.h) with Painter's float32 UV, BilinearSharp's bias and BilinearHQ's nine samples
    (decisions 060, 083, 084): `resample-uv-minify` and `-impulse` (isotropic footprints of 1.28 to
    4.15 texels, one anisotropic, offsets), and the validation goldens of decision 078, held out of
    every fit (anisotropic ratios 1.7 to 7.4 on both axes, isotropic LODs 0.5 to 2.5 and their
    integer boundaries for both biases, rotations by 90, 180 and 270 degrees and their rotation-0
    controls), every user channel of an axis-aligned footprint equal to both recordings, value
    for value. The other rotations are refused (the `sources` case)."""
    ctx = needs_store()
    users, refused = MINIFYING[stem]
    golden = ctx.golden(f"semantics/{stem}")
    manifest = load_json(ctx.manifests / "semantics" / f"{stem}.json")
    compared = [u for u in range(users) if u not in refused]
    spec = spec_from_manifest(manifest, texture_set, tmp_path, [f"User{u}" for u in compared])
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    for user in compared:
        ours = raster(result, f"User{user}")
        for recording in ("r1", "r2"):
            map_name = f"{texture_set}/user{user}"
            theirs = golden.map(recording, map_name).values.astype(np.int64).reshape(ours.shape)
            observe(golden, map_name, recording, "16-bit code value", ours, theirs)
            differing = int(np.count_nonzero(ours != theirs))
            worst = int(np.abs(ours - theirs).max()) if differing else 0
            assert differing == 0, (
                f"{stem} {map_name} {recording}: {differing} differing values, max |delta| {worst}"
            )


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_srgb8_evaluation_order_equals_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """3.2: the sRGB8 channel (User1) of `blend-order` (fields A Normal, B Subtract 0.8, uniform C
    Divide 0.6 in four orders), which phase1.5 could not compare without the bitmap import rule:
    every layer is stored through the sRGB8 conversion and read back through its decode."""
    ctx = needs_store()
    golden = ctx.golden("semantics/blend-order")
    manifest = load_json(MANIFESTS / "semantics" / "blend-order.json")
    spec = spec_from_manifest(manifest, texture_set, tmp_path, ["User1"])
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    compare_export(raster(result, "User1"), "sRGB8", srgb8_decode, golden, f"{texture_set}/user1")


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1"])
def test_srgb8_group_equals_the_golden(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """3.2: the sRGB8 channel (User1) of `group-masks` s0 and s1 (groups without masks)."""
    ctx = needs_store()
    golden = ctx.golden("semantics/group-masks")
    manifest = load_json(MANIFESTS / "semantics" / "group-masks.json")
    spec = spec_from_manifest(manifest, texture_set, tmp_path, ["User1"])
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    compare_export(raster(result, "User1"), "sRGB8", srgb8_decode, golden, f"{texture_set}/user1")


ISLAND_GOLDENS = {
    "height-normal-sphere": ("uzp_sphere", "sphere"),
    "height-normal-bevelled-cube": ("uzp_bevelled_cube", "bevelled-cube"),
}
MESHES = Path(__file__).resolve().parents[2] / "parity" / "fixtures" / "tier0-semantics" / "meshes"


def height_spec(manifest: dict[str, Any], texture_set: str, workdir: Path) -> dict[str, Any]:
    """The Height stack of a height-normal golden (default template: Height is L16F); layer uids
    are moved clear of the set, tile and stack ids the test project allocates."""
    spec = spec_from_manifest(manifest, texture_set, workdir, ["Height"])
    spec["channels"] = [{"type": "Height", "format": "L16F"}]
    for layer in spec["layers"]:
        layer["uid"] += 1000
    return spec


def height_raster(result: dict[str, Any]) -> np.ndarray:
    values = raster(result, "Height")
    return values[..., 0]


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_height_bitmap_equals_the_golden(
    evaluator_tests: Path, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """2.3: `height-normal-plane-amplitudes` s0-s2 (the height ramps at opacity 1, 0.5, 0.25) and
    s3 (doubled by a second fill in LinearDodge) on the grid's full quads: on the Height channel
    a bitmap value t is stored as 2 t - 1 (half toward zero) over the signed channel's base 0; the
    OpenEXR export holds it unchanged."""
    ctx = needs_store()
    golden = ctx.golden("semantics/height-normal-plane-amplitudes")
    manifest = load_json(MANIFESTS / "semantics" / "height-normal-plane-amplitudes.json")
    result = evaluate(
        evaluator_tests, height_spec(manifest, texture_set, tmp_path), tmp_path, backend
    )
    ours = height_raster(result)
    for recording in ("r1", "r2"):
        theirs = golden.map(recording, f"{texture_set}/height").values.astype(np.float64)
        theirs = theirs.reshape(ours.shape[0], ours.shape[1], -1)[..., 0]
        observe(golden, f"{texture_set}/height", recording, "float32 value", ours, theirs)
        differing = int(np.count_nonzero(ours != theirs))
        assert differing == 0, f"{texture_set}/height {recording}: {differing} differing values"


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("golden_stem", sorted(ISLAND_GOLDENS))
def test_island_edges_equal_the_golden(
    evaluator_tests: Path, tmp_path: Path, golden_stem: str, backend: str
) -> None:
    """2.5, 3.4: the height ramps on the sphere and the bevelled cube (one fill, UV projection at
    1:1). The fixture mesh is imported with the product's importer and rasterised by the render
    layer's UV raster (`uv-coverage`): on every texel whose centre a triangle covers, the evaluated
    Height equals both recordings value for value. The island-edge rule: the evaluator fills the
    whole UV tile, inside and outside the islands, and the texels outside them are export padding
    (`padding: infinite`, 08-export.md), not the stack's value."""
    ctx = needs_store()
    texture_set, mesh = ISLAND_GOLDENS[golden_stem]
    run_case(
        evaluator_tests,
        "uv-coverage",
        str(tmp_path / "coverage"),
        str(MESHES / f"{mesh}.obj"),
        "256",
        needs_gpu=True,
    )
    covered = np.fromfile(tmp_path / "coverage" / "coverage.bin", np.uint8).reshape(256, 256) == 1
    assert covered.any()
    golden = ctx.golden(f"semantics/{golden_stem}")
    manifest = load_json(MANIFESTS / "semantics" / f"{golden_stem}.json")
    result = evaluate(
        evaluator_tests, height_spec(manifest, texture_set, tmp_path), tmp_path, backend
    )
    ours = height_raster(result)
    for recording in ("r1", "r2"):
        theirs = golden.map(recording, f"{texture_set}/height").values.astype(np.float64)
        theirs = theirs.reshape(ours.shape[0], ours.shape[1], -1)[..., 0]
        observe(golden, f"{texture_set}/height", recording, "float32 value", ours, theirs, covered)
        differing = int(np.count_nonzero((ours != theirs) & covered))
        assert differing == 0, (
            f"{golden_stem} {recording}: {differing} of {int(covered.sum())} covered texels differ"
        )


# ── Published fits ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["colour-transfer.json", "uv-sampling.json"])
def test_fits_are_published_and_valid(name: str) -> None:
    """2.6: both fits exist, validate against the public schema and state exact entries only
    where every residual is zero (the guard and the publication tests of tests/parity/fit apply
    to them as to every file under parity/semantics/)."""
    from tools.parity.schemas import Schema, validation_errors

    document = load_json(Path(__file__).resolve().parents[2] / "parity" / "semantics" / name)
    assert validation_errors(document, Schema.SEMANTICS) == []
    for entry in document["entries"]:
        zero = all(r["difference"]["differing"] == 0 for r in entry["residuals"])
        if entry["status"] != "gap":
            assert (entry["status"] == "exact") == zero, entry["entry_id"]


def test_published_fits_reproduce(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.6, 4.1: the evaluator's residuals against the private goldens, re-derived on this machine,
    equal the published files byte for byte (owner's machine: store and DX12 adapter)."""
    from tests.evaluator import sources_fits

    needs_store()
    if os.environ.get("UZP_NO_GPU") == "1":
        pytest.skip("UZP_NO_GPU=1: the island-edge residuals need the UV raster (decision 028)")
    documents = sources_fits.build(evaluator_tests, tmp_path)
    for name, document in documents.items():
        published = (sources_fits.SEMANTICS / name).read_text(encoding="utf-8")
        assert sources_fits.serialise(document) == published, name

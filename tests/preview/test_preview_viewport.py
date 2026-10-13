"""Tests of phase2.1_preview-viewport-window: the `painter_viewport` pass (`src/preview/`), its
display transform and environment precomputation, and its regression goldens.

Every case runs `uzp-preview-tests.exe` (`tests/preview/preview_test.cpp`). `display`,
`environment`, `lighting-cache` and `latest` run anywhere; the viewport cases render on a DX12
device and skip under `UZP_NO_GPU=1` (hosted CI, decision 028) or when no adapter is present.

The regression goldens (`tests/preview/viewport-goldens.json`) are UzPainter-vs-UzPainter: exact
for a fixed (viewport kernel, adapter, driver) key, a repeatability check and never a tier result
or acceptance evidence (decision 018). A key the file does not hold fails with the instruction to
record it with `--bless` on the owner's machine.
"""

from __future__ import annotations

from pathlib import Path

from tests.preview.conftest import GOLDENS, run_case


def test_display_configuration_and_table(preview_tests: Path) -> None:
    """2.3, 3.4: only OCIO with Painter's substance config and `Default - sRGB` is supported;
    Legacy Linear and ACES, ACE mode, other configs and other views are refused naming decision
    038, and the preview panel labels them so (B13 of the practical end-to-end report, which saw a
    Legacy project labelled as the pinned configuration); the display table is
    round(65535 encode(binary16(clamp(L, 0, 1))))."""
    passed, _ = run_case(preview_tests, "display")
    assert {
        "the pinned configuration (OCIO, substance config, Default - sRGB) is supported",
        "the preview panel labels the pinned configuration",
        "the preview panel labels Legacy Linear as not displayed (decision 038)",
        "the preview panel labels Legacy ACES as not displayed (decision 038)",
        "the preview panel labels ACE mode as not displayed (decision 038)",
        "Legacy Linear is unsupported, naming what differs and decision 038",
        "Legacy ACES is unsupported, naming what differs and decision 038",
        "ACE mode is unsupported, naming what differs and decision 038",
        "another OCIO config is unsupported, naming what differs and decision 038",
        "another OCIO view is unsupported, naming what differs and decision 038",
        "codes of [0, 1] are round(65535 encode(L)) with the IEC 61966-2-1 encoding",
        "NaN gives 0",
        "linear 0.1 (the standard's clear colour) displays as 8-bit 89",
    } <= passed


def test_environment_precomputation(preview_tests: Path) -> None:
    """2.1: environment decoding, the iray.json direction mapping, SH irradiance of a uniform
    environment, prefiltered levels, the split-sum albedo table and repeatability."""
    passed, _ = run_case(preview_tests, "environment")
    assert {
        "a run-length encoded Radiance HDR decodes",
        "the authored sky-patch.exr decodes as a 2:1 latitude-longitude image",
        "a texel centre's direction samples that texel",
        "the SH irradiance of a uniform environment is pi L in every direction",
        "every prefiltered level of a uniform environment is that radiance",
        "a mirror (roughness 0) reflects everything: A + B = 1",
        "the importance distribution's marginal and conditional CDFs rise from 0 to 1",
        "a bright texel holds the importance distribution's mass in proportion to its light",
        "an environment without light gets the uniform distribution over the sphere",
        "the precomputation is repeatable bit for bit",
    } <= passed


def test_environment_lighting_persists_bit_for_bit(preview_tests: Path, tmp_path: Path) -> None:
    """decision 253: the persistent environment lighting (`LightingOf`) is precomputed bit for
    bit and stored cold, served warm without decoding the file, and never served from a damaged
    entry or under other MXCSR control bits (CPU)."""
    passed, _ = run_case(preview_tests, "lighting-cache", str(tmp_path))
    assert {
        "without the caches the lighting is precomputed and nothing is stored",
        "cold: the lighting is precomputed bit for bit",
        "cold: one entry is stored in the lighting area",
        "warm: the stored lighting is served bit for bit without decoding the environment file",
        "a damaged entry is not served (the file is decoded again), then recomputed bit for bit, "
        "stored and served",
        "under other MXCSR control bits the stored lighting is not served",
    } <= passed


def test_hand_over_never_waits_for_the_reader(preview_tests: Path) -> None:
    """2.4: the triple buffer between evaluation and the preview thread is wait-free; a stalled
    reader holding its frame does not delay the publisher."""
    passed, _ = run_case(preview_tests, "latest")
    assert {
        "100000 publishes complete while the reader is stalled",
        "after the stall the reader takes the newest value",
        "concurrent publishes are taken in order and the last one arrives",
    } <= passed


def test_unsupported_configuration_fails_before_rendering(
    preview_tests: Path, tmp_path: Path
) -> None:
    """3.4: Legacy Linear, Legacy ACES, ACE mode and another OCIO view fail with an error naming
    decision 038 before anything is submitted to the GPU."""
    passed, _ = run_case(preview_tests, "viewport-unsupported", str(tmp_path), gpu=True)
    assert {
        f"{name} fails before rendering (no submission) naming decision 038"
        for name in ("Legacy Linear", "Legacy ACES", "ACE mode", "another OCIO view")
    } <= passed


def test_normal_tilted_past_the_horizon_shades_continuously(
    preview_tests: Path, tmp_path: Path
) -> None:
    """Decision 256: where a normal map tilts the shading normal past the viewer's horizon, fading
    it toward the interpolated normal keeps the shade continuous (the Wand gem's thin dark lines
    were the jump of the former rule, a hard switch wherever the perturbed one faced away)."""
    passed, _ = run_case(preview_tests, "viewport-normal-fade", str(tmp_path), gpu=True)
    assert {
        "the plane covers the centre row with finite colours",
        "the shade is continuous where the perturbed normal turns past the horizon",
    } <= passed


def test_viewport_regression_goldens(preview_tests: Path, tmp_path: Path) -> None:
    """2.2, 2.6, 3.1: the sphere, plane and bevelled-cube fixtures and the concave cube on a plane
    (decision 251) render byte-identically twice, their display codes are the CPU table's, and
    they equal the stored golden of this build's (viewport kernel, adapter, driver) key."""
    passed, _ = run_case(preview_tests, "viewport-golden", str(tmp_path), str(GOLDENS), gpu=True)
    for fixture in ("sphere", "plane", "bevelled-cube", "cube-on-plane"):
        assert {
            f"{fixture}: two renders are byte-identical",
            f"{fixture}: every display code is the CPU table's code of its linear binary16 value",
            f"{fixture}: the corner shows the clear colour 0.1",
            f"{fixture}: the centre pixel shows the fixture",
            f"{fixture}: equals the stored regression golden",
        } <= passed


def test_viewport_ao_visibility(preview_tests: Path, tmp_path: Path) -> None:
    """phase2.3 item 2.5 (decision 257): the AO mesh map as a per-ray visibility weight mu^k
    inside the self-occlusion rays. UzPainter-against-UzPainter checks, never parity evidence: an
    AO map of 1 changes no pixel of any golden fixture (colour and both ratios); a flat or tilted
    normal map without AO darkens nothing (no cavity or micro-shadow term); an AO map of 0 gives
    exactly 0; the diffuse ratio is a against 1024-ray renders (also at a grazing view) and the
    shipped rays are within 0.5 / sqrt(N) of them; grazing light is attenuated and light along the
    normal kept as mu^k predicts; the specular occlusion falls with roughness and view; mirrored and
    scaled UVs sample the map as the CPU does; with the BVH, every ratio is at most each alone (the
    double darkening is reported, not bounded); an AO map never brightens a pixel; resident inputs
    render the same bytes and rebuild after Invalidate."""
    passed, _ = run_case(preview_tests, "viewport-occlusion", str(tmp_path), gpu=True)
    expected = {
        "an AO map of 1 leaves every pixel of the pass without one bit for bit (colour and both "
        "ratios, the golden fixtures and the concave one)",
        "no micro-shadow without AO or curvature: with an AO map of 1, a flat and a uniformly "
        "tilted normal map keep every diffuse and specular ratio exactly 1",
        "an AO map of 0 gives exactly 0: both ratios and the colour (dielectric and metal, three "
        "views)",
        "a = 0.3 keeps most light along the normal and almost no grazing light (micro-shadows), as "
        "mu^k over the lit texels; without AO both are kept",
        "the specular occlusion falls with roughness on a metal plane (1024 rays)",
        "the specular occlusion falls with the view angle on a metal plane (1024 rays)",
        "the shipped specular ratio with an AO map (64 rays) is within 0.5 / sqrt(64) of the "
        "1024-ray one",
        "mirrored and scaled UVs sample the AO map as the CPU does: exactly 1 and 0 where the "
        "lookup's texels agree",
        "the AO weight and the BVH meet per ray: with both, every ratio is at most each one alone "
        "(the overlap sizes are reported)",
        "an AO map never brightens a pixel: colour and both ratios are at most those without it "
        "(studio light, dielectric and metal)",
        "resident inputs give the bytes of a render without them, and a second render of the scene "
        "reuses them",
        "after Invalidate, the next resident render rebuilds its inputs and shows the changed AO "
        "map",
    }
    for a in ("0.25", "0.50", "0.75"):
        expected |= {
            f"a = {a}: a 1024-ray render's diffuse ratio is a within 0.01 on the open plane (the "
            "AO weight's cosine-weighted mean)",
            f"a = {a}: the 128-ray diffuse ratio is within 0.5 / sqrt(128) of the 1024-ray one",
            f"a = {a}: at a grazing view the diffuse ratio is still a within 0.01",
        }
    assert expected <= passed


def test_viewport_cavity(preview_tests: Path, tmp_path: Path) -> None:
    """phase2.3 item 2.6 (decision 258): the normal map's cavity, kappa = trace(J^-1 D) and
    a_cav the mean of 1 / (1 + r max(0, kappa)) over the pixel footprint's points, r = 0.25 mm.
    UzPainter-against-UzPainter checks on analytic fixtures, never parity evidence: without a
    normal map it is not computed; flat,
    uniformly tilted and convex normal maps change no byte; kappa is the closed-form Laplacian of
    a sinusoidal and a steep cylindrical groove, and the clamped slope's derivative where n.z <
    0.3; it does not change with resolution, texel density, mirrored, rotated or sheared UVs or
    across a seam; the radius is a world length; it never brightens a pixel and darkens a metal at
    least by a_cav; minified, it neither aliases into speckle nor loses the crease to its
    shoulders."""
    passed, _ = run_case(preview_tests, "viewport-cavity", str(tmp_path), gpu=True)
    assert {
        "without a normal map the cavity is not computed (the golden fixtures without one), and "
        "with one it is",
        "a flat, a uniformly tilted and a convex normal map give a_cav exactly 1 and the bytes of "
        "the pass with the cavity off (colour and both ratios, dielectric and metal)",
        "a sinusoidal groove: kappa is the closed-form Laplacian within 1 % of its peak, and "
        "a_cav darkens the groove as 1 / (1 + r kappa) with r = 0.25 mm",
        "a cylindrical groove with steep walls (n.z down to 0.44): kappa is the closed-form "
        "Laplacian within 3 %",
        "the slope clamp at n.z = 0.3: on a sinusoid of peak slope 5, kappa is the clamped "
        "slope's derivative where the clamp holds every tap (within 1 % of the peak) and the "
        "closed form (within 2 %) where the slope stays below 2.5",
        "the cavity does not change with the map's resolution, the texel density, mirrored, "
        "rotated or sheared UVs, or across a UV seam: kappa within the bound and a_cav within 0.01",
        "the radius is 0.25 mm in the world: a mesh that states centimetres gives the a_cav of "
        "the same groove without a unit, read in metres",
        "the cavity never brightens a pixel (colour and both ratios at most those with it off) and "
        "darkens a metal's colour at least by a_cav within the binary16 rounding (studio light)",
        "minified, the cavity's high-pass energy stays within twice (plus 0.005) that of a "
        "supersampled reference",
        "minified, the cavity keeps at least three quarters of a supersampled reference's "
        "high-pass energy and mean darkening (a crease and its convex shoulders in one footprint "
        "do not cancel)",
    } <= passed


def test_viewport_self_occlusion(preview_tests: Path, tmp_path: Path) -> None:
    """phase2.3 item 2.4 (decision 251): ray-traced self-occlusion. UzPainter-against-UzPainter
    checks, never parity evidence: a closed box renders exactly 0 (every ray valid and blocked);
    the BVH's visibility of every ray equals a CPU cast against all triangles; a thin gap blocks at
    twice the origin offset and leaks at half of it (documented); rays through shared edges are
    blocked; the cube shadows the plane, another texture set, where geometry predicts and the
    umbra is darker; a two-colour environment gives per-channel ratios; flat and convex surfaces
    never shadow themselves; the estimator converges to a 1024-ray render and is within
    0.5 / sqrt(N) of it; the BVH is built once per geometry."""
    passed, _ = run_case(preview_tests, "viewport-visibility", str(tmp_path), gpu=True)
    assert {
        "closed box: every pixel renders exactly 0 (every visibility ray valid and blocked)",
        "closed box without visibility rays: every pixel is lit (the 0 comes from the rays)",
        "a depth cap makes leaves at the cap that still hold every triangle once",
        "at y = 1 an occluder twice the origin offset above blocks",
        "at y = 0 an occluder twice the origin offset above blocks",
        "at y = 1 an occluder at half the origin offset leaks (documented)",
        "at y = 0 an occluder at half the origin offset leaks (documented)",
        "every ray through a shared edge or corner of a closed box is blocked (watertight)",
        "the cube (texture set 1) shadows the plane (texture set 0) where geometry predicts: the "
        "diffuse ratio is below 0.3 in the umbra and above 0.7 where the sun is in view",
        "an occluded point is darker: the umbra's mean colour is below half the lit plane's",
        "a two-colour environment gives per-channel ratios: beside a wall that hides the red half, "
        "the red ratio falls below 0.5 while the blue one stays above 0.98",
        "no self-shadowing: on a plane (with and without a uniformly tilted normal map) and on the "
        "sphere every diffuse and specular ratio is exactly 1 at grazing and steep views",
        "the diffuse ratio converges: four times the rays at least nearly halve its RMSE against "
        "a 1024-ray render of the same estimator",
        "the specular ratio converges: four times the rays at least nearly halve its RMSE against "
        "a 1024-ray render of the same estimator",
        "the diffuse ratio's RMSE against a 1024-ray render of the same estimator is within "
        "0.5 / sqrt(N) on the occluded pixels",
        "the specular ratio's RMSE against a 1024-ray render of the same estimator is within "
        "0.5 / sqrt(N) on the occluded pixels",
        "a new mesh object of the same geometry reuses its BVH; another geometry builds one",
    } <= passed
    for fixture in ("cube-on-plane", "sphere", "closed box"):
        assert {
            f"{fixture}: the BVH holds every triangle once, bounds its contents and is within the "
            "depth cap",
            f"{fixture}: the BVH's visibility of every ray equals a CPU cast against every "
            "triangle",
        } <= passed

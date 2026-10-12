"""Tests of phase2.1_preview-viewport-window: the `painter_viewport` pass (`src/preview/`), its
display transform and environment precomputation, and its regression goldens.

Every case runs `uzp-preview-tests.exe` (`tests/preview/preview_test.cpp`). `display`,
`environment` and `latest` run anywhere; the viewport cases render on a DX12 device and skip under
`UZP_NO_GPU=1` (hosted CI, decision 028) or when no adapter is present.

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
    038; the display table is round(65535 encode(binary16(clamp(L, 0, 1))))."""
    passed, _ = run_case(preview_tests, "display")
    assert {
        "the pinned configuration (OCIO, substance config, Default - sRGB) is supported",
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
        "the precomputation is repeatable bit for bit",
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


def test_viewport_regression_goldens(preview_tests: Path, tmp_path: Path) -> None:
    """2.2, 2.6, 3.1: the sphere, plane and bevelled-cube fixtures render byte-identically twice,
    their display codes are the CPU table's, and they equal the stored golden of this build's
    (viewport kernel, adapter, driver) key."""
    passed, _ = run_case(preview_tests, "viewport-golden", str(tmp_path), str(GOLDENS), gpu=True)
    for fixture in ("sphere", "plane", "bevelled-cube"):
        assert {
            f"{fixture}: two renders are byte-identical",
            f"{fixture}: every display code is the CPU table's code of its linear binary16 value",
            f"{fixture}: the corner shows the clear colour 0.1",
            f"{fixture}: the centre pixel shows the fixture",
            f"{fixture}: equals the stored regression golden",
        } <= passed

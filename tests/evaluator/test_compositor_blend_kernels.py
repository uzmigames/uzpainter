"""Tests of phase1.10_compositor-blend-kernels (P1-COMPOSITOR,
`docs/architecture/04-layer-stack-and-compositing.md` §3; `src/evaluator/arith.cpp`,
`src/evaluator/hwmath.h`, `src/evaluator/shaders/evaluator_blend.hlsl`).

The native `arith` case runs anywhere; `fp-hardware` and the GPU backend need a DX12 adapter
(decision 028). The Tier 0 comparisons read the private oracle store through `tools.parity` and
skip on a machine without it; the local run report
(`parity/reports/phase1/compositor-blend-kernels.md`) is their evidence. The blend sweeps are
stable goldens (r1 equals r2), so an exact mode equals both recordings value for value (CONTRACT
§3: no tolerance). A mode that is not exact is a release gap: its residuals must equal the
published ones (`parity/semantics/blend-kernels.json`), it is never reported exact, and its
capability entry stays `release-gap` (no exception is in force).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.evaluator import blend_fits
from tests.evaluator.quantisation_fits import exported
from tests.evaluator.sources_fits import channel_formats, pooled
from tests.evaluator.sources_fits import srgb8_decode as decode_table
from tests.evaluator.test_compositor_tile_dag import (
    MANIFESTS,
    REPO_ROOT,
    backends,
    evaluate,
    needs_store,
    run_case,
    spec_from_manifest,
)
from tools.parity.fit.common import residual
from tools.parity.schemas import load_json

PUBLISHED = blend_fits.SEMANTICS / blend_fits.FILE
INVENTORY = REPO_ROOT / "tools" / "capabilities" / "painter-api-inventory.json"
# phase1.11_compositor-blend-gaps made the normal-map modes exact at every opacity and fitted
# PassThrough on its UI-set golden; the component modes keep one-code residuals.
RELEASE_GAPS = set(blend_fits.COMPONENT_MODES)


def published() -> dict[str, Any]:
    document: dict[str, Any] = load_json(PUBLISHED)
    return document


def published_entry(mode: str) -> dict[str, Any]:
    for item in published()["entries"]:
        if item["entry_id"] == f"kernel-{mode.lower()}":
            found: dict[str, Any] = item
            return found
    raise AssertionError(f"no published entry for {mode}")


@pytest.fixture(scope="module")
def srgb8_decode(evaluator_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> np.ndarray:
    return decode_table(evaluator_tests, tmp_path_factory.mktemp("tables"))


@pytest.fixture(scope="module")
def runs(evaluator_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> blend_fits.Runs:
    needs_store()
    return blend_fits.Runs(evaluator_tests, tmp_path_factory.mktemp("blend"))


# ── Native cases ─────────────────────────────────────────────────────────────


def test_every_documented_mode_has_a_kernel(evaluator_tests: Path) -> None:
    """2.2: every BlendingMode but PassThrough (a group placement) has a kernel; Tint evaluates."""
    passed, _ = run_case(evaluator_tests, "arith")
    assert "every documented BlendingMode but PassThrough has a kernel (31 of 32)" in passed
    passed, _ = run_case(evaluator_tests, "order")
    assert "a non-separable blend mode (Tint) evaluates" in passed


def test_hardware_arithmetic_tables_equal_the_gpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.1, 2.2: the embedded reciprocal, square root and reciprocal square root tables equal the
    recording GPU on every float32 of their domains, and hw::Rcp/Sqrt/Rsqrt equal it on edge values
    and 2^20 bit patterns over every exponent (owner's machine: the RTX 4090 the goldens were
    recorded on)."""
    passed, output = run_case(evaluator_tests, "fp-hardware", str(tmp_path), needs_gpu=True)
    if "RTX 4090" not in output:
        pytest.skip("the hardware tables describe the RTX 4090 the Tier 0 goldens were recorded on")
    assert {
        "every measured result lies within -2 and +1 units in the last place of the correctly "
        "rounded one",
        "the embedded rcp table equals the GPU on every entry of its domain (8388608)",
        "the embedded sqrt table equals the GPU on every entry of its domain (16777216)",
        "the embedded rsqrt table equals the GPU on every entry of its domain (16777216)",
    } <= passed
    assert any(p.startswith("hw::Rcp, hw::Sqrt and hw::Rsqrt equal the GPU") for p in passed)


# ── Tier 0 goldens (owner's machine: private store, decision 028) ────────────


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("mode", blend_fits.MODES)
def test_blend_sweep_equals_the_golden(
    runs: blend_fits.Runs, srgb8_decode: np.ndarray, mode: str, backend: str
) -> None:
    """3.1, 4.1: field B over field A in `mode` on RGB16 (opacity 1 and 0.5), sRGB8 (1 and 0.5),
    RGB8, RGB16F, L16 (grey fields) and RGB32F (0.25), and on the Normal channel for the
    normal-map modes. An exact mode equals both recordings value for value; a release-gap mode
    reproduces its published residuals exactly and is not reported exact."""
    compared = blend_fits.comparisons(runs, srgb8_decode, mode, backend)
    if mode in RELEASE_GAPS:
        item = published_entry(mode)
        assert item["status"] != "exact"
        ours = [residual(g, m, r, u, pooled([(a, b)])) for g, m, r, u, a, b in compared]
        assert ours == item["residuals"], f"{mode}: residuals moved from the published fit"
        return
    for golden_id, map_name, recording, _, a, b in compared:
        equal = (a == b) | (np.isnan(a) & np.isnan(b))
        differing = int(np.count_nonzero(~equal))
        assert differing == 0, (
            f"{mode} {golden_id} {map_name} {recording}: {differing} values differ"
        )


# Channel of the blend sweeps -> the mode the per-channel test gives it (its golden: that
# mode's sweep).
PER_CHANNEL = {
    "User0": "Multiply",
    "User2": "Divide",
    "User4": "ColorBurn",
    "User5": "Screen",
    "User6": "SoftLight",
}


@pytest.mark.parametrize("backend", backends())
def test_per_channel_modes_of_one_layer_equal_their_goldens(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, backend: str
) -> None:
    """3.2: one upper layer with a different mode per channel (Multiply on RGB16, Divide on sRGB8
    as on BaseColor, ColorBurn on RGB8, Screen on RGB16F, SoftLight on the grey L16 channel as on
    Roughness) at each channel's own opacity: every channel equals the Tier 0 map recorded with
    its mode. No Tier 0 golden records different modes on one layer; the sweeps share their
    inputs and per-channel opacities, so each channel's golden is the sweep of its mode."""
    ctx = needs_store()
    manifest = load_json(MANIFESTS / "semantics" / "blend-basic.json")
    formats = channel_formats(manifest)
    spec = spec_from_manifest(manifest, "s0", tmp_path, list(formats))
    upper = spec["layers"][0]
    for channel, mode in PER_CHANNEL.items():
        upper["blending"][channel]["mode"] = mode
    modes = {upper["blending"][c]["mode"] for c in formats}
    assert len(modes) >= len(set(PER_CHANNEL.values())), "the layer mixes modes per channel"
    result = evaluate(evaluator_tests, spec, tmp_path, backend)
    for channel, mode in PER_CHANNEL.items():
        stem, texture_set = blend_fits.SWEEPS[mode]
        ours = exported(result, channel, formats[channel], srgb8_decode)
        for recording in ("r1", "r2"):
            theirs = ctx.golden(f"semantics/{stem}").map(
                recording, f"{texture_set}/{channel.lower()}"
            )
            values = theirs.values.reshape(ours.shape).astype(ours.dtype)
            differing = int(np.count_nonzero(ours != values))
            assert differing == 0, f"{channel} {mode} {recording}: {differing} values differ"


# ── Published fit ────────────────────────────────────────────────────────────


def test_fit_names_a_public_source_and_a_residual_per_mode() -> None:
    """2.3, 3.3, 2.4: one entry per documented BlendingMode, each citing a public source and
    giving its residuals (PassThrough: none, a gap); `exact` exactly where every residual is zero;
    the modes not exact are the release gaps and remain `release-gap` in the capability
    inventory."""
    from tools.parity.schemas import Schema, validation_errors

    document = published()
    assert validation_errors(document, Schema.SEMANTICS) == []
    inventory = load_json(INVENTORY)
    prefix = "substance_painter.layerstack.BlendingMode."
    documented = {
        e["symbol"][len(prefix) :] for e in inventory["entries"] if e["symbol"].startswith(prefix)
    }
    assert len(documented) == 32
    entries = {e["entry_id"]: e for e in document["entries"]}
    assert set(entries) == {f"kernel-{m.lower()}" for m in documented}
    not_exact = set()
    for mode in documented:
        item = entries[f"kernel-{mode.lower()}"]
        assert item["public_sources"], mode
        if mode != "PassThrough":
            assert item["residuals"], mode
        zero = bool(item["residuals"]) and all(
            r["difference"]["differing"] == 0 for r in item["residuals"]
        )
        assert (item["status"] == "exact") == zero, mode
        if item["status"] != "exact":
            not_exact.add(mode)
    assert not_exact == RELEASE_GAPS
    statuses = {
        e["symbol"][len(prefix) :]: e["status"]
        for e in inventory["entries"]
        if e["symbol"].startswith(prefix)
    }
    for mode in not_exact:
        assert statuses[mode] == "release-gap", mode


def test_published_fit_reproduces(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.3, 4.1: the residuals against the private goldens, re-derived on this machine, equal the
    published file byte for byte (owner's machine: store)."""
    needs_store()
    document = blend_fits.build(evaluator_tests, tmp_path)
    assert blend_fits.serialise(document) == PUBLISHED.read_text(encoding="utf-8")

"""Tests of phase1.9_compositor-quantisation-profile and phase1.10_compositor-float32-residual
(P1-COMPOSITOR, `docs/architecture/04-layer-stack-and-compositing.md` §4;
`src/evaluator/profile.h`).

The native `profile` case runs on the CPU anywhere. The Tier 0 comparisons read the private
oracle store through `tools.parity` and skip on a machine without it; the local run report
(`parity/reports/phase1/compositor-quantisation-profile.md`) is their evidence.

Both goldens compared here are classified unstable (`parity/reports/phase0/tier0-stability.md`):
the after-reopen recording r2 differs from the same-session recording r1 on 16 of the 36 maps
of `quantisation-thirds` and on the sRGB8 and RGB8 maps of `blend-inputs` s2. No evaluator can
equal both; under decision 032 r1 is the exact target and the register entries EXC-001 and
EXC-002 (`parity/exceptions.json`) cover the r2 comparisons. The tests below compare against r1
value for value (CONTRACT §3, §5: no tolerance); the residuals against both recordings are
published in `parity/semantics/quantisation-profile.json`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.evaluator.quantisation_fits import SEMANTICS, aliased, exported
from tests.evaluator.sources_fits import channel_formats
from tests.evaluator.sources_fits import srgb8_decode as decode_table
from tests.evaluator.test_compositor_tile_dag import (
    MANIFESTS,
    backends,
    evaluate,
    needs_store,
    run_case,
    spec_from_manifest,
)
from tools.parity.schemas import load_json

THIRDS = "quantisation-thirds"


@pytest.fixture(scope="module")
def srgb8_decode(evaluator_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> np.ndarray:
    """The sRGB8 operand of every code (the `tables` case)."""
    return decode_table(evaluator_tests, tmp_path_factory.mktemp("tables"))


def run_golden(
    exe: Path, stem: str, texture_set: str, workdir: Path, backend: str
) -> tuple[dict[str, str], dict[str, Any]]:
    """Evaluates `texture_set` of the Tier 0 golden `stem` (every channel) under the current
    profile; returns the channel formats and the result."""
    manifest = load_json(MANIFESTS / "semantics" / f"{stem}.json")
    formats = channel_formats(manifest)
    spec = aliased(spec_from_manifest(manifest, texture_set, workdir, list(formats)))
    return formats, evaluate(exe, spec, workdir, backend)


# ── Native case ──────────────────────────────────────────────────────────────


def test_profile_registry_dispatch_and_pinning(evaluator_tests: Path) -> None:
    """2.3 (phase1.9), 2.2 and 3.3 (phase1.10): the registry holds the provisional, the
    isolated-linear, the half-alpha and the coverage-weights profile; a project evaluates with
    the profile it records (the sRGB8 coverage tie and the 32-bit float uniform colours tell
    isolated-linear and half-alpha apart, the three 1/3 fills in 32-bit float and an sRGB8
    coverage tie below 1/2 tell half-alpha and coverage-weights apart); after a synthetic profile
    B is registered, the projects stamped layerq-linear, isolated-linear and half-alpha still
    evaluate bit for bit as before and tiles of different profiles never serve each other; an
    unregistered profile fails explicitly."""
    passed, _ = run_case(evaluator_tests, "profile")
    assert {
        "the build registers painter-12.1-layerq-linear (over the base), "
        "painter-12.1-isolated-linear (isolated root), painter-12.1-isolated-half-alpha "
        "(isolated root, binary16 sRGB8 coverage, plain 32-bit float uniform colours) and "
        "painter-12.1-isolated-coverage-weights (coverage weights, fused read-out, grey of the "
        "unrounded components, binary16 sRGB8 coverage from 1/2 up), the current profile",
        "the built-in profiles are listed first, in registration order",
        "an unregistered profile id fails with unknown_profile",
        "a registration with a malformed or taken id fails with invalid_profile (an id never "
        "changes meaning)",
        "painter-12.1-layerq-linear and painter-12.1-isolated-linear give different RGB8 codes "
        "for the three 1/3 fills (the dispatch is observable)",
        "painter-12.1-isolated-linear and painter-12.1-isolated-half-alpha differ on the sRGB8 "
        "coverage tie and on the 32-bit float uniform colours",
        "painter-12.1-isolated-half-alpha and painter-12.1-isolated-coverage-weights differ on "
        "the three 1/3 fills in 32-bit float and on the sRGB8 coverage tie below 1/2",
        "a synthetic profile painter-12.1-synthetic-b registers",
        "after profile B is registered, the projects stamped painter-12.1-layerq-linear, "
        "painter-12.1-isolated-linear and painter-12.1-isolated-half-alpha evaluate with their "
        "own profiles: their results are unchanged bit for bit (same evaluator and a fresh one)",
        "those projects are still served by their own cached tiles",
        "a project stamped B evaluates with B's rules (here those of painter-12.1-isolated-linear)",
        "tiles of different profiles never serve each other (subtree hashes are seeded by the "
        "profile)",
        "a project stamped with an unregistered profile fails with unknown_profile",
    } <= passed
    for fmt in ("RGB8", "sRGB8", "RGB32F"):
        assert (
            f"{fmt}: a project stamped painter-12.1-isolated-linear evaluates its root isolated, "
            "composited over the base at read-out"
        ) in passed
        assert (
            f"{fmt}: a project stamped painter-12.1-isolated-half-alpha evaluates its root "
            "isolated, the sRGB8 coverage written through binary16 and 32-bit float uniform "
            "colours plain"
        ) in passed
        assert (
            f"{fmt}: a project stamped painter-12.1-isolated-coverage-weights evaluates its "
            "layers with the coverage weights, its read-out fused and the sRGB8 coverage through "
            "binary16 from 1/2 up"
        ) in passed


def test_new_projects_are_stamped_with_the_current_profile() -> None:
    """The store stamps new (census) projects with the id of `evaluator::kCurrentProfile`; it
    spells the id out because the store does not depend on the evaluator."""
    src = Path(__file__).resolve().parents[2] / "src"
    header = (src / "evaluator" / "profile.h").read_text(encoding="utf-8")
    current = re.search(r"kCurrentProfile = (\w+);", header)
    assert current is not None
    value = re.search(rf'{current.group(1)} = "([^"]+)";', header)
    assert value is not None and value.group(1) == "painter-12.1-isolated-coverage-weights"
    census = (src / "store" / "census.cpp").read_text(encoding="utf-8")
    assert re.findall(r'evaluator_profile = "([^"]+)";', census) == [value.group(1)]


# ── Tier 0 goldens (owner's machine: private store, decision 028) ────────────


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_three_third_opacity_fills_equal_the_same_session_recording(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, texture_set: str, backend: str
) -> None:
    """2.1, 3.1, 3.2: `quantisation-thirds` (three uniform fills at opacity 1/3, one channel per
    ChannelFormat member). Under the current profile every map equals r1 value for value: sRGB8
    (blended on linear values), RGB8, RGB16, RGB16F, L8, L16, L16F and, with the coverage
    weights, the fused read-out and the grey of the unrounded components (phase1.10), RGB32F and
    L32F."""
    ctx = needs_store()
    golden = ctx.golden(f"semantics/{THIRDS}")
    formats, result = run_golden(evaluator_tests, THIRDS, texture_set, tmp_path, backend)
    for channel, fmt in formats.items():
        ours = exported(result, channel, fmt, srgb8_decode)
        theirs = golden.map("r1", f"{texture_set}/{channel.lower()}").values
        theirs = theirs.reshape(ours.shape).astype(ours.dtype)
        for component in range(ours.shape[-1]):
            a, b = ours[..., component], theirs[..., component]
            differing = int(np.count_nonzero(a != b))
            assert differing == 0, (
                f"{texture_set}/{channel} ({fmt}) component {component}: {differing} values "
                f"differ from r1, max |delta| {float(np.abs(a - b).max())}"
            )


@pytest.mark.parametrize("backend", backends())
def test_half_opacity_layer_over_the_base_equals_the_same_session_recording(
    evaluator_tests: Path, srgb8_decode: np.ndarray, tmp_path: Path, backend: str
) -> None:
    """2.1, 3.2: `blend-inputs` s2, fields A at opacity 0.5 over the white base: every channel
    (RGB16, sRGB8 on linear values, RGB8, RGB16F, L16, RGB32F) equals r1 value for value. The
    isolated root's coverage is stored in the channel format (32767/65535 on 16 bits), so every
    exact tie of the read-out goes up, as recorded; per-layer quantisation over the base sends
    them down."""
    ctx = needs_store()
    golden = ctx.golden("semantics/blend-inputs")
    formats, result = run_golden(evaluator_tests, "blend-inputs", "s2", tmp_path, backend)
    for channel, fmt in formats.items():
        ours = exported(result, channel, fmt, srgb8_decode)
        theirs = golden.map("r1", f"s2/{channel.lower()}").values
        theirs = theirs.reshape(ours.shape).astype(ours.dtype)
        differing = int(np.count_nonzero(ours != theirs))
        assert differing == 0, f"s2/{channel} ({fmt}): {differing} values differ from r1"


# ── Published fit ────────────────────────────────────────────────────────────


def test_fit_is_published_and_valid() -> None:
    """2.4: the fit exists, validates against the public schema, names the selected profile and
    states `exact` only where every residual is zero."""
    from tools.parity.schemas import Schema, validation_errors

    document = load_json(SEMANTICS / "quantisation-profile.json")
    assert validation_errors(document, Schema.SEMANTICS) == []
    ids = [e["entry_id"] for e in document["entries"]]
    assert ids == [
        "quantisation-isolated-coverage-weights",
        "quantisation-isolated-half-alpha",
        "quantisation-isolated-root",
        "quantisation-over-base",
    ]
    for entry in document["entries"]:
        zero = all(r["difference"]["differing"] == 0 for r in entry["residuals"])
        assert (entry["status"] == "exact") == zero, entry["entry_id"]
    selected = {p["name"]: p["value"] for p in document["entries"][0]["parameters"]}
    assert selected["evaluator_profile"] == "painter-12.1-isolated-coverage-weights"


def test_published_fit_reproduces(evaluator_tests: Path, tmp_path: Path) -> None:
    """2.4, 4.1: the residuals against the private goldens, re-derived on this machine, equal the
    published file byte for byte (owner's machine: store)."""
    from tests.evaluator import quantisation_fits

    needs_store()
    document = quantisation_fits.build(evaluator_tests, tmp_path)
    published = (quantisation_fits.SEMANTICS / quantisation_fits.FILE).read_text(encoding="utf-8")
    assert quantisation_fits.serialise(document) == published

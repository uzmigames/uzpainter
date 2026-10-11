"""Tests of phase1.13_compositor-diagnostics (P1-COMPOSITOR,
`docs/architecture/04-layer-stack-and-compositing.md` §8; `src/evaluator/diagnostics.h`; LAY-09,
LAY-14, EXP-04, DIA-01; decisions 075 and 076).

The native cases run `uzp-evaluator-tests.exe` (`tests/evaluator/evaluator_test.cpp`):
`diagnostics` on the CPU anywhere; `diagnostics-gpu-vs-cpu` needs the DX12 adapter and skips under
`UZP_NO_GPU=1` (hosted CI, decision 028). The region statistics are recomputed here, independently
of the C++ code, from the map and mask the native case writes: the correctly rounded sum
(`math.fsum`) and the linear percentile rule in Python floats.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

from tests.evaluator.test_compositor_tile_dag import run_case

INSIDE = 0.5


@pytest.fixture(scope="module")
def diagnostics_run(
    evaluator_tests: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[set[str], Path]:
    """The `diagnostics` case, run once: its passed checks and its work directory."""
    workdir = tmp_path_factory.mktemp("diagnostics")
    passed, _ = run_case(evaluator_tests, "diagnostics", str(workdir))
    return passed, workdir


def has(passed: set[str], prefix: str) -> bool:
    """Whether a passed check starts with `prefix`."""
    return any(p.startswith(prefix) for p in passed)


def floats(bits: list[int]) -> list[float]:
    """float32 values from their bit patterns (as doubles)."""
    return [struct.unpack("<f", struct.pack("<I", b))[0] for b in bits]


def percentile(ordered: list[float], q: float) -> float:
    """The linear rule (Hyndman and Fan 7): h = (n - 1) q, x[i] + (h - i)(x[i + 1] - x[i])."""
    h = (len(ordered) - 1) * q
    i = math.floor(h)
    if i + 1 >= len(ordered):
        return ordered[i]
    return ordered[i] + (h - i) * (ordered[i + 1] - ordered[i])


def stats_of(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": math.fsum(values) / len(values),
        "p10": percentile(ordered, 0.1),
        "p50": percentile(ordered, 0.5),
        "p90": percentile(ordered, 0.9),
    }


def region_stats(
    width: int, height: int, components: int, values: list[float], mask: list[float]
) -> dict[str, Any]:
    """The statistics of `values` over the texels whose mask is at least 1/2."""
    texels = width * height
    inside = [t for t in range(texels) if mask[t] >= INSIDE]
    per_component = [[values[t * components + c] for t in inside] for c in range(components)]
    luminance: dict[str, float] | None = None
    saturation: dict[str, float] | None = None
    if components == 3 and inside:
        lum: list[float] = []
        sat: list[float] = []
        for t in inside:
            r, g, b = values[t * 3], values[t * 3 + 1], values[t * 3 + 2]
            lum.append(((r + g) + b) / 3.0)
            high, low = max(r, g, b), min(r, g, b)
            sat.append((high - low) / high if high > 0.0 else 0.0)
        luminance, saturation = stats_of(lum), stats_of(sat)
    return {
        "texels": texels,
        "inside": len(inside),
        "coverage": len(inside) / texels,
        "mask_mean": math.fsum(mask) / texels,
        "components": [stats_of(v) for v in per_component] if inside else [],
        "luminance": luminance,
        "saturation": saturation,
    }


# ── Native cases ─────────────────────────────────────────────────────────────


def test_isolation_restores_the_prior_state(diagnostics_run: tuple[set[str], Path]) -> None:
    """2.1, 3.1: isolation evaluates a private copy of the revision: the document, its revision,
    operation records and save state are exactly as before, when the evaluation fails midway
    (tile 1 of 2) and when it succeeds."""
    passed, _ = diagnostics_run
    assert has(passed, "isolation and contribution leave the document")
    assert "isolating a node outside the stack fails with not_found" in passed


def test_contribution_is_full_minus_isolated(diagnostics_run: tuple[set[str], Path]) -> None:
    """2.2, 3.2: contribution equals the full evaluation minus the isolated one texel for texel
    on six channel formats and on both virtual normal maps; the isolated evaluation reuses the
    cache."""
    passed, _ = diagnostics_run
    assert has(passed, "contribution equals the full evaluation minus the evaluation")
    assert "an invisible node contributes exactly 0; a visible bitmap layer contributes" in passed
    assert has(passed, "isolating the top layer reuses the cached tiles")
    assert has(passed, "contribution on Normal_OpenGL and Normal_DirectX")


def test_material_views_detect_the_injected_leak(diagnostics_run: tuple[set[str], Path]) -> None:
    """2.3, 3.3: the two-material fixture: the ID view and the five channel views under B's mask,
    the injected texel of A's Roughness is the only leak; an ID spill; the nested effective mask;
    missing views and refusals."""
    passed, _ = diagnostics_run
    assert has(passed, "material_views of B on the two-material fixture")
    assert has(passed, "a mask that spills onto another ID island is an ID leak")
    assert has(passed, "a nested material's region is its effective mask")
    assert has(passed, "views the set or stack cannot give are listed as missing")
    assert has(passed, "an instance material fails with unsupported_node")


@pytest.mark.parametrize("name", ["colour", "grey", "empty"])
def test_region_stats_equal_an_independent_computation(
    diagnostics_run: tuple[set[str], Path], name: str
) -> None:
    """2.4, 3.4: region_stats equals this Python computation over the same map and mask, double
    for double."""
    passed, workdir = diagnostics_run
    assert has(passed, "region_stats counts the texels whose mask is at least 1/2")
    assert has(passed, "region_stats refuses a mask of more than one component")
    assert has(passed, "the regionStats source equals region_stats over the evaluated map")
    fixture = json.loads((workdir / f"region-stats-{name}.json").read_text(encoding="utf-8"))
    expected = region_stats(
        fixture["width"],
        fixture["height"],
        fixture["components"],
        floats(fixture["map"]),
        floats(fixture["mask"]),
    )
    assert fixture["stats"] == expected


def test_every_diagnostic_is_a_named_source(diagnostics_run: tuple[set[str], Path]) -> None:
    """2.5, 3.5: every diagnostic is a source the export plan names (round-trip, refusals), the
    named sources equal the direct diagnostics, and every output is byte-identical across runs."""
    passed, _ = diagnostics_run
    assert has(passed, "every diagnostic source name round-trips")
    assert has(passed, "malformed source names fail with not_found")
    assert has(passed, "every diagnostic output is byte-identical across two runs")
    assert has(passed, "every named source equals its direct diagnostic")


def test_diagnostics_gpu_equal_cpu(evaluator_tests: Path, tmp_path: Path) -> None:
    """3.1, 3.5 on DX12: every diagnostic source equals the CPU reference bit for bit and repeats
    byte for byte; a GPU isolation failing midway leaves the document as it was."""
    passed, _ = run_case(evaluator_tests, "diagnostics-gpu-vs-cpu", str(tmp_path), needs_gpu=True)
    assert has(passed, "every diagnostic source on the GPU equals the CPU reference")
    assert has(passed, "a GPU isolation that fails midway leaves the document")

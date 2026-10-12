"""Tests of phase1.14_compositor-core (P1-COMPOSITOR, the parent of the seven compositor children;
`docs/architecture/04-layer-stack-and-compositing.md`, `10-python-api.md` §3).

- 3.2 Repeatability lane: specs built from the public Tier 0 manifests of the current envelope
  and the public fixtures (no private store) are evaluated twice, in two separate processes of
  `uzp-evaluator-tests.exe`, and every raw channel raster (and virtual normal map) must be
  byte-identical. The CPU store runs everywhere; the GPU store needs the DX12 adapter and skips
  under `UZP_NO_GPU=1` (decision 028). Byte identity is determinism, not parity: parity is the
  union run (3.1, `tests/evaluator/union_run.py`, `parity/reports/phase1/compositor-core.md`).
- 3.3 Excluded features: the native case `not-yet-supported` (decision 082).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.evaluator.masks_fits import envelope_manifest, spec_from_steps
from tests.evaluator.quantisation_fits import aliased
from tests.evaluator.sources_fits import channel_formats
from tests.evaluator.test_compositor_height_normal import virtual_spec
from tests.evaluator.test_compositor_tile_dag import backends, evaluate, run_case

# (golden of the current envelope, texture set, outputs or None for every added channel): one or
# more sets of every child's Tier 0 golden family.
REPEATABILITY: list[tuple[str, str, list[str] | None]] = [
    ("semantics/blend-basic", "s3", None),  # Multiply on every channel format
    ("semantics/blend-basic", "s4", None),  # Divide: the hardware reciprocal
    ("semantics/blend-additive", "s5", None),  # SignedAddition
    ("semantics/blend-contrast", "s3", None),  # SoftLight: the hardware square root
    ("semantics/blend-component", "s0", None),  # Tint: the float32 hue
    ("semantics/blend-component", "s4", None),  # NormalMapCombine
    ("semantics/blend-order", "s3", None),
    ("semantics/blend-inputs", "s2", None),  # coverage weights over the base
    ("semantics/quantisation-thirds", "s0", None),
    ("semantics/colour-ramps-srgb", "s0", None),
    ("semantics/mask-precision", "s3", None),  # mask effects, 16-bit masks
    ("semantics/group-masks", "s2", None),
    ("semantics/group-coverage-order", "s1", None),
    ("semantics/levels-clamp", "s0", None),  # levels: the hardware pow
    ("semantics/resample-uv", "s0", [f"User{u}" for u in (0, 1, 2, 3, 4, 5, 7)]),  # BilinearHQ
    ("semantics/resample-uv", "s2", None),  # Nearest
    ("semantics-ui/group-passthrough-masks", "s3", None),
]
VIRTUAL: list[tuple[str, str]] = [
    ("semantics-ui/height-normal-sobel-plane-strength", "s2"),
    ("semantics/height-normal-plane-amplitudes", "s1"),
]


def repeatability_spec(name: str, texture_set: str, outputs: list[str] | None, work: Path) -> Any:
    manifest = envelope_manifest(name)
    if name.startswith("semantics-ui/group-passthrough"):
        from tests.evaluator.blend_fits import passthrough_spec

        return passthrough_spec(manifest, texture_set, work, sorted(channel_formats(manifest)))
    selected = outputs if outputs is not None else list(channel_formats(manifest))
    return aliased(spec_from_steps(manifest, texture_set, work, selected))


def rasters(result: dict[str, Any]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for channel, entry in sorted(result["channels"].items()):
        assert "error" not in entry, (channel, entry["error"])
        out[channel] = (Path(result["_dir"]) / entry["file"]).read_bytes()
    return out


def evaluate_twice(
    exe: Path, spec: Callable[[Path], dict[str, Any]], tmp_path: Path, backend: str
) -> None:
    """Builds the spec (with its resources) in two directories and evaluates each in its own
    process."""
    first = rasters(evaluate(exe, spec(tmp_path / "first"), tmp_path / "first", backend))
    second = rasters(evaluate(exe, spec(tmp_path / "second"), tmp_path / "second", backend))
    assert first.keys() == second.keys() and first
    differing = [channel for channel in first if first[channel] != second[channel]]
    assert not differing, f"rasters differ between the two processes: {differing}"


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize(
    ("name", "texture_set", "outputs"),
    REPEATABILITY,
    ids=[f"{n.split('/')[-1]}-{s}" for n, s, _ in REPEATABILITY],
)
def test_tier0_inputs_evaluate_to_identical_rasters_in_two_processes(
    evaluator_tests: Path,
    tmp_path: Path,
    name: str,
    texture_set: str,
    outputs: list[str] | None,
    backend: str,
) -> None:
    """3.2: the same Tier 0 inputs evaluated twice in separate processes give byte-identical
    channel rasters."""
    evaluate_twice(
        evaluator_tests,
        lambda work: repeatability_spec(name, texture_set, outputs, work),
        tmp_path,
        backend,
    )


@pytest.mark.parametrize("backend", backends())
@pytest.mark.parametrize(
    ("name", "texture_set"), VIRTUAL, ids=[f"{n.split('/')[-1]}-{s}" for n, s in VIRTUAL]
)
def test_virtual_normal_maps_are_identical_in_two_processes(
    evaluator_tests: Path, tmp_path: Path, name: str, texture_set: str, backend: str
) -> None:
    """3.2: the Height channel and both virtual normal maps of the height-to-normal goldens."""
    manifest = envelope_manifest(name)
    evaluate_twice(
        evaluator_tests,
        lambda work: virtual_spec(manifest, texture_set, work, ["Height"]),
        tmp_path,
        backend,
    )


def test_excluded_features_raise_not_yet_supported_before_any_mutation(
    evaluator_tests: Path,
) -> None:
    """3.3 (decision 082): every excluded feature of the Phase 1 subset, requested through a
    transaction, fails with NotYetSupported naming its owner task and leaves the document, its
    revision, records and save state unchanged; the features the evaluator refuses itself fail
    evaluation with a kind whose API class is NotYetSupported before any tile is allocated; a
    supported request commits; a project that already holds a gap stays editable elsewhere."""
    passed, _ = run_case(evaluator_tests, "not-yet-supported")
    assert any(p.startswith("every excluded feature (29:") for p in passed)
    assert any(p.startswith("the 23 features the evaluator refuses itself") for p in passed)
    assert {
        "unsupported_node, unsupported_blend_mode and unsupported_source are NotYetSupported; "
        "invalid_argument and not_found ValueError; missing_resource ResourceNotFoundError; "
        "internal RuntimeError",
        "a supported request (opacity, UV projection with Nearest, a content levels effect) "
        "commits and evaluates",
        "an edit of a supported node commits in a project that holds an instance layer; touching "
        "the instance fails with NotYetSupported",
    } <= passed

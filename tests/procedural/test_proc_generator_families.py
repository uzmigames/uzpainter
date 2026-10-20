"""Tests of phase3.2_proc-generator-families (`src/procedural/generators.h`, decision 329): the
mesh-map generators' certified editable domains, declared in the shipped asset library before any
calibration (item 2.7), the generators over mesh maps bound by usage (items 2.2-2.4), the loud
failure of a missing or invalid mesh map (test 3.2), DX12 repeatability (test 3.3) and the
refusals just outside the declared domains (test 3.4).

The native cases run `uzp-proc-generator-tests.exe` (`tests/procedural/generators_test.cpp`).
`signals`, `wear`, `masks`, `bind` and `domain` run on the CPU, `kernels` needs `dxcompiler.dll`
(installed beside the executable), and `gpu` needs a DX12 hardware adapter: it skips under
`UZP_NO_GPU=1` or when the executable reports none (exit code 77). Only one GPU run may be on the
machine at a time.

None of these assets is certified: each record's parity status is `unavailable`, no alias of the
library names it (decision 324), and no case here compares against a Painter output.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.parity.proc_cert.batch import Domain

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = REPO_ROOT / "assets/procedural"
# Each generator and the mesh maps it reads by usage (decision 329 §1).
GENERATORS = {
    "uzasset://generator/curvature@1": ("records/generator.curvature@1.json", {"Curvature"}),
    "uzasset://generator/position@1": ("records/generator.position@1.json", {"Position"}),
    "uzasset://generator/world-normal@1": (
        "records/generator.world-normal@1.json",
        {"WorldSpaceNormal"},
    ),
    "uzasset://generator/occlusion@1": ("records/generator.occlusion@1.json", {"AO"}),
    "uzasset://generator/dirt@1": (
        "records/generator.dirt@1.json",
        {"AO", "Curvature", "Position"},
    ),
    "uzasset://generator/edge-wear@1": (
        "records/generator.edge-wear@1.json",
        {"AO", "Curvature", "Position"},
    ),
    "uzasset://generator/mask-builder@1": (
        "records/generator.mask-builder@1.json",
        {"AO", "Curvature", "Position", "WorldSpaceNormal"},
    ),
    "uzasset://generator/mask-editor@1": (
        "records/generator.mask-editor@1.json",
        {"AO", "Curvature", "Position", "Thickness", "WorldSpaceNormal"},
    ),
}
EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
# The implemented families, their kernel passes at the defaults, and the GPU case's parameter sets.
FAMILIES = (
    "uzasset://generator/curvature@1",
    "uzasset://generator/position@1",
    "uzasset://generator/world-normal@1",
    "uzasset://generator/occlusion@1",
    "uzasset://generator/dirt@1",
    "uzasset://generator/edge-wear@1",
    "uzasset://generator/mask-builder@1",
    "uzasset://generator/mask-editor@1",
)
KERNEL_PASSES = 15
GPU_CASES = 16
# One channel for the scalar maps, three for the vector ones.
CHANNELS = {"AO": 1, "Curvature": 1, "Thickness": 1, "Position": 3, "WorldSpaceNormal": 3}


def record(path: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((SHIPPED / path).read_text(encoding="utf-8"))
    return document


@pytest.mark.parametrize("asset", sorted(GENERATORS))
def test_generator_domain_is_declared_before_calibration(asset: str) -> None:
    """2.7: the domain parses as the certification harness reads it; nothing is certified."""
    path, usages = GENERATORS[asset]
    document = record(path)
    assert document["asset"] == asset
    assert document["usage"] == "GENERATOR"
    assert document["license"] == "Apache-2.0"
    domain = Domain(document["domain"])
    assert domain.seed_policy == "any_u32"
    assert domain.mesh_classes == ["sphere", "bevelled-cube", "garment"]
    # The mesh maps it reads by usage, each at the output's resolutions (no resampling).
    assert set(domain.inputs) == usages
    for usage, rule in domain.inputs.items():
        assert rule["resolutions"] == domain.output["resolutions"] == [1024, 2048, 4096]
        assert rule["formats"] == ["u8", "u16"]
        assert rule["colour_spaces"] == ["Raw"]
        assert rule["channels"] == [CHANNELS[usage]]
    assert domain.output == {
        "resolutions": [1024, 2048, 4096],
        "formats": ["f32"],
        "colour_spaces": ["linear"],
        "channels": [1],
    }
    assert domain.ranges, "every family has a ranged parameter for the boundary sets"
    assert set(document["defaults"]) == set(domain.ranges) | set(domain.sets)
    assert domain.params_refusal(document["defaults"]) is None
    # Every low/high pair is ordered by at least 2^-8.
    for constraint in domain.constraints:
        assert constraint["max"] == -(2**-8)
        assert sorted(constraint["coefficients"].values()) == [-1, 1]
    assert document["parity"]["status"] == "unavailable"
    assert document["corpus"] == {}
    assert "report" not in document["parity"]


def test_no_alias_names_a_generator_family() -> None:
    """Decision 324: only an `exact` asset gets an alias; the generators are not certified."""
    library = json.loads((SHIPPED / "library.json").read_text(encoding="utf-8"))
    assert {path for path, _ in GENERATORS.values()} <= set(library["records"])
    aliases = json.loads((SHIPPED / library["aliases"]).read_text(encoding="utf-8"))
    generator_urls = set(GENERATORS)
    assert not [a for a in aliases["aliases"] if a.get("asset") in generator_urls]


@pytest.fixture(scope="session")
def generator_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-proc-generator-tests.exe` of a fresh `zig build proc-generator-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-proc-generator-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("proc-generator-tests")
    build = subprocess.run(
        [zig, "build", "proc-generator-tests", "-j2", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-proc-generator-tests.exe"


def run_case(exe: Path, case: str, work: Path) -> set[str]:
    """Run one case; return its passed checks. Fails on any failed check."""
    if case == "gpu" and NO_GPU:
        pytest.skip("UZP_NO_GPU=1: the `gpu` case needs a DX12 hardware adapter")
    proc = subprocess.run(
        [str(exe), case, str(work), str(SHIPPED)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no DX12 adapter for `{case}`: {output.strip()}")
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    return {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}


def test_mesh_map_generators_follow_their_formulas(generator_tests: Path, tmp_path: Path) -> None:
    """2.2 (CPU): Curvature, Position, World Space Normals and Ambient Occlusion over mesh maps
    bound by usage, against their published formulas; tiles, the joint rule (no resampling) and
    the seam's refusal of the uncertified families."""
    passed = run_case(generator_tests, "signals", tmp_path)
    assert len(passed) == 25, sorted(passed)
    for check in (
        "Curvature at its defaults is the convex part clamp(2c - 1)",
        "Curvature concave, boxstep [0.125, 0.625], smoothed and inverted",
        "Position gradient along axis 2 boxstepped [0.25, 0.75]",
        "World Space Normals along signed axis 5 boxstepped [-0.5, 0.75]",
        "Ambient Occlusion is the smoothed occlusion 1 - ao",
        "a mesh map at another resolution than the output is refused, not resampled",
        "the seam refuses the uncertified family inside its domain (family not certified)",
    ):
        assert check in passed


def test_dirt_and_edge_wear_follow_their_formulas(generator_tests: Path, tmp_path: Path) -> None:
    """2.3 (CPU): Dirt and Metal Edge Wear from curvature/AO cavity and edge detection, the disk
    dilation and the fBm noise breakup of the shared primitives, against their formulas."""
    passed = run_case(generator_tests, "wear", tmp_path)
    assert len(passed) == 13, sorted(passed)
    for check in (
        "uzasset://generator/dirt@1 at its defaults equals base, dilation, noise breakup and "
        "boxstep",
        "uzasset://generator/edge-wear@1 at an edited parameter set equals its formula",
        "Dirt's noise breakup changes with the seed",
        "Dirt without noise does not depend on the seed",
        "Dirt's spread grows the mask and never shrinks it",
        "Edge Wear reduced to its edge detection equals the Curvature generator's convex part",
    ):
        assert check in passed


def test_mask_builder_and_mask_editor_follow_their_formulas(
    generator_tests: Path, tmp_path: Path
) -> None:
    """2.4 (CPU): Mask Builder (Legacy) and Mask Editor over the mesh-map terms, the noise mask,
    disk growth and shrinking, against their formulas."""
    passed = run_case(generator_tests, "masks", tmp_path)
    assert len(passed) == 15, sorted(passed)
    for check in (
        "Mask Builder source 4 boxstepped [0.25, 0.875]",
        "Mask Builder with the noise mask and grow -3 equals its formula",
        "Mask Editor's weighted sum of the six terms, boxstepped [-0.5, 1.5] and inverted",
        "Mask Editor at its defaults (edges only) equals the Curvature generator at its defaults",
    ):
        assert check in passed


def test_missing_or_invalid_mesh_map_fails_loudly(generator_tests: Path, tmp_path: Path) -> None:
    """3.2: a generator with a missing or invalid mesh map fails evaluation, naming the map;
    nothing is substituted."""
    passed = run_case(generator_tests, "bind", tmp_path)
    assert len(passed) == 16, sorted(passed)
    for check in (
        "a texture set without a Curvature binding fails loudly, naming it",
        "a Curvature binding marked invalid fails loudly, naming it with its report",
        "a Curvature image the resources do not hold fails loudly",
        "a Curvature image at another size than the set fails loudly, not resampled",
        "evaluation without the Curvature raster fails (CPU lane)",
        "evaluation without the Curvature raster fails before any GPU work (candidate lane)",
        "a reference that binds a mesh map itself is refused: maps come from the texture set",
    ):
        assert check in passed


def test_requests_just_outside_the_domain_are_refused_before_mutation(
    generator_tests: Path, tmp_path: Path
) -> None:
    """3.4: a parameter, a seed, a mesh class, a mesh-map input and a resolution just outside the
    declared domain raise `UnsupportedProcedural{reason: "outside certified domain"}` before
    mutation, naming the field: nothing is clamped or substituted."""
    passed = run_case(generator_tests, "domain", tmp_path)
    outside = [c for c in passed if c.startswith("outside the domain, refused before mutation")]
    assert len(outside) == 12, sorted(passed)
    assert sum(c.startswith("the candidate lane evaluates nothing: ") for c in passed) == 12
    for check in (
        "outside the domain, refused before mutation with nothing clamped: a parameter one ulp "
        "above its range",
        "outside the domain, refused before mutation with nothing clamped: a seed outside 32 bits",
        "outside the domain, refused before mutation with nothing clamped: a mesh-map input in "
        "half floats",
        "outside the domain, refused before mutation with nothing clamped: a mesh-map input at "
        "another resolution than the output",
        "outside the domain, refused before mutation with nothing clamped: an output resolution "
        "of 8192",
        "inside the domain the uncertified Dirt is refused before mutation (family not certified)",
        "an admitted generator edit commits the reference as given, with no mesh map stored in it",
    ):
        assert check in passed


def test_generator_kernels_compile(generator_tests: Path, tmp_path: Path) -> None:
    """2.2-2.4: every family's kernel passes compile to DXIL and SPIR-V through the render core."""
    passed = run_case(generator_tests, "kernels", tmp_path)
    planned = [c for c in passed if c.startswith("kernel passes planned for ")]
    assert len(planned) == len(FAMILIES), sorted(passed)
    assert sum(c.startswith("compiles: ") for c in passed) == 2 * KERNEL_PASSES


def test_generators_on_dx12_equal_the_cpu_reference_and_repeat(
    generator_tests: Path, tmp_path: Path
) -> None:
    """2.2-2.4 and 3.3 (DX12): every generator equals its CPU reference bit for bit, whole and by
    tile, and two runs give identical bytes."""
    passed = run_case(generator_tests, "gpu", tmp_path)
    equal = [c for c in passed if c.startswith("DX12 equals the CPU reference bit for bit: ")]
    repeat = [c for c in passed if c.startswith("DX12 repeats: identical bytes across two runs: ")]
    assert len(equal) == len(repeat) == GPU_CASES, sorted(passed)
    for asset in FAMILIES:
        assert any(c.endswith(f"{asset} defaults") for c in repeat), asset

"""Tier 2b hit/coverage of the native baker's other usages against Painter's goldens.

`tools/bake/usage_tier2b.py` bakes each non-Normal `tier2b/bakes/*` golden's own instruction
sequence with the native driver's `bake-files` and compares Painter's nonzero texels with the
native hits and covered texels (phase3.2_baker-normal, decision 415). The argument tests run
everywhere; the comparisons need the private store and are skipped without it (decision 028). No
GPU and no Painter session are involved.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.bake import usage_tier2b as ut
from tools.parity.store.store import OracleStore, locate

REPO_ROOT = Path(__file__).resolve().parents[2]

# One golden per usage and scene: coverage depends on the scene and the common steps only.
HITS_EQUAL = (
    "ao-plane-no-ground-plane",
    "ao-sphere-no-ground-plane",
    "ao-bevelled-cube-no-ground-plane",
    "id-plane-mesh-id-random",
    "id-sphere-mesh-id-random",
    "id-bevelled-cube-mesh-id-random",
    "thickness-slab-none",
    "thickness-sphere-none",
    "thickness-bevelled-cube-none",
)
# Painter writes a value on every covered texel, misses included (the bevelled cube's 20832).
COVERED_EQUAL = (
    "world-space-normal-plane",
    "world-space-normal-sphere",
    "world-space-normal-bevelled-cube",
)
# A Position value can be zero, so only Painter's nonzero texels outside the covered set count.
WITHIN_COVERED = (
    "position-plane-all-axis-none-full-scene",
    "position-sphere-all-axis-none-full-scene",
    "position-bevelled-cube-all-axis-none-full-scene",
)


def test_every_golden_but_normal_is_compared() -> None:
    names = ut.goldens()
    assert len(names) == 60
    assert {ut.usage_of(ut.manifest(n)) for n in names} == {
        "AO",
        "Curvature",
        "ID",
        "Position",
        "Thickness",
        "WorldSpaceNormal",
    }


def test_bake_arguments_keep_the_usage_steps_apart() -> None:
    common, usage_sets = ut.bake_arguments(ut.manifest("position-sphere-one-axis-x"))
    assert usage_sets == ["Position:Mode=One axis", "Position:Axis=X"]
    assert "--high" not in common
    common, usage_sets = ut.bake_arguments(ut.manifest("ao-bevelled-cube-ground-plane"))
    assert usage_sets == ["AO:GroundPlane=true"]
    assert common[common.index("--high") + 1].endswith("bevelled-cube-high.obj")


def test_curvature_from_the_normal_map_is_curvature_s_golden() -> None:
    assert ut.usage_of(ut.manifest("curvature-plane-from-normal-map")) == "Curvature"


def test_parse_result_refuses_other_bytes() -> None:
    with pytest.raises(ut.ComparisonError):
        ut.parse_result(b"UZPBAKE9" + bytes(64))


@pytest.fixture(scope="session")
def bake_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-bake-feasibility-tests.exe` of a fresh `zig build bake-feasibility-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-bake-feasibility-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-bake-usage-tier2b")
    build = subprocess.run(
        [zig, "build", "bake-feasibility-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-bake-feasibility-tests.exe"


@pytest.fixture(scope="session")
def store() -> OracleStore:
    found = locate()
    if found is None:
        pytest.skip("oracle_unavailable: no private store on this machine (decision 028)")
    return found


@pytest.mark.parametrize("name", HITS_EQUAL + COVERED_EQUAL + WITHIN_COVERED)
def test_coverage_against_painter(
    bake_tests: Path, store: OracleStore, tmp_path: Path, name: str
) -> None:
    entry = ut.compare(store, bake_tests, name, tmp_path / f"{name}.bin")
    assert entry["oracle_stable"]
    for recording in ("r1", "r2"):
        c = entry[recording]["coverage"]
        assert c["painter_outside_covered"] == 0, c
        if name in HITS_EQUAL:
            assert c["painter_only"] == c["native_only"] == 0, c
        if name in COVERED_EQUAL:
            assert c["covered_without_painter"] == 0, c

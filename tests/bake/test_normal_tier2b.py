"""Tier 2b of the native Normal baker against Painter's goldens (phase3.2_baker-normal, 3.1-3.4).

`tools/bake/normal_tier2b.py` bakes each `tier2b/bakes/normal-*` golden's own instruction sequence
with the native driver's `bake-files` command and compares hit/coverage first, then the 16-bit map,
on every texel. The argument and parsing tests run everywhere; the comparisons need the private
store and are skipped without it (decision 028). No GPU and no Painter session are involved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.bake import normal_tier2b as nt
from tools.parity.store.store import OracleStore, locate

REPO_ROOT = Path(__file__).resolve().parents[2]

# Goldens the native baker equals on every texel, r1 and r2.
EXACT = ("normal-plane", "normal-bevelled-cube")
# Goldens whose coverage is equal and whose maps still differ (task notes, 2026-11-08, section 11):
# the separating recordings and the best candidates are recorded there; no difference is accepted.
NOT_EXACT = {
    "normal-sphere": "low as high: the sign of Painter's residue around zero is not fitted",
    "normal-sphere-absolute-0-01": "low as high: the sign of Painter's residue around zero",
    "normal-sphere-absolute-0-05": "low as high: the sign of Painter's residue around zero",
    "normal-hemisphere-per-vertex": "ties on the high facets' edges; one-code rounding residue",
    "normal-hemisphere-per-fragment": "ties on the high facets' edges; one-code rounding residue",
}
SPHERES = ("normal-sphere", "normal-sphere-absolute-0-01", "normal-sphere-absolute-0-05")


def manifest(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(nt.manifest_path(name).read_text(encoding="utf-8"))
    return data


def test_every_normal_golden_is_classified() -> None:
    assert set(nt.GOLDENS) == set(EXACT) | set(NOT_EXACT)


def test_bake_arguments_replay_each_golden_sequence() -> None:
    cube = nt.bake_arguments(manifest("normal-bevelled-cube"))
    low = REPO_ROOT / "parity/fixtures/tier2b-bakes/bevelled-cube-low.obj"
    assert cube[:2] == ["--low", str(low)]
    assert cube[2:6] == ["--format", "OpenGL", "--tangent-space", "PerVertex"]
    sets = [cube[i + 1] for i, a in enumerate(cube) if a == "--set"]
    assert sets == [
        "OutputSize=9,9",
        "DilationWidth=0",
        "FilterMethod=By mesh name",
        "RelativeScale=false",
        "MaxHeight=0.05",
        "MaxDepth=0.04",
    ]
    assert cube[cube.index("--high") + 1].endswith("bevelled-cube-high.obj")
    fragment = nt.bake_arguments(manifest("normal-hemisphere-per-fragment"))
    assert fragment[fragment.index("--tangent-space") + 1] == "PerFragment"
    sphere = manifest("normal-sphere")
    assert "--high" not in nt.bake_arguments(sphere)
    assert nt.relative_distances(sphere)
    assert not nt.relative_distances(manifest("normal-sphere-absolute-0-01"))
    assert not nt.relative_distances(manifest("normal-plane"))


def test_parse_result_refuses_a_result_without_normal() -> None:
    with pytest.raises(nt.ComparisonError):
        nt.parse_result(b"UZPBAKE3" + bytes(64))


@pytest.fixture(scope="session")
def bake_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-bake-feasibility-tests.exe` of a fresh `zig build bake-feasibility-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-bake-feasibility-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-bake-normal-tier2b")
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


def test_bake_files_replays_the_plane(bake_tests: Path, tmp_path: Path) -> None:
    """The plane golden's sequence baked natively: its covered quarter is the flat normal."""
    result = nt.bake(bake_tests, manifest("normal-plane"), tmp_path / "plane.bin")
    hit = np.isin(result.texel_class, nt.HIT_CLASSES)
    assert int(hit.sum()) == result.summary["texels"]["straight_hit"] == 256 * 256
    assert (result.normal[hit] == [32768, 32768, 65535]).all()
    assert (result.normal[~hit] == 0).all()


@pytest.mark.parametrize("name", EXACT)
def test_normal_equals_painter(
    bake_tests: Path, store: OracleStore, tmp_path: Path, name: str
) -> None:
    entry = nt.compare(store, bake_tests, name, tmp_path / f"{name}.bin")
    for recording in ("r1", "r2"):
        coverage = entry[recording]["coverage"]
        assert coverage["painter_only"] == coverage["native_only"] == 0, coverage
        assert entry[recording]["map"]["exact"], entry[recording]["map"]
    assert entry["exact"]


@pytest.mark.parametrize("name", sorted(NOT_EXACT))
def test_coverage_equals_painter(
    bake_tests: Path, store: OracleStore, tmp_path: Path, name: str
) -> None:
    """Hit/coverage first: equal on every texel where the map is not yet exact."""
    entry = nt.compare(store, bake_tests, name, tmp_path / f"{name}.bin")
    for recording in ("r1", "r2"):
        coverage = entry[recording]["coverage"]
        assert coverage["painter_only"] == coverage["native_only"] == 0, coverage
    assert not entry["exact"], f"{name} became exact: move it to EXACT ({NOT_EXACT[name]})"


def test_painter_sphere_is_independent_of_the_detail_distances(store: OracleStore) -> None:
    """The separating recording of the sphere (low as high): Painter's map is the same at the
    default relative distances and at absolute 0.01 and 0.05, so its residue does not come from
    the primary ray's hit."""
    maps = [nt.golden_maps(store, manifest(name))["r1"] for name in SPHERES]
    assert all(np.array_equal(maps[0], m) for m in maps[1:])


def test_bytes_equal_across_thread_counts(bake_tests: Path, tmp_path: Path) -> None:
    """Item 3.4 on this machine's qualified ISA: the bevelled cube's bytes at 1, 4 and every
    hardware thread are identical."""
    cube = manifest("normal-bevelled-cube")
    outputs = []
    for threads in (1, 4, 0):
        out = tmp_path / f"{threads}.bin"
        result = nt.bake(bake_tests, cube, out, threads)
        expected = min(threads or (os.cpu_count() or 1), 32 * 32)
        assert result.summary["threads_used"] == expected
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1] == outputs[2]

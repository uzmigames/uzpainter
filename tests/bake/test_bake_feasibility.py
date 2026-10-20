"""CPU baker (phase3.1_baker-request-model, permitted slices, not its acceptance; decisions 302,
306 and 311; `docs/architecture/06-baking.md` §1-§4 and §6).

`uzp-bake-feasibility-tests.exe` (`tests/bake/bake_feasibility_test.cpp`,
`zig build bake-feasibility-tests`) holds the native cases with their analytic class counts and
bakes the authored fixtures on request; these tests run each case, then bake the fixtures in
separate processes at 1, 4 and every hardware thread and compare the output bytes. Parity with
Painter's bakers is not claimed: the baker reports `pending-evidence`. No GPU is involved:
everything runs on the CPU lane.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "sampling",  # 2.3: Hammersley addressing by texel index and sample id
    "open_plane",  # 2.6: straight hits and uncovered texels, every ray escapes
    "box_inward",  # 2.6: every secondary ray hits a front face
    "box_outward",  # 2.6: every secondary ray hits a back face, counted per texel
    "centre_miss",  # 2.6: centre misses kept as a class, never filled
    "back_face_primary",  # 2.4, 2.6: back-face primary hits kept; IgnoreBackface passes them
    "self_hit",  # 2.6: self-intersections counted, removed by min_distance
    "capability_errors",  # 2.2, 3.5: unqualified ISA, usage, size, cage and diffusion refusals
    "build_threads_diagnostic",  # 2.2: only the serial BVH build is qualified (SUP-023)
    "threads_in_process",  # 3.3: identical bytes at 1, 4 and N threads in one process
    "job_async",  # 2.2: IBaker/JobHandle, progress, ids, published result
    "job_cancel",  # 2.2: cancellation publishes nothing; dropping a handle cancels
    "job_fail",  # 2.2: a casting failure ends in Fail with its error
    "worker_spawn_failure",  # SUP-023: a failed worker spawn joins the started ones
    "embree_acquisition_failure",  # SUP-023: Embree objects released at every failing step
    "tile_callback_throws",  # SUP-031: a throwing tile callback fails the job, never terminates
    "match_by_name",  # 2.4, 3.4: FilterMethod by name, _low/_high/_ignorebf suffixes
    "match_always",  # 2.4, 3.4: FilterMethod always; IgnoreBackface
    "low_as_high_matching",  # 2.4: LowAsHigh with name matching
    "custom_cage",  # 2.5, 2.6: in-memory custom cage, cage-hit class
    "hidden_mask",  # 2.6: hidden class from the request's mask
    "subsampling_bevel",  # 2.6, 3.4: SubSampling coverage and hit counts per texel
    "subsampling_coverage",  # 2.6, 3.4: coverage accumulation on a UV edge
    "dilation",  # 2.7, 3.4: DilationWidth outside the used surface, RAW kept
    "bevel_threads_in_process",  # 3.3: the bevelled cube with highs at 1, 4 and N threads
    "parameters",  # 2.8: the BakingParameters/Property model, one-transaction set()
    "units",  # 2.7: distances in centimetres over the mesh's scale_to_internal, recorded
    "relative_distances",  # 2.5: distances relative to the project mesh's bounding box
    "cage_file",  # 2.5, 3.4: low, high and cage read from mesh files, cage vertices by index
    "cage_file_threads_in_process",  # 3.3: the file-loaded cage scene at 1, 4 and N threads
    "linked_groups",  # 2.10, 3.5: link groups, one transaction across linked sets
    "bake_settings",  # 2.10: bake_settings {common, detail, per_baker} saved and loaded
    "parameters_to_request",  # 2.8: BakingParameters to a BakeRequest
    "normal_plane",
    "normal_curved_modes",
    "normal_mirrored",
    "normal_directx",
    "normal_negative_z",
    "normal_high_interpolation",
    "normal_hit_classes",
    "normal_singular_failure",
    "normal_usage_isolation",
    "normal_refusals",
    "normal_material_split",
    "normal_retained_corners",
    "world_normal_plane",  # WSN 2.1: the high normal at the hit, signed float32
    "world_normal_sphere",  # WSN 2.1: low as high, the low mesh's own normal
    "world_normal_bevel",  # WSN 2.1: faces, edge chamfers and corners of the bevelled cube
    "world_normal_threads_in_process",  # WSN 3.3 (one ISA): identical bytes at 1, 4 and N threads
    "world_normal_isolation",  # WSN: shares AO's primary hits without changing AO
    "world_normal_refusals",  # WSN: SubSampling and DilationWidth refused, owner named
    "position_plane",  # Position 2.1: each Mode and Axis, centimetres over scale_to_internal
    "position_sphere",  # Position 2.1: low as high, ground mapping and sphere radius
    "position_bevel",  # Position 2.1: the bevelled cube's analytic hit points
    "position_threads_in_process",  # Position (one ISA): identical bytes at 1, 4 and N threads
    "position_record",  # Position 2.2 (None only): the effective normalisation and its JSON
    "position_refusals",  # Position: BBox, BSphere, SubSampling, DilationWidth refused
    "position_parameters",  # Position: stored, saved, loaded and mapped through the model
    "id_plane",  # ID 2.1 (Mesh ID only): two high planes, one label each
    "id_sphere",  # ID 2.1: low as high, one label per part
    "id_bevel",  # ID 2.1: the bevelled cube's highs matched by name
    "id_threads_in_process",  # ID (one ISA): identical bytes at 1, 4 and N threads
    "id_isolation",  # ID: shares AO's primary hits without changing AO
    "id_refusals",  # ID: other sources, every generator, SubSampling, DilationWidth refused
    "id_parameters",  # ID: stored, saved, loaded and mapped through the model
)


@pytest.fixture(scope="session")
def bake_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-bake-feasibility-tests.exe` of a fresh `zig build bake-feasibility-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-bake-feasibility-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-bake-feasibility-tests")
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


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(exe), *args], capture_output=True, timeout=300, check=False)


def bake(
    exe: Path, fixture: str, threads: int, out: Path | None = None, *extra: str
) -> dict[str, Any]:
    args = ["bake", fixture, str(threads), *extra]
    if out is not None:
        args += ["--out", str(out)]
    proc = run(exe, *args)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(bake_tests: Path, case: str) -> None:
    proc = run(bake_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


@pytest.mark.parametrize(
    ("fixture", "tiles"),
    [
        ("scene", 256),
        ("bevel", 32),
        ("cage_file", 32),
        ("normal", 16),
        ("world_normal", 32),
        ("position", 32),
        ("id", 32),
    ],
)
def test_bytes_equal_across_thread_counts(
    bake_tests: Path, tmp_path: Path, fixture: str, tiles: int
) -> None:
    """A fixture baked in three processes at 1, 4 and N workers: identical bytes. `bevel` is the
    bevelled cube with highs and every path of decision 306 on; `cage_file` reads its meshes and
    cage from OBJ files with relative AO distances and a unit scale (decision 311)."""
    hardware = os.cpu_count() or 1
    outputs = {}
    for threads in (1, 4, hardware):
        out = tmp_path / f"{fixture}-{threads}.bin"
        result = bake(bake_tests, fixture, threads, out)
        assert result["threads_used"] == min(threads, tiles)
        assert result["parity_status"] == "pending-evidence"
        assert result["qualified"] is True and result["diagnostic"] is False
        outputs[threads] = (out.read_bytes(), result)
    reference_bytes, reference = outputs[1]
    for threads, (data, result) in outputs.items():
        assert data == reference_bytes, f"{threads} threads changed the output bytes"
        assert result["sha256"] == reference["sha256"]
        assert result["texels"] == reference["texels"] and result["rays"] == reference["rays"]


def test_parallel_bvh_build_is_diagnostic_only(bake_tests: Path) -> None:
    """A BVH build thread count other than 1 is unqualified (decision 306): refused before any
    work, and baked only on the explicit diagnostic path, marked as such."""
    refused = run(bake_tests, "bake", "scene", "4", "--embree-build-threads", "8")
    assert refused.returncode == 3
    assert b"CapabilityError" in refused.stderr and b"serial BVH build" in refused.stderr
    result = bake(bake_tests, "scene", 4, None, "--embree-build-threads", "8", "--diagnostic")
    assert result["qualified"] is False and result["diagnostic"] is True


@pytest.mark.parametrize("fixture", ["scene", "scene_self"])
def test_miss_classes_are_reported(bake_tests: Path, fixture: str) -> None:
    """Every texel and every secondary ray is in exactly one class, and the classes the scene
    produces (back-face primary hits at the sphere's contact with the ground, back-face and self
    secondary hits) are reported, not folded into the map."""
    result = bake(bake_tests, fixture, 4)
    texels, rays = result["texels"], result["rays"]
    assert sum(texels.values()) == result["width"] * result["height"]
    assert sum(rays.values()) == result["subsamples"]["hit"] * result["rays_per_texel"]
    assert texels["back_face_hit"] > 0
    assert rays["back_face_hit"] > 0
    assert rays["self_hit"] > 0
    if fixture == "scene_self":
        # Without min_distance most rays meet their own triangle at t = 0: counted as self hits.
        assert rays["self_hit"] > rays["escaped"]

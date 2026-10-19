"""CPU baker feasibility (a slice of phase3.1_baker-request-model, items 2.2, 2.3, 2.6 and 3.3 in
part; decision 302; `docs/architecture/06-baking.md` §1-§4).

`uzp-bake-feasibility-tests.exe` (`tests/bake/bake_feasibility_test.cpp`,
`zig build bake-feasibility-tests`) holds the native cases with their analytic class counts and
bakes the authored determinism scene on request; these tests run each case, then bake the scene
in separate processes at 1, 4 and every hardware thread and compare the output bytes. Parity
with Painter's bakers is not claimed: the baker reports `pending-evidence`. No GPU is involved:
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
    "back_face_primary",  # 2.6: back-face primary hits kept as a class
    "self_hit",  # 2.6: self-intersections counted, removed by min_distance
    "capability_errors",  # 2.2, 3.5: unqualified ISA, usage, size, Automatic cage
    "threads_in_process",  # 3.3: identical bytes at 1, 4 and N threads in one process
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


def bake(exe: Path, fixture: str, threads: int, out: Path | None = None) -> dict[str, Any]:
    args = ["bake", fixture, str(threads)]
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


def test_bytes_equal_across_thread_counts(bake_tests: Path, tmp_path: Path) -> None:
    """The scene baked in three processes at 1, 4 and N workers: identical bytes."""
    hardware = os.cpu_count() or 1
    outputs = {}
    for threads in (1, 4, hardware):
        out = tmp_path / f"scene-{threads}.bin"
        result = bake(bake_tests, "scene", threads, out)
        assert result["threads_used"] == min(threads, 256)  # 256 tiles at 256² and 16² tiles
        assert result["parity_status"] == "pending-evidence"
        outputs[threads] = (out.read_bytes(), result)
    reference_bytes, reference = outputs[1]
    for threads, (data, result) in outputs.items():
        assert data == reference_bytes, f"{threads} threads changed the output bytes"
        assert result["sha256"] == reference["sha256"]
        assert result["texels"] == reference["texels"] and result["rays"] == reference["rays"]


@pytest.mark.parametrize("fixture", ["scene", "scene_self"])
def test_miss_classes_are_reported(bake_tests: Path, fixture: str) -> None:
    """Every texel and every secondary ray is in exactly one class, and the classes the scene
    produces (back-face primary hits at the sphere's contact with the ground, back-face and self
    secondary hits) are reported, not folded into the map."""
    result = bake(bake_tests, fixture, 4)
    texels, rays = result["texels"], result["rays"]
    assert sum(texels.values()) == result["width"] * result["height"]
    assert sum(rays.values()) == texels["straight_hit"] * result["rays_per_texel"]
    assert texels["back_face_hit"] > 0
    assert rays["back_face_hit"] > 0
    assert rays["self_hit"] > 0
    if fixture == "scene_self":
        # Without min_distance most rays meet their own triangle at t = 0: counted as self hits.
        assert rays["self_hit"] > rays["escaped"]

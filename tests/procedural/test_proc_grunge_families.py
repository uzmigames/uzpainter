"""Tests of phase3.2_proc-grunge-families (`src/procedural/grunges.h`, decision 331): the grunge
assets' certified editable domains, declared in the shipped asset library before any calibration
(item 2.6), their evaluation with seed and parameters (item 2.3), seamless tiling (test 3.2),
seed behaviour (test 3.3, the half that needs no Painter golden) and the domain refusals before
mutation (test 3.4).

The native cases run `uzp-proc-grunge-tests.exe` (`tests/procedural/grunges_test.cpp`).
`families`, `tiling`, `seeds` and `domain` run on the CPU, `kernels` needs `dxcompiler.dll`
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
INVENTORY = REPO_ROOT / "docs/analysis/proc-grunge-families/01-asset-inventory.md"
COMMON = {"balance", "contrast", "invert", "tiling"}
GRUNGES = {
    "rock": set(),
    "stone-details": set(),
    "dirt-large": set(),
    "dirt-spots-small": {"disorder"},
    "spots-bw-a": {"disorder"},
    "spots-bw-b": {"disorder"},
    "dirt-a": {"disorder"},
    "scratches-fine": {"rotation_variation"},
    "scratches": {"rotation_variation"},
    "scratches-dirty": {"rotation_variation"},
    "rust-fine": set(),
    "humidity": {"flip_horizontal", "flip_vertical"},
    "map-a": set(),
    "map-b": set(),
    "spots-soft": {"disorder"},
    "cracks-leather": {"hardness", "shape"},
    "linen": {"tension_variation"},
}


def record(asset_id: str) -> dict[str, Any]:
    path = SHIPPED / f"records/grunge.{asset_id}@1.json"
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


@pytest.mark.parametrize("asset_id", sorted(GRUNGES))
def test_grunge_domain_is_declared_before_calibration(asset_id: str) -> None:
    """2.6: every inventoried asset declares its domain in its record, uncertified."""
    document = record(asset_id)
    assert document["asset"] == f"uzasset://grunge/{asset_id}@1"
    assert document["usage"] == "PROCEDURAL"
    assert document["name"].startswith("UzPainter ")
    domain = Domain(document["domain"])
    # Grunges are seeded: any 32-bit seed, and no image input.
    assert domain.seed_policy == "any_u32"
    assert domain.inputs == {}
    assert domain.mesh_classes == ["sphere", "bevelled-cube", "garment"]
    assert domain.output == {
        "resolutions": [1024, 2048, 4096],
        "formats": ["f32"],
        "colour_spaces": ["linear"],
        "channels": [1],
    }
    assert set(domain.ranges) | set(domain.sets) == COMMON | GRUNGES[asset_id]
    # Tiling is a whole number of repeats across the texture, so the texture still wraps.
    assert domain.sets["tiling"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert domain.ranges, "every asset has a ranged parameter for the boundary sets"
    assert set(document["defaults"]) == set(domain.ranges) | set(domain.sets)
    assert domain.params_refusal(document["defaults"]) is None
    assert document["parity"]["status"] == "unavailable"
    assert document["corpus"] == {}


def test_every_inventoried_asset_has_a_record_and_no_alias() -> None:
    """2.1, 2.6: the inventory's assets are the shipped grunge records; decision 324 admits no
    alias to an asset that is not `exact`."""
    library = json.loads((SHIPPED / "library.json").read_text(encoding="utf-8"))
    grunges = {p for p in library["records"] if p.startswith("records/grunge.")}
    assert grunges == {f"records/grunge.{a}@1.json" for a in GRUNGES}
    aliases = json.loads((SHIPPED / library["aliases"]).read_text(encoding="utf-8"))
    assert all(not a["asset"].startswith("uzasset://grunge/") for a in aliases["aliases"])
    inventory = INVENTORY.read_text(encoding="utf-8")
    for asset_id in GRUNGES:
        assert f"`grunge/{asset_id}`" in inventory, asset_id


EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"


@pytest.fixture(scope="session")
def grunge_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-proc-grunge-tests.exe` of a fresh `zig build proc-grunge-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-proc-grunge-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("proc-grunge-tests")
    build = subprocess.run(
        [zig, "build", "proc-grunge-tests", "-j2", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-proc-grunge-tests.exe"


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


def test_grunge_assets_evaluate_with_seed_and_parameters(
    grunge_tests: Path, tmp_path: Path
) -> None:
    """2.3 (CPU): every asset registers from its record, evaluates inside [0, 1] with its seed and
    parameters, answers a tile with the texture's texels, and is refused by the seam."""
    passed = run_case(grunge_tests, "families", tmp_path)
    for check in (
        "every inventoried grunge asset registers from its library record",
        "every grunge asset evaluates its defaults on the CPU lane, inside [0, 1]",
        "no grunge asset is constant at its defaults",
        "invert gives 1 - value bit for bit for every grunge asset",
        "a tile of every grunge asset equals the same texels of the whole texture",
        "every declared parameter of every grunge asset changes its texture",
        "the seam refuses every uncertified grunge asset inside its domain (family not certified)",
        "GrungeWords refuses an asset outside the family",
        "GrungeWords refuses a request without a declared parameter",
        "the CPU lane refuses a request outside the domain before evaluating it",
    ):
        assert check in passed, check


def test_grunge_assets_tile_seamlessly(grunge_tests: Path, tmp_path: Path) -> None:
    """3.2: the texture continued past each border is the texture itself, bit for bit."""
    passed = run_case(grunge_tests, "tiling", tmp_path)
    assert (
        "every grunge asset wraps seamlessly: the texture continued one tile past each border is "
        "the texture itself, bit for bit" in passed
    )
    assert (
        "every texel coordinate (x + 1/2) P / R of every grunge asset is exact in float32 over "
        "three tiles" in passed
    )
    assert (
        "the CPU lane's first column is the continuation of its last, for one asset of each "
        "pattern kind" in passed
    )


def test_two_seeds_differ_on_the_cpu_lane(grunge_tests: Path, tmp_path: Path) -> None:
    """3.3 (our half, CPU): two seeds differ; the same seed repeats."""
    passed = run_case(grunge_tests, "seeds", tmp_path)
    assert "two seeds give two different textures for every grunge asset (CPU lane)" in passed
    assert "the same seed repeats bit for bit on the CPU lane for every grunge asset" in passed


COMMON_REFUSALS = (
    "a parameter one ulp above its range",
    "a parameter one ulp below its range",
    "a tiling of 9 repeats",
    "a fractional tiling",
    "a recorded parameter with no counterpart",
    "a seed outside 32 bits",
    "a mesh-map input, which no grunge reads",
    "an output resolution of 512",
    "an output resolution of 8192",
    "an output in half floats",
)


def test_domain_refusals_come_before_mutation(grunge_tests: Path, tmp_path: Path) -> None:
    """3.4: a parameter, a seed, a mesh-map input, a resolution and an output format just outside
    each asset's domain raise `UnsupportedProcedural{reason: "outside certified domain"}` before
    mutation, naming the field, with nothing clamped or substituted."""
    passed = run_case(grunge_tests, "domain", tmp_path)
    prefix = "outside the domain, refused before mutation with nothing clamped"
    refused = [c for c in passed if c.startswith(prefix)]
    assert len(refused) == sum(16 + len(own) for own in GRUNGES.values()), refused
    for asset_id, own in GRUNGES.items():
        name = f"uzasset://grunge/{asset_id}@1"
        for what in (
            *COMMON_REFUSALS,
            *(f"its own parameter {p} " for p in own),
        ):
            assert any(c.startswith(f"{prefix}: {name}, {what}") for c in refused), (name, what)
            lane = f"the candidate lane evaluates nothing: {name}, {what}"
            assert any(c.startswith(lane) for c in passed), (name, what)
        assert (
            "inside the domain the uncertified grunge is refused before mutation (family not "
            f"certified): {name}" in passed
        )
    assert (
        "an admitted grunge source commits the reference as given, as a mask fill's source and a "
        "channel's" in passed
    )


def test_grunge_kernels_compile(grunge_tests: Path, tmp_path: Path) -> None:
    """Every asset's kernel compiles to DXIL and SPIR-V."""
    passed = run_case(grunge_tests, "kernels", tmp_path)
    assert "one kernel pass planned for every grunge asset" in passed
    assert "every grunge kernel compiles to DXIL and SPIR-V" in passed


def test_grunge_assets_on_dx12(grunge_tests: Path, tmp_path: Path) -> None:
    """2.3, 3.3 (GPU): DX12 equals the CPU reference bit for bit; the same seed repeats
    byte-identically; two seeds differ."""
    passed = run_case(grunge_tests, "gpu", tmp_path)
    for asset_id in GRUNGES:
        name = f"uzasset://grunge/{asset_id}@1"
        for check in (
            "DX12 equals the CPU reference bit for bit over the whole 1024 texture: ",
            "the same seed repeats byte-identically on DX12: ",
            "two seeds give two different textures on DX12: ",
            "a DX12 tile at the border equals the CPU tile: ",
        ):
            assert check + name in passed, check + name

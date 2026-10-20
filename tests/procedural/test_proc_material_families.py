"""Tests of phase3.2_proc-material-families (`src/procedural/materials.h`, decision 334): the
material assets' certified editable domains, outputs and physical sizes, declared in the shipped
asset library before any calibration (item 2.6, the domain half), and their evaluation with
every output reachable through `output_mapping` (items 2.2 and 2.3), and the physical-size scale
modes under the project unit rule (item 2.4; test 3.2, the half that needs no Painter golden).

The native cases run `uzp-proc-material-tests.exe` (`tests/procedural/materials_test.cpp`).
`library`, `families`, `tiling`, `physical` and `domain` run on the CPU; `kernels` needs
`dxcompiler.dll` (installed beside the executable), and `gpu` needs a DX12 hardware adapter: it
skips under `UZP_NO_GPU=1` or when the executable reports none (exit code 77). Only one GPU run
may be on the machine at a time.

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
COMMON = {
    "tiling",
    "color_r",
    "color_g",
    "color_b",
    "color_variation",
    "roughness",
    "roughness_variation",
    "normal_intensity",
    "ao_intensity",
}
MATERIALS = {
    "felt": {"fibre_density", "fibre_alignment"},
    "burlap": {"gap", "irregularity", "fuzz"},
    "leather-grain": {"irregularity", "groove_width", "pore_amount"},
    "leather-pattern": {"crease_depth", "wrinkles", "grain_amount"},
}
OUTPUTS = [
    ("basecolor", "BaseColor", 3, "srgb"),
    ("normal", "Normal", 3, "linear"),
    ("roughness", "Roughness", 1, "linear"),
    ("metallic", "Metallic", 1, "linear"),
    ("height", "Height", 1, "linear"),
    ("ambient_occlusion", "AO", 1, "linear"),
]


def record(asset_id: str) -> dict[str, Any]:
    path = SHIPPED / f"records/material.{asset_id}@1.json"
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


@pytest.mark.parametrize("asset_id", sorted(MATERIALS))
def test_material_domain_is_declared_before_calibration(asset_id: str) -> None:
    """2.6 (domain half): every material declares its domain, outputs and physical size in its
    record, uncertified."""
    document = record(asset_id)
    assert document["asset"] == f"uzasset://material/{asset_id}@1"
    assert document["usage"] == "BASE_MATERIAL"
    assert document["name"].startswith("UzPainter ")
    domain = Domain(document["domain"])
    # Materials are seeded and read no image input.
    assert domain.seed_policy == "any_u32"
    assert domain.inputs == {}
    assert domain.mesh_classes == ["sphere", "bevelled-cube", "garment"]
    assert domain.output == {
        "resolutions": [1024, 2048, 4096],
        "formats": ["f32"],
        "colour_spaces": ["linear", "srgb"],
        "channels": [1, 3],
    }
    assert set(domain.ranges) | set(domain.sets) == COMMON | MATERIALS[asset_id]
    # Tiling is a whole number of repeats across the texture, so the texture still wraps.
    assert domain.sets == {"tiling": list(range(1, 33))}
    assert set(document["defaults"]) == COMMON | MATERIALS[asset_id]
    assert domain.params_refusal(document["defaults"]) is None
    # One output per channel, each inside the domain's output rule.
    outputs = [
        (o["id"], o["channel"], o["channels"], o["colour_space"]) for o in document["outputs"]
    ]
    assert outputs == OUTPUTS
    for _, _, channels, space in outputs:
        assert channels in domain.output["channels"]
        assert space in domain.output["colour_spaces"]
    width, height = document["physical_size_cm"]
    assert width > 0 and height > 0
    assert document["parity"]["status"] == "unavailable"
    assert document["corpus"] == {}


def test_every_material_has_a_record_and_no_alias() -> None:
    """2.6: the four materials are the shipped material records; decision 324 admits no alias to
    an asset that is not `exact`."""
    library = json.loads((SHIPPED / "library.json").read_text(encoding="utf-8"))
    materials = {p for p in library["records"] if p.startswith("records/material.")}
    assert materials == {f"records/material.{a}@1.json" for a in MATERIALS}
    aliases = json.loads((SHIPPED / library["aliases"]).read_text(encoding="utf-8"))
    assert all(not a["asset"].startswith("uzasset://material/") for a in aliases["aliases"])


EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"


@pytest.fixture(scope="session")
def material_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-proc-material-tests.exe` of a fresh `zig build proc-material-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-proc-material-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("proc-material-tests")
    build = subprocess.run(
        [zig, "build", "proc-material-tests", "-j2", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-proc-material-tests.exe"


def run_case(exe: Path, case: str, work: Path) -> tuple[set[str], str]:
    """Run one case; return its passed checks and its output. Fails on any failed check."""
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
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    return passed, proc.stdout


def test_shipped_library_declares_material_outputs_natively(
    material_tests: Path, tmp_path: Path
) -> None:
    """2.6: the native loader admits every shipped record with each material's outputs and
    physical size, refuses malformed ones, and `assets list --parity` prints them."""
    passed, stdout = run_case(material_tests, "library", tmp_path)
    library = json.loads((SHIPPED / "library.json").read_text(encoding="utf-8"))
    assert f"LOADED {len(library['records'])}" in stdout.splitlines()
    assert (
        "every material loads natively with its six outputs, its physical size and an "
        "unavailable status" in passed
    )
    assert "assets list --parity prints every material's outputs and physical size" in passed
    refusals = [c for c in passed if c.startswith("the loader refuses ")]
    assert len(refusals) == 9, refusals


def test_materials_evaluate_every_output(material_tests: Path, tmp_path: Path) -> None:
    """2.2, 2.3 (CPU): every material registers from its record; every output evaluates inside
    [0, 1], is reachable through `output_mapping`, and is refused by the seam."""
    passed, _ = run_case(material_tests, "families", tmp_path)
    for check in (
        "every material registers from its library record",
        "every output of every material evaluates on the CPU lane inside [0, 1] with its channels",
        "no output but metallic is constant at the defaults",
        "the metallic output of every material is 0",
        "every normal output is a unit vector facing out, and (0, 0, 1) without relief",
        "every occlusion output lies in [1 - ao_intensity, 1] and is 1 on open surfaces",
        "a tile of every output equals the same texels of the whole texture",
        "every declared parameter of every material changes an output",
        "every output of every material is reachable through output_mapping, and an unknown "
        "output, an empty mapping or a key that is not a channel is refused",
        "the seam refuses every uncertified material output inside its domain (family not "
        "certified)",
        "MaterialWords refuses an asset outside the family",
        "MaterialWords refuses a request without a declared parameter",
        "the CPU lane refuses a request outside the domain before evaluating it",
        "a material request that names no output is refused (output.id)",
        "a basecolor request with one channel is refused (output.channels)",
        "an sRGB height request is refused (output.colour_space)",
    ):
        assert check in passed, check


def test_materials_tile_seamlessly(material_tests: Path, tmp_path: Path) -> None:
    """The fields continued past each border are the texture itself, bit for bit."""
    passed, _ = run_case(material_tests, "tiling", tmp_path)
    assert (
        "every material wraps seamlessly: its fields continued one tile past each border are "
        "the texture itself, bit for bit" in passed
    )


def test_physical_size_follows_the_project_unit_rule(material_tests: Path, tmp_path: Path) -> None:
    """2.4, 3.2 (our half): the same material on one mesh imported in two unit scales repeats by
    its physical size, and every receipt records the effective units. The oracle half of 3.2
    (equal to Painter's outputs) waits on goldens."""
    passed, stdout = run_case(material_tests, "physical", tmp_path)
    for check in (
        "the same material on one mesh in two unit scales repeats by (centimetres per UV or file "
        "unit) / its physical size, MaterialPhysicalSize and CustomPhysicalSize alike",
        "every physical-size receipt records the effective units (source, from, requested scale, "
        "centimetres per file unit) and the size it used, and the two unit scales record "
        "different units",
        "the Factors scale mode is refused as not a physical size",
        "MaterialPhysicalSize is refused for an asset without a physical size",
        "a texture set the mesh certificate does not know is refused",
        "a mesh without an import report is refused",
    ):
        assert check in passed, check
    receipts = [
        json.loads(line.split(": ", 1)[1])
        for line in stdout.splitlines()
        if line.startswith("INFO ") and "PhysicalSize: {" in line
    ]
    assert [r["units"]["scale_to_internal"] for r in receipts] == [1.0, 1.0, 100.0, 100.0]
    assert [r["units"]["from"] for r in receipts] == ["file", "file"] + ["mesh_unit_scale"] * 2


def test_domain_refusals_come_before_mutation(material_tests: Path, tmp_path: Path) -> None:
    """3.4: a parameter, a seed, a mesh-map input, a resolution and a format just outside each
    material's domain raise `UnsupportedProcedural{reason: "outside certified domain"}` before
    mutation, naming the field, with nothing clamped or substituted."""
    passed, _ = run_case(material_tests, "domain", tmp_path)
    refused = [c for c in passed if c.startswith("outside the domain, refused before mutation")]
    assert len(refused) == 15 * len(MATERIALS), refused
    prefix = "outside the domain, refused before mutation with nothing clamped"
    for asset_id in MATERIALS:
        name = f"uzasset://material/{asset_id}@1"
        for what in (
            "a parameter one ulp above its range",
            "a seed outside 32 bits",
            "a mesh-map input, which no material reads",
            "an output resolution of 512",
            "an output resolution of 8192",
        ):
            check = f"{prefix}: {name}, {what}"
            assert check in passed, check
        assert (
            "inside the domain the uncertified material is refused before mutation (family not "
            f"certified): {name}" in passed
        )
        assert f"an output the material does not have is refused before mutation: {name}" in passed
    assert (
        "an admitted material source commits the reference as given, every channel mapped" in passed
    )


def test_material_kernels_compile(material_tests: Path, tmp_path: Path) -> None:
    """Every output's kernel passes compile to DXIL and SPIR-V."""
    passed, _ = run_case(material_tests, "kernels", tmp_path)
    assert (
        "one pass planned for every single-pass output and two for the normal and the "
        "occlusion" in passed
    )
    assert "every material kernel compiles to DXIL and SPIR-V" in passed


def test_materials_on_dx12(material_tests: Path, tmp_path: Path) -> None:
    """3.3 (GPU): every output of every material on DX12 equals its CPU reference bit for bit,
    whole and by a border tile; two runs give identical bytes; two seeds differ."""
    passed, _ = run_case(material_tests, "gpu", tmp_path)
    for asset_id in MATERIALS:
        for output, _, _, _ in OUTPUTS:
            name = f"uzasset://material/{asset_id}@1 {output}"
            checks = [
                "DX12 equals the CPU reference bit for bit over the whole 1024 texture: ",
                "two DX12 runs give identical bytes: ",
                "a DX12 tile at the border equals the CPU tile: ",
            ]
            if output != "metallic":
                checks.append("two seeds give two different textures on DX12: ")
            for check in checks:
                assert check + name in passed, check + name

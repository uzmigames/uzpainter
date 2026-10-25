"""Tests of phase3.1_proc-backend-seam items 2.1-2.3 (`src/procedural/`): the seam, the
certified-domain check, the HlslBackend host and the primitive library.

Every case runs `uzp-procedural-tests.exe` (`tests/procedural/procedural_test.cpp`). `seam`,
`domain`, `primitives` and `kernels` run on the CPU (`kernels` needs `dxcompiler.dll`, installed
beside the executable); `gpu` needs a DX12 hardware adapter and skips under `UZP_NO_GPU=1` or
when the executable reports none (exit code 77). Only one GPU run may be on the machine at a
time. The families in these cases are authored test probes, not Painter assets.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
PRIMITIVES = Path(__file__).resolve().parents[2] / "src/procedural/primitives.provenance.json"


def run_case(exe: Path, case: str, work: Path) -> set[str]:
    """Run one case; return its passed checks. Fails on any failed check."""
    if case == "gpu" and NO_GPU:
        pytest.skip("UZP_NO_GPU=1: the `gpu` case needs a DX12 hardware adapter")
    proc = subprocess.run(
        [str(exe), case, str(work)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no DX12 adapter for `{case}`: {output.strip()}")
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    return {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}


def test_seam_order_refusal_and_no_substitution(procedural_tests: Path, tmp_path: Path) -> None:
    """2.1: Snapshot then Hlsl; no backend -> UnsupportedProcedural before evaluation."""
    passed = run_case(procedural_tests, "seam", tmp_path)
    assert "the refusal evaluates nothing and substitutes no other asset" in passed
    assert "a snapshot with the exact signature is tried first" in passed
    assert "a missing mesh map fails the evaluation loudly" in passed


def test_reserved_observation_family_is_refused_everywhere(
    procedural_tests: Path, tmp_path: Path
) -> None:
    """Decision 362 (phase3.1 item 2.6g): the observation family is refused by the HLSL backend
    (registration, refusal, kernels, reference and candidate lanes), the snapshot backend, the
    seam, the asset library and admission, whatever its id and version."""
    passed = run_case(procedural_tests, "observations", tmp_path)
    assert "the seam selects no backend" in passed
    assert "the reference and candidate lanes evaluate nothing for the family" in passed
    assert "admission refuses a malformed member of the family before parsing it" in passed


def test_domain_refusals_name_field_value_and_range(procedural_tests: Path, tmp_path: Path) -> None:
    """2.1 / decision 222: refusal outside the certified domain, nothing clamped."""
    passed = run_case(procedural_tests, "domain", tmp_path)
    assert sum(check.startswith("outside the domain: ") for check in passed) == 20
    assert any(check.startswith("no refused request is planned or evaluated") for check in passed)
    assert any(
        check.startswith("an out-of-domain request whose exact signature") for check in passed
    )


def test_typed_parameter_signatures_and_domain_refusals(
    procedural_tests: Path, tmp_path: Path
) -> None:
    passed = run_case(procedural_tests, "typed-params", tmp_path)
    assert "color alpha presence and working space each alter the signature" in passed
    assert "structured values cannot enter a scalar certified range" in passed
    assert "malformed project parameter refuses at admission" in passed


def test_primitives_meet_public_expectations(procedural_tests: Path, tmp_path: Path) -> None:
    """2.3 / 3.3 (CPU lane): properties stated by the papers and IEEE 754."""
    passed = run_case(procedural_tests, "primitives", tmp_path)
    assert any(check.startswith("SqrtRn equals the correctly rounded") for check in passed)
    assert "Perlin 1985 and 2002 noise are 0 at every lattice point" in passed


def test_kernels_compile_through_the_render_core(procedural_tests: Path, tmp_path: Path) -> None:
    """2.2: generated HLSL to DXIL and SPIR-V, `precise`, cached by content hash."""
    passed = run_case(procedural_tests, "kernels", tmp_path)
    assert any(check.startswith("precise arithmetic reaches SPIR-V") for check in passed)
    assert "parameter and seed edits reuse the kernel; another family's body does not" in passed


def test_gpu_equals_cpu_and_repeats(procedural_tests: Path, tmp_path: Path) -> None:
    """2.2 / 3.3 (DX12): every probe equals its CPU reference bit for bit and repeats."""
    passed = run_case(procedural_tests, "gpu", tmp_path)
    assert sum(check.startswith("GPU equals CPU bit for bit: ") for check in passed) == 29
    assert sum(check.startswith("DX12 repeats byte for byte: ") for check in passed) == 29
    assert any(check.startswith("the seam serves a certified family on DX12") for check in passed)


def test_every_primitive_has_a_public_provenance_note() -> None:
    """2.3: one provenance note per primitive, citing public sources only."""
    record = json.loads(PRIMITIVES.read_text(encoding="utf-8"))
    names = [entry["primitive"] for entry in record["primitives"]]
    source = (PRIMITIVES.parent / "primitives.cpp").read_text(encoding="utf-8")
    listed = source[source.index("kNames[] = {") :].split("};", 1)[0]
    assert sorted(names) == sorted(part.strip() for part in listed.split('"')[1::2])
    for entry in record["primitives"]:
        assert entry["sources"], entry["primitive"]
        assert all(s["kind"] in {"paper", "standard", "book"} for s in entry["sources"])


def test_edits_refuse_before_mutation_and_reopen_identically(
    procedural_tests: Path, tmp_path: Path
) -> None:
    """3.1, 3.6 and 3.4 through a document edit (`src/procedural/admission.h`, decision 324
    §10): every refusal leaves the stored project's revision where it was and evaluates
    nothing; a snapshot with the exact signature still serves an out-of-domain request; the
    pinned reference evaluates identically after save and reopen. CPU only."""
    fixture = Path(__file__).resolve().parent / "fixtures/library"
    proc = subprocess.run(
        [str(procedural_tests), "admission", str(tmp_path), str(fixture)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, proc.stdout + proc.stderr
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    assert len(passed) == 24, sorted(passed)
    refused = [check for check in passed if check.startswith("refused before mutation, ")]
    assert len(refused) == 10
    assert any(check.endswith("a vector outside a scalar certified domain") for check in refused)
    assert sum("(3.6)" in check for check in refused) == 4
    for check in (
        "no refused edit evaluates, plans or stores any asset in its place (no substitution, "
        "no clamping)",
        "an out-of-domain request whose exact signature a snapshot holds is served and committed "
        "unclamped",
        "evaluation after save and reopen is identical, bit for bit (RES-04)",
        "a library without that version refuses the pin on reopen; no other version is used",
    ):
        assert check in passed

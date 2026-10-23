"""Native qualification only; product Vulkan activation and settling remain separate gates."""

from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from tests.preview.conftest import GOLDENS, run_case


def test_viewport_fixed_slot_shaders_without_gpu(preview_tests: Path, tmp_path: Path) -> None:
    passed, _ = run_case(preview_tests, "viewport-spirv", str(tmp_path))
    for entry in ("main", "display", "probe"):
        assert f"Vulkan viewport {entry} compiles to SPIR-V" in passed
        assert f"Vulkan viewport {entry} uses fixed slots and push constants" in passed
        assert f"Vulkan viewport {entry} writes one storage image" in passed


@pytest.mark.skipif(os.environ.get("UZP_NO_GPU") == "1", reason="GPU qualification disabled")
def test_viewport_backends_preserve_regressions_and_repeat(
    preview_tests: Path, tmp_path: Path
) -> None:
    """Four authored fixtures, both captured planes, two processes and resident reuse per run."""
    captures: dict[str, dict[str, bytes]] = {}
    for backend in ("dx12", "vulkan"):
        baseline: dict[str, bytes] | None = None
        for repeat in range(2):
            directory = tmp_path / f"{backend}-{repeat}"
            process = subprocess.run(
                [str(preview_tests), "viewport-backend", str(directory), backend],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1200,
                check=False,
            )
            output = process.stdout + process.stderr
            if process.returncode == 77:
                pytest.skip(output)
            assert process.returncode == 0, output
            report = json.loads((directory / "backend-report.json").read_text())
            assert report["backend"] == backend
            assert report["adapter"] and report["driver"]
            assert report["acceptance"] is False
            assert report["probe_rays"] == 4096 and report["probe_matches_cpu"] is True
            assert set(report["fixtures"]) == {"sphere", "plane", "bevelled-cube", "cube-on-plane"}
            golden_path = (
                GOLDENS if backend == "dx12" else GOLDENS.with_name("viewport-vulkan-goldens.json")
            )
            entries = json.loads(golden_path.read_text())["entries"]
            matching = [
                entry
                for entry in entries
                if entry["adapter"] == report["adapter"] and entry["driver"] == report["driver"]
            ]
            assert matching, f"No recorded {backend} baseline for this adapter and driver"
            assert report["fixtures"] == matching[-1]["fixtures"], f"{backend} output regressed"
            captured = {path.name: path.read_bytes() for path in directory.glob("*.rgba16")}
            assert len(captured) == 8
            assert all(len(data) == 256 * 256 * 4 * 2 for data in captured.values())
            if baseline is None:
                baseline = captured
                captures[backend] = captured
            else:
                for name, expected in baseline.items():
                    actual = captured[name]
                    mismatches = sum(a != b for a, b in zip(actual, expected, strict=True))
                    assert mismatches == 0, (
                        f"{backend} run {repeat}, {name}: {mismatches} bytes differ"
                    )
    # The realtime viewport is a per-backend regression check, not a parity tier.
    diagnostics = {}
    for name, expected in captures["dx12"].items():
        actual = captures["vulkan"][name]
        words = len(expected) // 2
        a = struct.unpack(f"<{words}H", expected)
        b = struct.unpack(f"<{words}H", actual)
        values_a = struct.unpack(f"<{words}e", expected) if ".linear." in name else a
        values_b = struct.unpack(f"<{words}e", actual) if ".linear." in name else b
        diagnostics[name] = {
            "differing_samples": sum(x != y for x, y in zip(a, b, strict=True)),
            "max_absolute_difference": max(
                abs(x - y) for x, y in zip(values_a, values_b, strict=True)
            ),
        }
    (tmp_path / "cross-backend-diagnostic.json").write_text(
        json.dumps({"acceptance": False, "fixtures": diagnostics}, indent=2) + "\n"
    )

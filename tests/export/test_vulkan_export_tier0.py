"""Real GPU export against the current private Tier 0 subset; no product activation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.export.encoders_tier0 import export_goldens


@pytest.mark.skipif(os.environ.get("UZP_NO_GPU") == "1", reason="GPU lane, decision 028")
@pytest.mark.parametrize("backend", ["dx12", "vulkan"])
def test_gpu_written_goldens_equal_painter_and_repeat(
    export_tests: Path, tmp_path: Path, backend: str
) -> None:
    """Sharp/Sobel normals and Height, every recorded strength, map and export step.

    Both backends must equal the same golden bytes, including PNG/EXR headers, and
    repeat in separate processes. An unavailable requested backend fails this lane.
    """
    report = export_goldens(export_tests, tmp_path, runs=2, backend=backend)
    assert report["steps"] > 0 and report["files"] > 0
    assert report["problems"] == [], report["problems"][:10]
    assert report["identical_to_painter"] == report["comparisons"]
    print(
        f"PASS {backend}: {report['files']} files, "
        f"{report['comparisons']} exact Painter comparisons, two runs"
    )

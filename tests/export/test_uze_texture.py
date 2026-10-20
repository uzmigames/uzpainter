"""UzEngine textures: BC encoder adapter, mip chains, `.uztexture` writer.

Task `phase3.1_uze-uztexture-writer` (decision 315). `uzp-texture-tests.exe`
(`tests/export/texture_test.cpp`, `zig build uzp-texture-tests`) holds the native cases over
`uzp_texture.lib`: etcpak BC encoding at 1, 4 and the maximum worker count (3.1), the sRGB-aware
colour mips against an independent reference (3.2), unit-length normal mips (3.3), alpha-coverage
preservation (3.4), the negative-Z guard (3.5), the `.uztexture` layout read back through the
test-only reader (3.6) and the lossy-derivative report (3.7). No GPU is involved: everything runs
on the CPU lane.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "encoder_determinism",  # 3.1
    "encoder_channels",  # 2.2
    "bc_decoder",  # 2.8: own decoder, every BC7 mode, independent oracle.
    "colour_mips",  # 3.2
    "normal_mips",  # 3.3
    "alpha_coverage",  # 3.4
    "negative_z",  # 3.5 (library guard)
    "uztexture_layout",  # 3.6
    "normal_colour_space",  # Normal maps must not be sampled as sRGB.
    "lossy_derivative",  # 3.7
)

LOSSY_LINE = re.compile(
    r"LOSSY-DERIVATIVE map=(\w+) format=(\w+) mip=(\d+) channel=([RGBA]) "
    r"max=([0-9.]+) mean=([0-9.]+) p99=([0-9.]+)"
)


@pytest.fixture(scope="session")
def texture_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-texture-tests.exe` of a fresh `zig build uzp-texture-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; `zig build uzp-texture-tests` cannot run")
    prefix = tmp_path_factory.mktemp("uzp-texture-tests")
    build = subprocess.run(
        [zig, "build", "uzp-texture-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-texture-tests.exe"


def run_case(exe: Path, case: str) -> str:
    proc = subprocess.run(
        [str(exe), "run", case], capture_output=True, text=True, timeout=600, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"PASS {case}" in proc.stdout
    return proc.stdout


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(texture_tests: Path, case: str) -> None:
    run_case(texture_tests, case)


def test_lossy_derivative_report_is_separate(texture_tests: Path) -> None:
    """3.7: every BC derivative reports max, mean and p99 per channel and mip under the
    lossy-derivative heading only, with max >= p99 and max >= mean."""
    out = run_case(texture_tests, "lossy_derivative")
    assert "lossy-derivative contract" in out
    rows = [m.groups() for m in LOSSY_LINE.finditer(out)]
    maps = {(r[0], r[1]) for r in rows}
    assert maps == {("orm", "BC7"), ("height", "BC4")}
    assert {r[3] for r in rows if r[0] == "orm"} == {"R", "G", "B", "A"}
    assert {r[3] for r in rows if r[0] == "height"} == {"R"}
    assert {int(r[2]) for r in rows} == set(range(9))
    for row in rows:
        high, mean, p99 = (float(v) for v in row[4:])
        assert mean <= high and p99 <= high

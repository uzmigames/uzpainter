"""Strict native signature and lossless recording decoder boundary (synthetic CPU evidence)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_snapshot_recording_boundary(procedural_tests: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [str(procedural_tests), "snapshot-recording", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL " not in result.stdout
    assert "recording signature roundtrip preserves every field" in result.stdout
    assert "recording EXR refuses implicit precision conversion f16" in result.stdout

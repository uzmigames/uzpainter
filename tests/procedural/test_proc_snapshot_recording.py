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


def test_snapshot_source_metadata(procedural_tests: Path, tmp_path: Path) -> None:
    """Optional recorded image outputs beside the signature: legacy bytes and keys, validation
    before mutation, idempotency, reopen and bundle, exact-signature lookup and receipt parsing."""
    result = subprocess.run(
        [str(procedural_tests), "snapshot-metadata", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL " not in result.stdout
    for name in (
        "metadata: without metadata the operation key and arguments are unchanged",
        "metadata: an entry recorded without metadata has exactly the pre-metadata canonical bytes",
        "metadata: other metadata neither replays the recording nor changes the immutable snapshot",
        "metadata: recorded image outputs survive bundle import",
        "metadata: a receipt without readback refuses",
        "metadata: a receipt with an extra output refuses (no capture domain widening)",
        "metadata: a receipt whose active output differs from the signature refuses",
        "metadata: the order of the outputs changes the canonical metadata and its hash",
    ):
        assert "PASS " + name in result.stdout, name

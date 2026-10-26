"""Decision 363: the frozen-host native proof on authored bit patterns (real provider, DAG and
CPU store; no Painter, no captured data)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from tests.export.conftest import export_tests as export_tests

PREFIX = "FROZEN_HOST_PROOF: "
SOURCE = Path(__file__).resolve().parents[2] / "src" / "procedural"


def test_frozen_host_proof_on_authored_patterns(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    proc = subprocess.run(
        [str(export_tests), "frozen-host-proof", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.startswith(PREFIX)]
    assert len(lines) == 1, proc.stdout
    summary = json.loads(lines[0][len(PREFIX) :])
    # The record names the executable that computed it (its own file), never a caller's claim, and
    # the SHA-256 of the validator source embedded in it, which must be the current source bytes
    # (header then implementation): a stale embedded source fails here.
    binary = hashlib.sha256(export_tests.read_bytes()).hexdigest()
    source = SOURCE / "frozen_host_proof.h", SOURCE / "frozen_host_proof.cpp"
    code = hashlib.sha256(b"".join(path.read_bytes() for path in source)).hexdigest()
    # The mixed plane repeats six patterns; -0 and 2^-26 (positions 1 and 2) are not fixed points.
    nonfixed = sum(1 for i in range(128 * 128) if i % 6 in (1, 2))
    assert summary == {
        "binary_sha256": binary,
        "validator_code_sha256": code,
        "fixed_counts_zero": True,
        "mixed_nonfixed": nonfixed,
        "samples": 128 * 128,
    }

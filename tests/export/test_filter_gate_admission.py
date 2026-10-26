"""Native admission and envelope checks on authored oracle-store artifacts only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_filter_gate_admission_on_authored_evidence(
    export_tests: Path,
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [str(export_tests), "filter-gate-admission", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = "FILTER_GATE_ADMISSION: "
    summaries = [
        line[len(prefix) :] for line in result.stdout.splitlines() if line.startswith(prefix)
    ]
    assert len(summaries) == 1, result.stdout
    summary = json.loads(summaries[0])
    assert summary == {"checks": 88}

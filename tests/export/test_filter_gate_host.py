"""Native H admission from authored snapshots and pinned public policy only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_filter_gate_host_on_authored_evidence(export_tests: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [str(export_tests), "filter-gate-host", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = "FILTER_GATE_HOST: "
    summaries = [
        line[len(prefix) :] for line in result.stdout.splitlines() if line.startswith(prefix)
    ]
    assert len(summaries) == 1, result.stdout
    assert json.loads(summaries[0]) == {"checks": 25}

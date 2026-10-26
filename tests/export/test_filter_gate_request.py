"""Native command payload and replay identity on authored inputs only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_filter_gate_request_on_authored_inputs(export_tests: Path) -> None:
    result = subprocess.run(
        [str(export_tests), "filter-gate-request"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = "FILTER_GATE_REQUEST: "
    summaries = [
        line[len(prefix) :] for line in result.stdout.splitlines() if line.startswith(prefix)
    ]
    assert len(summaries) == 1, result.stdout
    assert json.loads(summaries[0]) == {"checks": 46}

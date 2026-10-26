"""Native destination mapping from authored F evidence; no Painter or private reads."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tests.parity.test_filter_context_settings_validation import authored as authored
from tests.parity.test_filter_context_settings_validation import png_bytes


def test_filter_gate_destination_on_authored_evidence(
    export_tests: Path,
    tmp_path: Path,
    authored: tuple[dict[str, Any], dict[str, Any]],  # noqa: F811
) -> None:
    _, record = authored
    (tmp_path / "destination-record.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "destination-panel.png").write_bytes(png_bytes())
    result = subprocess.run(
        [str(export_tests), "filter-gate-destination", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = "FILTER_GATE_DESTINATION: "
    summaries = [
        line[len(prefix) :] for line in result.stdout.splitlines() if line.startswith(prefix)
    ]
    assert len(summaries) == 1, result.stdout
    assert json.loads(summaries[0]) == {"checks": 61}

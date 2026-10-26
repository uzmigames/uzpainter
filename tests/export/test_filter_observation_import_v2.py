"""Decision 363: the internal V2 verified-context transaction component on authored evidence
(authored H artifacts and F context; no Painter, no captured data, no runtime entry point)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.export.conftest import export_tests as export_tests

REPO = Path(__file__).resolve().parents[2]
PREFIX = "FILTER_IMPORT_V2: "


def test_filter_import_v2_transaction_on_authored_evidence(
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    proc = subprocess.run(
        [str(export_tests), "filter-import-v2", str(tmp_path)],
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
    assert summary == {"checks": 81}


def test_no_production_route_reaches_the_verified_filter_context() -> None:
    """The F gate does not exist: no production source defines the test-only access, and only the
    test binary compiles the transaction component."""
    definition = re.compile(r"struct\s+FilterImportTestAccess\s*\{")
    defined = [
        path.relative_to(REPO).as_posix()
        for path in (REPO / "src").rglob("*")
        if path.suffix in {".h", ".cpp"} and definition.search(path.read_text(encoding="utf-8"))
    ]
    assert defined == []
    build = (REPO / "build.zig").read_text(encoding="utf-8")
    assert build.count("procedural/filter_observation_import_v2.cpp") == 1

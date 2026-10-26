"""Public production Filter import command: usage and refusal before external inputs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.python.test_assets3d_production_guard import painter as painter


def test_filter_import_usage(painter: Path) -> None:  # noqa: F811
    result = subprocess.run(
        [str(painter), "assets", "import-filter-observation"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stdout == ""
    assert "assets import-filter-observation <h-store.uzp>" in result.stderr
    for flag in ("--oracle-store", "--manifest", "--request"):
        assert flag in result.stderr


def test_filter_import_invalid_payload_precedes_external_inputs(
    painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    request = tmp_path / "import.json"
    request.write_text("{}", encoding="utf-8")
    project = tmp_path / "missing-project.uzp"
    oracle = tmp_path / "missing-oracle"
    manifest = tmp_path / "missing-manifest.json"
    result = subprocess.run(
        [
            str(painter),
            "assets",
            "import-filter-observation",
            str(project),
            "--oracle-store",
            str(oracle),
            "--manifest",
            str(manifest),
            "--request",
            str(request),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 3, result.stdout + result.stderr
    prefix = "UZP_JSON:"
    reports = [
        json.loads(line[len(prefix) :])
        for line in result.stdout.splitlines()
        if line.startswith(prefix)
    ]
    assert reports == [
        {
            "status": "refused",
            "reason": "FILTER_IMPORT_REQUEST_INVALID",
            "detail": "FILTER_IMPORT_REQUEST_SCHEMA",
        }
    ], result.stdout + result.stderr
    assert not project.exists() and not oracle.exists() and not manifest.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["import.json"]
    assert request.read_text(encoding="utf-8") == "{}"

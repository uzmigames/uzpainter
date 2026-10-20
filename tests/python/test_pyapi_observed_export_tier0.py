"""Observed engine/export and overwrite-save replays, phase1.24 item 4.1."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import Run
from tests.python.observed_replay import (
    check_observed_trace,
    compare_observed,
    observed_symbols,
    replay_observed,
    save_trace,
)

EXCLUDED: dict[str, dict[str, str]] = {
    "p22b-export-error-status": {},
    "phase1-engine-computations": {},
    "phase1-save-as-existing": {},
}


def comparable_files(
    probe: str, replayed: dict[str, Any], golden: dict[str, Any]
) -> dict[str, Any]:
    """Project only declared storage artifacts; retain every delivered name and byte hash."""
    compared = copy.deepcopy(replayed)
    for recording in golden["recordings"]:
        condition = recording["condition"]
        outputs = compared[condition]["outputs"]
        if probe == "phase1-save-as-existing":
            # Store owns the lock format; phase1.24 compares its presence on the open file.
            files = outputs["s11/files"]["value"]
            assert files.count("existing.spp") == 1
            assert files.count("existing.spp.lock") == 1
            assert outputs["s11/save_as"] == {"value": None}
            path = outputs["s12/file_path"]["value"]
            assert path == {"file_name": "existing.spp"}
            outputs["s11/files"]["value"] = [
                "existing.spp.painter_lock" if name == "existing.spp.lock" else name
                for name in files
            ]
        elif probe == "phase1-engine-computations":
            # Decisions 097/105: phase1.18 owns publication metadata and fixed-name copies.
            # This one export starts in an empty directory, so only generation 000001 exists.
            expected = next(
                o["value"] for o in recording["outputs"] if o["output_id"] == "s13/files"
            )
            files = outputs["s13/files"]["value"]
            by_name = {entry["file_name"]: entry for entry in files}
            assert len(by_name) == len(files), "duplicate export files"
            metadata = {
                "current.json",
                "fixed-names.journal.json",
                "publication.lock",
                "generations/000001/plan.json",
                "generations/000001/receipt.json",
            }
            for name in metadata:
                assert re.fullmatch(r"[0-9a-f]{64}", by_name[name]["sha256"])
            copies = set()
            for entry in expected:
                name = "generations/000001/files/" + entry["file_name"]
                assert by_name[name] == {**entry, "file_name": name}
                copies.add(name)
            outputs["s13/files"]["value"] = [
                entry for entry in files if entry["file_name"] not in metadata | copies
            ]
    return compared


@pytest.mark.parametrize("probe", sorted(EXCLUDED))
def test_observed_export_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    compared = comparable_files(probe, replayed, golden)
    differences = compare_observed(compared, golden, job, tmp_path, EXCLUDED[probe])
    save_trace(f"facade-observed/{probe}", golden, replayed, EXCLUDED[probe], differences)
    assert replayed["cleanup_failures"] == [], replayed["cleanup_failures"]
    assert not differences, "\n".join(differences)
    check_observed_trace(
        f"facade-observed/{probe}",
        golden["golden_id"],
        observed_symbols(replayed, golden, EXCLUDED[probe]),
    )

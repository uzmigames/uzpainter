"""Native procedural resolution; no SourceSubstance facade/parity claim."""

from pathlib import Path

from tests.procedural.test_proc_backend_seam import run_case


def test_native_resolution_modes(procedural_tests: Path, tmp_path: Path) -> None:
    passed = run_case(procedural_tests, "resolution", tmp_path)
    assert "Auto resize changes effective output and snapshot signature" in passed
    assert "known filter context refuses resolution override" in passed

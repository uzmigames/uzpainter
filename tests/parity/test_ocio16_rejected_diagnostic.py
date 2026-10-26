"""Authored arrays exercise diagnostic measurements without an oracle or native process."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity import ocio16_rejected_diagnostic as diagnostic
from tools.parity.fit.decode import Array
from tools.parity.tier0_semantics import ocio16_bitmap_control as control


def test_text_index_normalizes_native_paths_and_refuses_duplicate_identity() -> None:
    original = Path("public") / "run-13" / "config.json"
    entry: dict[str, Any] = {
        "origin": original.as_posix(),
        "text": "{}",
        "sha256": diagnostic.sha(b"{}"),
        "size": 2,
    }
    assert diagnostic.indexed_texts([entry])[original] == "{}"
    with pytest.raises(ValueError, match="duplicate text identity"):
        diagnostic.indexed_texts([entry, {**entry, "origin": str(original)}])


def test_cli_failure_is_private_staged_and_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"{}")
    output = tmp_path / "diagnostic.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "diagnostic",
            "--evidence",
            str(evidence),
            "--evidence-sha256",
            diagnostic.sha(b"{}"),
            "--output",
            str(output),
        ],
    )

    def refused(evidence: dict[str, Any], root: Path, progress: dict[str, str]) -> dict[str, Any]:
        progress["stage"] = "preserved"
        raise ValueError("PRIVATE_SYNTHETIC_SENTINEL")

    monkeypatch.setattr(diagnostic, "analyze", refused)
    assert diagnostic.main() == 2
    assert capsys.readouterr().out == '{"status":"refused"}\n'
    failure = tmp_path / "diagnostic-failure.json"
    initial = failure.read_bytes()
    record = json.loads(initial)
    assert record["stage"] == "preserved"
    assert "PRIVATE_SYNTHETIC_SENTINEL" in record["traceback"]
    assert not output.exists()
    assert diagnostic.main() == 2
    assert capsys.readouterr().out == '{"status":"refused"}\n'
    assert failure.read_bytes() == initial


def blank() -> Array:
    return np.zeros((256, 256, 3), dtype=np.float64)


def test_equal_images_count_pixels_without_errors() -> None:
    result = diagnostic.measurements(blank(), blank())
    assert result["pixels"] == 65536
    assert result["pixels_mismatched"] == 0
    assert result["candidate_nonfinite"] == result["reference_nonfinite"] == 0
    for channel in result["channels"]:
        assert channel["samples"] == 65536
        assert channel["mismatches"] == 0
        assert channel["signed_min"] == channel["signed_max"] == 0.0
        assert channel["abs_quantiles_all"] == [0.0] * 5
        assert channel["abs_quantiles_mismatches"] is None


def test_one_changed_channel_counts_one_pixel_and_keeps_error_direction() -> None:
    candidate, reference = blank(), blank()
    reference[17, 29, 1] = 3.0
    result = diagnostic.measurements(candidate, reference)
    assert result["pixels_mismatched"] == 1
    assert [c["mismatches"] for c in result["channels"]] == [0, 1, 0]
    green = result["channels"][1]
    assert green["signed_min"] == -3.0 and green["signed_max"] == 0.0
    assert green["abs_quantiles_all"] == [0.0, 0.0, 0.0, 0.0, 3.0]
    assert green["abs_quantiles_mismatches"] == [3.0] * 5


def test_matching_nan_and_signed_zero_follow_existing_numeric_comparator() -> None:
    candidate, reference = blank(), blank()
    candidate[0, 0, 0] = reference[0, 0, 0] = np.nan
    candidate[0, 1, 0] = -0.0
    result = diagnostic.measurements(candidate, reference)
    assert result["pixels_mismatched"] == 0
    assert result["candidate_nonfinite"] == result["reference_nonfinite"] == 1
    candidate[0, 2, 2] = np.nan
    result = diagnostic.measurements(candidate, reference)
    assert result["pixels_mismatched"] == 1
    assert result["channels"][2]["mismatches"] == 1
    assert result["channels"][2]["abs_quantiles_mismatches"] is None


def test_authored_channel_permutations_are_undone_without_search() -> None:
    triples = {"field-a": [2, 7, 11], "field-a-brg": [11, 2, 7], "field-a-gbr": [7, 11, 2]}
    images = {
        (source, format_, condition): np.broadcast_to(np.array(triple), (256, 256, 3)).copy()
        for source, triple in triples.items()
        for format_ in ("png8", "png16", "exr32")
        for condition in ("candidate", "same_session", "after_save_reopen")
    }
    assert all(row["samples_mismatched"] == 0 for row in diagnostic.permutation_checks(images))
    images["field-a-brg", "png8", "candidate"][3, 5, 0] = 12
    failures = [row for row in diagnostic.permutation_checks(images) if row["samples_mismatched"]]
    assert failures == [
        {
            "source": "field-a-brg",
            "format": "png8",
            "condition": "candidate",
            "samples_mismatched": 1,
            "pixels_mismatched": 1,
        }
    ]


def test_cross_format_separates_unknown_operands_from_known_code_errors() -> None:
    operands, png16, _ = diagnostic.existing_tables()
    codes = np.broadcast_to(np.arange(256)[None, :, None], (256, 256, 3))
    images = {
        (source, format_, condition): values.copy()
        for source in control.RGB16_CANDIDATES
        for condition in ("candidate", "same_session", "after_save_reopen")
        for format_, values in (
            ("png8", codes),
            ("png16", png16[codes]),
            ("exr32", operands[codes]),
        )
    }
    assert all(
        row["outside_srgb8_operands"]
        == row["png8_known_samples_mismatched"]
        == row["png16_known_samples_mismatched"]
        == 0
        for row in diagnostic.cross_format(images)
    )
    key = "field-a", "exr32", "same_session"
    images[key][0, 0, 0] = -1.0  # outside the existing table; no nearest-code substitution
    images["field-a", "png8", "same_session"][1, 0, 0] = 1
    images["field-a", "png16", "same_session"][2, 0, 0] = 1
    row = next(
        row
        for row in diagnostic.cross_format(images)
        if row["source"] == "field-a" and row["condition"] == "same_session"
    )
    assert row["outside_srgb8_operands"] == 1
    assert row["png8_known_samples_mismatched"] == row["png16_known_samples_mismatched"] == 1

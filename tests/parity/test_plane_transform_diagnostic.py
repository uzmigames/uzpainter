"""Authored metadata/topology only; no oracle access or production admission."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from tools.parity.fit import plane_transform_diagnostic as diagnostic
from tools.parity.fit.padding_plane_control import checked_bytes
from tools.parity.schemas import REPO_ROOT


def test_standalone_module_loading_does_not_need_pytest_import_path() -> None:
    validator = diagnostic.load_module(
        REPO_ROOT / "tests/export/padding_probe_diagnostic.py", "test_plane_diagnostic_exports"
    )
    assert callable(validator.validate_exports)


def test_pinned_public_manifests() -> None:
    for dataset, digest in diagnostic.MANIFESTS.items():
        path = diagnostic.MANIFEST_ROOT / f"export-padding-{dataset}.json"
        manifest = json.loads(checked_bytes(path, digest))
        assert manifest["golden_id"] == f"tier0/semantics/export-padding-{dataset}"
        assert len(manifest["inputs"]) == len({row["input_id"] for row in manifest["inputs"]})
        assert (
            len([r for r in manifest["private_records"] if r["record_id"] == "golden-record"]) == 1
        )


@pytest.mark.parametrize("fault", ["recording", "output", "condition"])
def test_raw_record_rejects_collapsing_or_mislabeled_identities(fault: str) -> None:
    value: dict[str, Any] = {
        "recordings": [
            {"recording_id": "r1", "condition": "same_session", "outputs": [{"output_id": "a"}]},
            {
                "recording_id": "r2",
                "condition": "after_save_reopen",
                "outputs": [{"output_id": "a"}],
            },
        ]
    }
    if fault == "recording":
        value["recordings"][1]["recording_id"] = "r1"
    elif fault == "output":
        value["recordings"][0]["outputs"].append({"output_id": "a"})
    else:
        value["recordings"][1]["condition"] = "same_session"
    with pytest.raises(ValueError):
        diagnostic.validate_record(value, {})


def ring() -> Any:
    return SimpleNamespace(
        tris=[
            SimpleNamespace(chart=0, face=0),
            SimpleNamespace(chart=0, face=1),
            SimpleNamespace(chart=1, face=2),
            SimpleNamespace(chart=1, face=3),
        ],
        _paths=lambda _a, _b: [[0, 1, 2, 3]],
        links={1: {0: (1, 0, 0, 1)}, 2: {1: (2, 1, 0, 1)}, 3: {2: (3, 2, 0, 1)}},
    )


def test_source_plane_selects_unique_source_side_seam_triangle() -> None:
    assert diagnostic.source_plane(ring(), 0, 3) == 1


@pytest.mark.parametrize(
    "fault", ["same_chart", "many_paths", "many_seams", "target_at_seam", "reversed_seam"]
)
def test_source_plane_preserves_historical_exclusions(fault: str) -> None:
    value = ring()
    if fault == "same_chart":
        value.tris[0].chart = 1
    elif fault == "many_paths":
        value._paths = lambda _a, _b: [[0, 1, 2, 3], [0, 3]]
    elif fault == "many_seams":
        value.tris[1].chart = 1
        value.tris[2].chart = 0
    elif fault == "target_at_seam":
        value.tris[2].face = 3
    else:
        value.links[2][1] = (1, 2, 0, 1)
    assert diagnostic.source_plane(value, 0, 3) is None


def test_deadline_rejects_expired_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "monotonic", lambda: 10.0)
    diagnostic.check_deadline(10.1)
    with pytest.raises(TimeoutError):
        diagnostic.check_deadline(10.0)


@pytest.mark.parametrize(
    "fault", ["none", "lost_regression", "baseline_count", "intersection_count"]
)
def test_historical_hinge_baseline_required_before_candidate(fault: str) -> None:
    baseline = {(i, 0) for i in range(395)}
    intersection = {(i, 0) for i in range(6)} | {(500, 0)}
    if fault == "lost_regression":
        intersection = {(i, 0) for i in range(7)}
    elif fault == "baseline_count":
        baseline.remove((394, 0))
    elif fault == "intersection_count":
        intersection.add((501, 0))
    values = {"baseline": {"r1": baseline}, "intersection": {"r1": intersection}}
    if fault == "none":
        diagnostic.validate_baseline("hinge-far", values)
    else:
        with pytest.raises(diagnostic.DiagnosticFailure, match="historical_baseline_drift"):
            diagnostic.validate_baseline("hinge-far", values)


@pytest.mark.parametrize("first_pass", [False, True])
def test_main_stops_failed_candidate_before_second_dataset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    first_pass: bool,
) -> None:
    visited: list[str] = []
    monkeypatch.setattr(diagnostic, "locate", object)
    monkeypatch.setattr(diagnostic, "reference", object)

    def run(dataset: str, _store: Any, _ref: Any, _deadline: float) -> dict[str, Any]:
        visited.append(dataset)
        return {"continue": first_pass}

    monkeypatch.setattr(diagnostic, "run_dataset", run)
    assert diagnostic.main() == (0 if first_pass else 1)
    assert visited == (list(diagnostic.MANIFESTS) if first_pass else ["hinge-far"])
    assert set(json.loads(capsys.readouterr().out)) == {"datasets", "reference_sha256"}


def exports() -> dict[str, Any]:
    channels = {
        f"User{i}": {"format": "RGB32F", "bit_depth": 32, "is_floating": True} for i in range(8)
    }
    template = {
        "kind": "template_capture",
        "values": {
            "texture_sets": {"authored": {"resolution": [512, 512], "stacks": {"": channels}}}
        },
    }
    outputs = [template]
    for step in range(45, 49):
        for channel in range(8):
            outputs.append(
                {
                    "kind": "exported_map",
                    "texture_set": "authored",
                    "map": f"user{channel}",
                    "export_settings": {
                        "paddingAlgorithm": "infinite" if step < 47 else "passthrough",
                        "step": step,
                        "map_type": "documentMap",
                        "map_channels": "RGB",
                        "encoding_basis": "file",
                        "fileFormat": "exr",
                        "bitDepth": "32f",
                        "dithering": False,
                    },
                    "storage_format": {
                        "container": "exr",
                        "sample_type": "float",
                        "bits_per_channel": 32,
                        "channels": 3,
                        "encoding": "linear",
                    },
                    "blob": {"sha256": str(channel), "size_bytes": 1},
                }
            )
    return {"recordings": [{"recording_id": "r1", "outputs": outputs}]}


@pytest.mark.parametrize("fault", ["none", "duplicate", "missing", "precision", "encoding", "step"])
def test_sample_assembly_and_domain_guards(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    record = exports()
    outputs = record["recordings"][0]["outputs"]
    if fault == "duplicate":
        outputs.append(outputs[-1])
    elif fault == "missing":
        outputs.pop()
    elif fault == "precision":
        outputs[0]["values"]["texture_sets"]["authored"]["stacks"][""]["User0"]["bit_depth"] = 16
    elif fault == "encoding":
        outputs[1]["storage_format"]["encoding"] = "sRGB"
    elif fault == "step":
        outputs[1]["export_settings"]["step"] = 99
    monkeypatch.setattr(diagnostic, "load_oracle", lambda *_args: b"authored")
    monkeypatch.setattr(diagnostic, "image", lambda path: np.full((1, 1, 3), int(path), np.float32))
    store: Any = SimpleNamespace(blob_path=lambda sha: sha)
    if fault != "none":
        with pytest.raises(ValueError):
            diagnostic.samples(record, "authored", store)
        return
    images = diagnostic.samples(record, "authored", store)
    assert len(images) == 4
    for value in images.values():
        np.testing.assert_array_equal(value, np.repeat(np.arange(8), 3).reshape(1, 1, 24))

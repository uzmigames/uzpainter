"""CPU-only cross-backend contract tests; all images and bundle identities are synthetic."""

from __future__ import annotations

import copy
import json
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity import cross_backend as cb
from tools.parity.feasibility import png
from tools.parity.guard.guard import Snapshot, run_guard
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.store.store import OracleStore
from tools.parity.tier1.compare import FLIP_VERSION, FLIP_WHEEL_SHA256


def bundle(root: Path, backend: str, data: bytes | None = None, name: str = "color") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    data = data if data is not None else png.encode(np.zeros((2, 3, 3), np.uint16), 16)
    (root / "map.bin").write_bytes(data)
    doc = {
        "project_uuid": "00000000-0000-4000-8000-000000000118",
        "revision": 1,
        "project_sha256": "1" * 64,
        "evaluator_profile": "synthetic-v1",
        "build_sha256": "2" * 64,
        "resource_hashes": {"mesh": "3" * 64},
        "backend": backend,
        "adapter": "Synthetic adapter",
        "driver": "0.0",
        "files": [
            {"texture_set": "set", "map": name, "path": "map.bin", "sha256": cb.digest(data)}
        ],
    }
    path = root / "bundle.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def edit(path: Path, **changes: Any) -> None:
    doc = json.loads(path.read_text())
    doc.update(changes)
    path.write_text(json.dumps(doc), encoding="utf-8")


def pair(tmp_path: Path) -> tuple[Path, Path]:
    return bundle(tmp_path / "dx12", "dx12"), bundle(tmp_path / "vulkan", "vulkan")


def checked(a: Path, b: Path, **kwargs: Any) -> dict[str, Any]:
    result = cb.compare(a, b, **kwargs)
    assert cb.report_problems(result) == []
    return result


def test_equal_nonempty_bundle_and_cli(tmp_path: Path) -> None:
    a, b = pair(tmp_path)
    result = checked(a, b)
    assert result["outcome"] == "pass"
    assert result["maps"][0]["bytes_equal"]
    assert result["maps"][0]["differing"] == {"count": 0, "percent": 0, "total": 18}
    path = tmp_path / "report.json"
    assert cb.main([str(a), str(b), "--report", str(path)]) == 0
    assert json.loads(path.read_text()) == result
    assert "map.bin" not in path.read_text() and "Synthetic adapter" not in path.read_text()


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_uuid", "other"),
        ("revision", 2),
        ("project_sha256", "4" * 64),
        ("evaluator_profile", "other"),
        ("build_sha256", "5" * 64),
        ("resource_hashes", {"other-id": "3" * 64}),
    ],
)
def test_identity_mismatch_compares_nothing(tmp_path: Path, field: str, value: Any) -> None:
    a, b = pair(tmp_path)
    edit(b, **{field: value})
    result = checked(a, b)
    assert result["outcome"] == "fail" and result["maps"] == []
    assert result["structural"] == [{"reason": field + "_mismatch", "backend": "pair"}]


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"files": []}, "no_maps"),
        ({"files": None}, "no_maps"),
        ({"refused": True, "files": []}, "export_refused"),
        ({"backend": "cpu"}, "backend_mismatch"),
        ({"revision": True}, "identity_invalid"),
        ({"driver": ""}, "identity_invalid"),
        ({"driver": " UnKnOwN "}, "identity_invalid"),
        ({"adapter": "unknown"}, "identity_invalid"),
        ({"resource_hashes": []}, "identity_invalid"),
        ({"project_sha256": "x"}, "identity_invalid"),
    ],
)
def test_invalid_and_refused_bundles(tmp_path: Path, changes: dict[str, Any], reason: str) -> None:
    a, b = pair(tmp_path)
    edit(b, **changes)
    result = checked(a, b)
    assert result["maps"] == []
    assert result["structural"] == [{"reason": reason, "backend": "vulkan"}]


@pytest.mark.parametrize("case", ["duplicate", "hash", "missing-file", "map-set", "decode"])
def test_file_structure_fails_before_comparison(tmp_path: Path, case: str) -> None:
    a, b = pair(tmp_path)
    doc = json.loads(b.read_text())
    expected = ""
    if case == "duplicate":
        doc["files"] *= 2
        expected = "duplicate_map"
    elif case == "hash":
        doc["files"][0]["sha256"] = "f" * 64
        expected = "map_hash_mismatch"
    elif case == "missing-file":
        doc["files"][0]["path"] = "missing"
        expected = "map_unreadable"
    elif case == "map-set":
        doc["files"][0]["map"] = "other"
        expected = "map_missing"
    else:
        (b.parent / "map.bin").write_bytes(b"bad")
        doc["files"][0]["sha256"] = cb.digest(b"bad")
        expected = "map_decode_failed"
    b.write_text(json.dumps(doc))
    result = checked(a, b)
    assert result["maps"] == [] and result["outcome"] == "fail"
    assert {e["reason"] for e in result["structural"]} == {expected}


def test_16bit_one_code_regions_difference_store(tmp_path: Path) -> None:
    values = np.full((2, 3, 3), 50000, np.uint16)
    a = bundle(tmp_path / "a", "dx12", png.encode(values, 16))
    values[0, 0, 0] += 1
    b = bundle(tmp_path / "b", "vulkan", png.encode(values, 16))
    store = OracleStore.init(tmp_path / "store")
    mask = np.zeros((2, 3), np.bool_)
    mask[0, 0] = True
    result = checked(a, b, regions={"selected": mask}, store=store)
    assert result["outcome"] == "fail"
    row = result["maps"][0]
    assert row["abs_diff"]["max"] == 1 and row["differing"]["count"] == 1
    assert row["regions"][0]["differing"]["count"] == 1
    assert row["storage_format"]["bits_per_channel"] == 16
    assert len(row["private_difference_map_sha256"]) == 64


def test_different_bytes_equal_pixels_still_fail(tmp_path: Path) -> None:
    original = png.encode(np.zeros((2, 3, 3), np.uint8), 8)
    payload = b"synthetic\x00different encoder metadata"
    kind = b"tEXt"
    chunk = (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )
    different = original[:-12] + chunk + original[-12:]
    a = bundle(tmp_path / "a", "dx12", original)
    b = bundle(tmp_path / "b", "vulkan", different)
    result = checked(a, b)
    assert result["outcome"] == "fail"
    assert result["maps"][0]["differing"]["count"] == 0
    assert not result["maps"][0]["bytes_equal"]


def test_normal_id_and_alpha_diagnostics(tmp_path: Path) -> None:
    for kind, channels in (("normal", 3), ("id", 3), ("alpha", 4)):
        values = np.zeros((2, 3, channels), np.uint8)
        if kind == "normal":
            values[:] = (128, 128, 255)
        a = bundle(tmp_path / kind / "a", "dx12", png.encode(values, 8), kind)
        values[0, 0, -1] = 0 if kind == "normal" else 255
        b = bundle(tmp_path / kind / "b", "vulkan", png.encode(values, 8), kind)
        row = checked(a, b, kinds={("set", kind): kind})["maps"][0]
        if kind == "normal":
            assert row["normal"]["angular_max_deg"] > 170
            assert row["normal"]["negative_z_count"] == 1
        else:
            assert row["exact_checks"][0]["differing_count"] == 1


def test_float32_difference_is_not_quantised_to_integer(tmp_path: Path) -> None:
    exr = pytest.importorskip("OpenEXR")
    values = np.full((2, 3), 0.5, np.float32)
    files = []
    for backend in ("dx12", "vulkan"):
        path = tmp_path / f"{backend}.exr"
        with exr.File({}, {"R": values, "G": values, "B": values}) as image:
            image.write(str(path))
        files.append(bundle(tmp_path / backend, backend, path.read_bytes()))
        values = np.nextafter(values, np.float32(1))
    row = checked(*files)["maps"][0]
    assert row["storage_format"]["bits_per_channel"] == 32
    assert row["abs_diff"]["max"] == 2**-24
    assert row["differing"]["count"] == 18


def test_storage_and_shape_mismatches(tmp_path: Path) -> None:
    a, _ = pair(tmp_path)
    for bits, shape, reason in (
        (8, (2, 3, 3), "storage_format_mismatch"),
        (16, (1, 3, 3), "shape_mismatch"),
    ):
        b = bundle(tmp_path / str(bits), "vulkan", png.encode(np.zeros(shape, np.uint16), bits))
        assert checked(a, b)["structural"][0]["reason"] == reason


def test_schema_and_guard_reject_paths_and_forged_pass(tmp_path: Path) -> None:
    a, b = pair(tmp_path)
    result = checked(a, b)
    path = "parity/reports/phase3/cross-backend-synthetic.json"
    files = {path: json.dumps(result).encode()}
    snapshot = Snapshot((path,), (path,), files.__getitem__)
    assert run_guard(REPO_ROOT, snapshot, frozenset()) == []
    bad = copy.deepcopy(result)
    bad["maps"][0]["path"] = "private/image.png"
    assert validation_errors(bad, Schema.CROSS_BACKEND_REPORT)
    files[path] = json.dumps(bad).encode()
    assert run_guard(REPO_ROOT, snapshot, frozenset())
    bad = copy.deepcopy(result)
    bad["maps"] = []
    assert cb.report_problems(bad)
    bad = copy.deepcopy(result)
    bad["runs"][1]["project_sha256"] = "f" * 64
    assert cb.report_problems(bad)
    bad = copy.deepcopy(result)
    bad["maps"][0]["abs_diff"]["max"] = 1
    assert cb.report_problems(bad)
    bad = copy.deepcopy(result)
    bad["maps"][0]["abs_diff"]["mean"] = float("nan")
    assert cb.report_problems(bad)


def test_cli_missing_bundle_is_explicit_failure_report(tmp_path: Path) -> None:
    a, b = pair(tmp_path)
    report = tmp_path / "failed.json"
    assert cb.main([str(a), str(b.with_name("missing")), "--report", str(report)]) == 1
    data = json.loads(report.read_text())
    assert data["outcome"] == "fail" and not data["maps"]
    assert data["structural"] == [{"reason": "input_unreadable", "backend": "vulkan"}]


@pytest.mark.parametrize("kind", ["alpha", "id_labels"])
def test_guard_rejects_exact_check_contradicting_pass(tmp_path: Path, kind: str) -> None:
    a, b = pair(tmp_path)
    result = checked(a, b)
    result["maps"][0]["exact_checks"] = [
        {"check": kind, "equal": False, "differing_count": 1, "edge_coverage_differing_count": 1}
    ]
    assert cb.report_problems(result)
    path = "parity/reports/phase3/cross-backend-contradiction.json"
    payload = json.dumps(result).encode()
    snapshot = Snapshot((path,), (path,), lambda _: payload)
    assert run_guard(REPO_ROOT, snapshot, frozenset())
    with pytest.raises(ValueError):
        cb.write_report(tmp_path / "report.json", result)


@pytest.mark.parametrize(
    "identity",
    [
        {"version": "C:/private/oracle/project-secret.json", "sha256": FLIP_WHEEL_SHA256},
        {"version": FLIP_VERSION, "sha256": "0" * 64},
    ],
)
def test_guard_rejects_unpinned_flip_identity(tmp_path: Path, identity: dict[str, str]) -> None:
    a, b = pair(tmp_path)
    result = checked(a, b)
    result["flip_tool"] = identity
    assert validation_errors(result, Schema.CROSS_BACKEND_REPORT)
    assert cb.report_problems(result)
    path = "parity/reports/phase3/cross-backend-private-flip.json"
    payload = json.dumps(result).encode()
    assert run_guard(REPO_ROOT, Snapshot((path,), (path,), lambda _: payload), frozenset())


def test_pinned_flip_identity_is_accepted(tmp_path: Path) -> None:
    a, b = pair(tmp_path)
    result = checked(a, b)
    result["flip_tool"] = {"version": FLIP_VERSION, "sha256": FLIP_WHEEL_SHA256}
    assert cb.report_problems(result) == []


def test_guard_rejects_region_and_angle_contradictions(tmp_path: Path) -> None:
    a, b = pair(tmp_path)
    result = checked(a, b, regions={"whole": np.ones((2, 3), np.bool_)})
    result["maps"][0]["regions"][0].update(
        differing={"count": 1, "total": 18, "percent": 100 / 18},
        abs_diff={"max": 1, "mean": 1 / 18, "p99": 1},
    )
    assert cb.report_problems(result)
    result = checked(a, b, kinds={("set", "color"): "normal"})
    # Unit-length validity remains diagnostic even when equal maps contain invalid normals.
    assert result["maps"][0]["normal"]["unnormalised_count"] > 0
    result["maps"][0]["normal"]["angular_max_deg"] = 1
    assert cb.report_problems(result)


def test_cli_mapping_and_pinned_regions(tmp_path: Path) -> None:
    a, b = pair(tmp_path)
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps([{"texture_set": "set", "map": "color", "kind": "id"}]))
    data = png.encode(np.ones((2, 3, 1), np.uint8), 8)
    (tmp_path / "mask.png").write_bytes(data)
    regions = tmp_path / "regions.json"
    regions.write_text(json.dumps([{"id": "whole", "path": "mask.png", "sha256": cb.digest(data)}]))
    report = tmp_path / "result.json"
    args = [
        str(a),
        str(b),
        "--mapping",
        str(mapping),
        "--regions",
        str(regions),
        "--report",
        str(report),
    ]
    assert cb.main(args) == 0
    row = json.loads(report.read_text())["maps"][0]
    assert row["regions"][0]["region"] == "whole"
    assert row["exact_checks"][0]["check"] == "id_labels"
    regions.write_text(json.dumps([{"id": "whole", "path": "mask.png", "sha256": "0" * 64}]))
    assert cb.main(args) == 2


def test_bad_mapping_and_region_resolution_refuse(tmp_path: Path) -> None:
    a, b = pair(tmp_path)
    for kinds in ({("set", "unknown"): "normal"}, {("set", "color"): "made-up"}):
        result = checked(a, b, kinds=kinds)
        assert result["maps"] == [] and result["structural"][0]["reason"] == "mapping_invalid"
    result = checked(a, b, regions={"wrong": np.ones((7, 7), np.bool_)})
    assert result["maps"] == [] and result["structural"][0]["reason"] == "regions_invalid"


def test_id_and_alpha_count_boundary_errors(tmp_path: Path) -> None:
    for kind, channels in (("id", 3), ("alpha", 4)):
        values = np.zeros((2, 3, channels), np.uint8)
        values[:, 1:, -1] = 255
        a = bundle(tmp_path / kind / "a", "dx12", png.encode(values, 8), kind)
        values[0, 1, -1] = 0
        b = bundle(tmp_path / kind / "b", "vulkan", png.encode(values, 8), kind)
        row = checked(a, b, kinds={("set", kind): kind})["maps"][0]
        assert row["exact_checks"][0]["edge_coverage_differing_count"] == 1

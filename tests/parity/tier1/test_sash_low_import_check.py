"""The Sash low import check's comparator and bindings, on authored inspector documents."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tools.parity.recorder.session import RecorderError
from tools.parity.tier1 import sash_low_import_check as check

POSITIONS = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]]
UVS = [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]]
NORMAL = [0.0, 0.0, 1.0]


def document(triangles: list[list[int]], material: str = "m") -> dict[str, Any]:
    """An inspector document with one corner per (triangle, corner)."""
    corners: list[dict[str, Any]] = []
    indices: list[list[int]] = []
    for triangle in triangles:
        row = []
        for vertex in triangle:
            row.append(len(corners))
            corners.append(
                {
                    "position": vertex,
                    "uv0": list(UVS[vertex]),
                    "normal": list(NORMAL),
                    "material": 0,
                }
            )
        indices.append(row)
    return {
        "mesh": {
            "positions": copy.deepcopy(POSITIONS),
            "corners": corners,
            "objects": [{"name": "o", "triangles": indices}],
        },
        "report": {"materials": [{"index": 0, "name": material}]},
    }


SOURCE = document([[0, 1, 2], [1, 3, 2]])


def test_face_order_and_cyclic_rotation_are_equal() -> None:
    other = document([[3, 2, 1], [2, 0, 1]])
    result = check.compare(SOURCE, other, 0.0)
    assert result["full_multiset_equal"] and result["within_bounds"]
    assert result["normals"]["max_abs"] == 0.0


def test_reversed_winding_is_not_equal() -> None:
    other = document([[0, 2, 1], [1, 3, 2]])
    result = check.compare(SOURCE, other, 1.0)
    assert not result["position_uv_material_multiset_equal"] and not result["within_bounds"]
    assert result["diagnostics"]["identity_matches"] == 1
    assert result["diagnostics"]["reversed_winding_matches"] == 1


def test_v_mirror_is_not_equal_and_is_diagnosed() -> None:
    other = document([[0, 1, 2], [1, 3, 2]])
    for corner in other["mesh"]["corners"]:
        corner["uv0"][1] = 1.0 - corner["uv0"][1]
    result = check.compare(SOURCE, other, 1.0)
    assert not result["within_bounds"]
    assert result["diagnostics"]["v_mirrored_matches"] == 2


def test_material_name_and_moved_positions_are_compared() -> None:
    assert not check.compare(SOURCE, document([[0, 1, 2], [1, 3, 2]], "x"), 1.0)["within_bounds"]
    moved = document([[0, 1, 2], [1, 3, 2]])
    moved["mesh"]["positions"][3] = [1.0, 1.0, 1e-7]
    assert not check.compare(SOURCE, moved, 1.0)["within_bounds"]


def test_normals_are_held_to_the_declared_bound() -> None:
    other = document([[1, 2, 0], [1, 3, 2]])
    other["mesh"]["corners"][4]["normal"] = [0.0, 3e-5, 1.0]
    within = check.compare(SOURCE, other, 6.5e-5)
    assert within["position_uv_material_multiset_equal"] and not within["full_multiset_equal"]
    assert within["within_bounds"] and within["normals"]["differing_components"] == 1
    assert not check.compare(SOURCE, other, 1e-5)["within_bounds"]


def test_uv_tiles() -> None:
    other = document([[0, 1, 2]])
    other["mesh"]["corners"][0]["uv0"] = [1.5, 1.5]
    assert check.uv_tiles(SOURCE) == [1001]
    assert check.uv_tiles(other) == [1001, 1012]


def report_for(bounds: list[list[float]], **options: Any) -> dict[str, Any]:
    pinned = {
        "forward_axis": "NEGATIVE_Z",
        "up_axis": "Y",
        "global_scale": 1.0,
        "apply_transform": True,
    }
    return {
        "export": {"options": {**pinned, **options}},
        "mesh": {"bounds": bounds, "triangles": check.TRIANGLES},
    }


def bound_source() -> dict[str, Any]:
    doc = document([[0, 1, 2]])
    doc["mesh"]["positions"] = [[-1.0, 2.0, -6.0], [1.0, 3.0, -5.0], [0.0, 2.5, -5.5]]
    doc["report"].update(
        counts={"triangles": check.TRIANGLES}, flags={"v_flip": False}, units={"scale": 1.0}
    )
    return doc


def test_source_binding_maps_blender_axes() -> None:
    # Blender bounds x [-1, 1], y [5, 6], z [2, 3]; the OBJ holds (x, z, -y).
    report = report_for([[-1.0, 5.0, 2.0], [1.0, 6.0, 3.0]])
    bound = check.source_binding(bound_source(), report)
    assert bound["max_bounds_delta"] == 0.0
    with pytest.raises(RecorderError, match="bounds differ"):
        check.source_binding(bound_source(), report_for([[-1.0, 2.0, 5.0], [1.0, 3.0, 6.0]]))
    with pytest.raises(RecorderError, match="up_axis"):
        check.source_binding(bound_source(), report_for(report["mesh"]["bounds"], up_axis="Z"))


def test_scene_versus_source() -> None:
    box = {"center": [0.0, 2.5, -5.5], "dimensions": [4.0, 2.0, 2.0], "radius": 1.0}
    result = check.scene_versus_source(box, {"min": [-1.0, 2.0, -6.0], "max": [1.0, 3.0, -5.0]})
    assert result["center_delta"] == [0.0, 0.0, 0.0]
    assert result["dimension_ratio"] == [2.0, 2.0, 2.0]

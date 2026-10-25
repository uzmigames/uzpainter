"""Only fixture invariants; this does not execute the forecast or read an oracle."""

from __future__ import annotations

from tools.parity.fit.plane_offset_forecast import (
    SOURCE_TRIANGLES,
    MemoryMesh,
    mesh,
    plane_offset,
    triangles,
)


def test_plane_offset_uses_normalized_float64_normal() -> None:
    point = (7.0, -4.0, 2.0)
    assert plane_offset((0.0, 0.0, 4.0), point) == 2.0
    assert plane_offset((0.0, 0.0, 1.0), point) == 2.0


def test_only_source_triangles_change_by_cyclic_corner_permutation() -> None:
    before, after = triangles(False), triangles(True)
    assert len(before) == len(after) == 8
    for index, (a, b) in enumerate(zip(before, after, strict=True)):
        if index in SOURCE_TRIANGLES:
            assert b == (a[0][1:] + a[0][:1], a[1][1:] + a[1][:1])
        else:
            assert a == b


def test_mesh_is_deterministic_and_memory_only() -> None:
    a, b = mesh(False), mesh(True)
    assert isinstance(a, MemoryMesh)
    assert a == mesh(False) and b == mesh(True)
    assert a != b
    assert a.read_text(encoding="utf-8").count("\nf ") == 8

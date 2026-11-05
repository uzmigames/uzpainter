"""The folded-seam tie probe (`padding_fold_tie.py`): its mesh is the generator's, its dyadic
copies are exact and its offset twins are not, and the reference puts the designed ring texels'
far points on a far window boundary along the seam."""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_fold_tie as ft

MESH = REPO_ROOT / "parity/fixtures/tier0-semantics/meshes" / f"{ft.MESH}.obj"


def test_the_mesh_is_the_generators() -> None:
    assert MESH.read_bytes() == ft.mesh()


def test_every_dyadic_copy_is_exact_and_no_offset_twin_is() -> None:
    placed, _ = ft.layout()
    assert len(placed) == len(ft.FOLDS) * len(ft.TURNS) * len(ft.ACROSS) * len(ft.OFFSETS) * 2
    for copy, slot, offset in placed:
        assert ft.exact(copy, slot, offset) == (copy.twin == "dyadic"), copy.name


@pytest.fixture(scope="module")
def ties() -> dict[str, collections.Counter[tuple[int, bool]]]:
    """Per twin: (axis, exactly on the boundary in double) -> near axes of the reference's ring."""
    ref = load_module(REPO_ROOT / "tests/export/padding_reference.py", "ref_fold_tie")
    ring = ref.Ring(Path(MESH), ft.MATERIAL, ft.RESOLUTION, ft.RESOLUTION)
    placed, _ = ft.layout()
    out: dict[str, collections.Counter[tuple[int, bool]]] = {
        t: collections.Counter() for t in ft.TWINS
    }
    for x, y, _, _ in ring.texels():
        (twin,) = {
            c.twin
            for c, (sc, sr), _ in placed
            if sc - 2 <= x < sc + c.size[0] + 2 and sr - 2 <= y < sr + c.size[1] + 2
        }
        for _, axis, m, *_ in ring.near.get((x, y), []):
            out[twin][(axis, m == round(m))] += 1
    return out


def test_every_dyadic_tie_is_exact_in_double(
    ties: dict[str, collections.Counter[tuple[int, bool]]],
) -> None:
    dyadic = ties["dyadic"]
    assert dyadic[(0, True)] > 0 and dyadic[(1, True)] > 0
    assert dyadic[(0, False)] == 0 and dyadic[(1, False)] == 0


def test_the_twins_hold_the_same_ties(
    ties: dict[str, collections.Counter[tuple[int, bool]]],
) -> None:
    for axis in (0, 1):
        assert sum(n for (a, _), n in ties["offset"].items() if a == axis) == sum(
            n for (a, _), n in ties["dyadic"].items() if a == axis
        )

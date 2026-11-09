"""The seam-end overhang sweep (`padding_end_overhang.py`): its mesh is the generator's, every copy
is exact in float32, and the reference puts a ring texel's far point on a far window boundary
only on the copies with no shift, and only along the seam (rows, B at turn 0)."""

from __future__ import annotations

import collections
from pathlib import Path

from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_end_overhang as eo

MESH = REPO_ROOT / "parity/fixtures/tier0-semantics/meshes" / f"{eo.MESH}.obj"


def test_the_mesh_is_the_generators() -> None:
    assert MESH.read_bytes() == eo.mesh()


def test_every_copy_is_exact() -> None:
    placed, _ = eo.layout()
    assert len(placed) == len(eo.FOLDS) * len(eo.OVERHANGS) * len(eo.SHIFTS)
    for copy, slot, offset in placed:
        assert eo.exact(copy, slot, offset), copy.name


def test_only_unshifted_copies_tie_and_only_along_the_seam() -> None:
    ref = load_module(REPO_ROOT / "tests/export/padding_reference.py", "ref_end_overhang")
    ring = ref.Ring(Path(MESH), eo.MATERIAL, eo.RESOLUTION, eo.RESOLUTION)
    placed, _ = eo.layout()
    ties: collections.Counter[tuple[bool, int, bool]] = collections.Counter()
    for x, y, _, _ in ring.texels():
        (copy,) = [
            c
            for c, (sc, sr), _ in placed
            if sc - 2 <= x < sc + c.size[0] + 2 and sr - 2 <= y < sr + c.size[1] + 2
        ]
        for _, axis, m, *_ in ring.near.get((x, y), []):
            ties[(copy.shift == 0.0, axis, m == round(m))] += 1
    unshifted = len(eo.FOLDS) * len(eo.OVERHANGS)
    assert set(ties) == {(True, 1, True)}
    assert ties[(True, 1, True)] % unshifted == 0 and ties[(True, 1, True)] > 0

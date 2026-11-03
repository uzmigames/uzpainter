"""Decision 245 section 2's texel classes
(`tools/parity/tier0_semantics/normal_empty_height_mask.py`): the counts and membership digests
are the frozen ones, the classes partition the tile, and the covered texels are exactly
`padding_reference.Ring`'s owned texels (decision 281's raster)."""

from __future__ import annotations

import numpy as np
import pytest

from tests.export import padding_reference
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import normal_empty_height as request
from tools.parity.tier0_semantics import normal_empty_height_mask as m
from tools.parity.tier0_semantics import recording_requests as rr


def test_classes_have_the_frozen_counts_and_digests() -> None:
    found = m.frozen_classes()
    assert m.COUNTS["covered"] == m.COUNTS["interior"] + m.COUNTS["edge"]
    assert m.COUNTS["covered"] + m.COUNTS["uncovered"] == m.SIZE * m.SIZE
    total = sum(found.get(n).astype(np.int64) for n in ("interior", "edge", "uncovered"))
    assert np.all(total == 1)


def test_covered_texels_are_the_rings_owned_texels() -> None:
    ring = padding_reference.Ring(
        REPO_ROOT / rr.fixture(request.MESH)[1], request.TEXTURE_SET, m.SIZE, m.SIZE
    )
    assert np.array_equal(ring.owner >= 0, m.classes().covered)


def test_a_changed_class_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    found = m.classes()
    spoiled = m.Classes(found.covered, found.interior, found.edge.copy(), found.uncovered)
    spoiled.edge[0, 0] = not spoiled.edge[0, 0]
    monkeypatch.setattr(m, "classes", lambda: spoiled)
    with pytest.raises(ValueError):
        m.frozen_classes()

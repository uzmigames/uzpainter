"""Decision 245 section 2's texel classes on the pinned sphere at 256 px, from the authored
geometry only, never from exported values.

`covered` is `tools.parity.coverage` of the sphere's UV triangles (decision 281's raster, the
one `padding_reference.Ring.owner >= 0` reproduces). `interior` is a covered texel whose eight
neighbours are all covered, both axes wrapping (the island-normal stencil's addressing, not the
ring's x-wrap, y-outside rule); `edge` is covered minus interior; `uncovered` the rest. The counts
and the membership digests (`np.packbits` of the C-order flattened mask, big bit order) are
frozen before any capture.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from tools.parity import coverage
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import normal_empty_height as request
from tools.parity.tier0_semantics import recording_requests as rr

SIZE = 256
COUNTS = {"covered": 61440, "interior": 59264, "edge": 2176, "uncovered": 4096}
DIGESTS = {
    "covered": "01f1a76c8f3f29715f9d430c9c9c2bacfcc79d0c25d5015461038bfbb3a2b462",
    "interior": "0134bab17af35667eb58d0c2a30fd14b11eae22bcef7d3ff7b79653a1c611dae",
    "edge": "78d4e25a991de7152cf253383e7294634d3c43f43396b24deda66ed98513eb6e",
    "uncovered": "fb9daeb128aa7ed99ab85b58da6a871f2b1a7f77b3247d0b9864e48a4ef41ad1",
}

Mask = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class Classes:
    covered: Mask
    interior: Mask
    edge: Mask
    uncovered: Mask

    def get(self, name: str) -> Mask:
        mask: Mask = getattr(self, name)
        return mask


def classes() -> Classes:
    triangles = coverage.obj_triangles(REPO_ROOT / rr.fixture(request.MESH)[1], request.TEXTURE_SET)
    covered = np.asarray(coverage.coverage(triangles, SIZE, SIZE), dtype=np.bool_)
    interior = covered.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            interior &= np.roll(covered, (dy, dx), axis=(0, 1))
    return Classes(covered, interior, covered & ~interior, ~covered)


def digest(mask: Mask) -> str:
    return hashlib.sha256(np.packbits(mask.ravel(order="C"), bitorder="big").tobytes()).hexdigest()


def frozen_classes() -> Classes:
    """The classes, refused unless their counts and digests are the frozen ones."""
    found = classes()
    for name, count in COUNTS.items():
        mask = found.get(name)
        if int(mask.sum()) != count or digest(mask) != DIGESTS[name]:
            raise ValueError(f"the {name} texels of the sphere are not the frozen ones")
    return found

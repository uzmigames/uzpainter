"""The texels a generator case compares: Painter's UV coverage, eroded by one texel.

The World Space Normals map baked with no dilation holds a unit normal encoded n / 2 + 1/2 on every
texel the bake covers (never three zeros) and 0 everywhere else. A compared texel is a covered
texel whose 3 x 3 neighbourhood is covered (texels on the image border excluded). The erosion
drops the island-edge texels, where Painter's bake and its layer stack rasterize the UVs
differently: on the hat at 4096 one such texel differs between the two recordings of a golden.
Outside the compared texels an export with `passthrough` padding holds no defined output.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt


def covered_texels(normals: npt.NDArray[Any]) -> npt.NDArray[np.bool_]:
    mask: npt.NDArray[np.bool_] = np.abs(normals).sum(axis=-1) > 0
    padded = np.pad(mask, 1, constant_values=False)
    eroded = np.ones_like(mask)
    height, width = mask.shape
    for dy in range(3):
        for dx in range(3):
            eroded &= padded[dy : dy + height, dx : dx + width]
    return eroded

"""Public procedural value types; source evaluation remains subject to backend admission.

The source-resolution-values Tier 0 probe records aliases, accepted value shapes and
constructor/assignment failures. These types neither bind an asset nor edit a document.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Any

import uzpainter


class ResolutionMode(enum.Enum):
    Auto = uzpainter.source._ResolutionMode.Auto
    Asset = uzpainter.source._ResolutionMode.Document
    Custom = uzpainter.source._ResolutionMode.Manual
    TextureSet = uzpainter.source._ResolutionMode.TextureSet
    UVTile = uzpainter.source._ResolutionMode.UVTile
    Document = Asset
    Manual = Custom

    @classmethod
    def _missing_(cls, value: object) -> ResolutionMode | None:
        for member in cls:
            if value == int(member.value):
                return member
        return None


def _check_resolution(value: Any) -> None:
    if len(value) != 2:
        raise AssertionError("Attribut 'value': resolution should be a list of 2 values.")
    for size in value:
        if size <= 0 or not math.log2(size).is_integer():
            raise ValueError("Attribut 'value': resolution values should be a power of 2")
    if any(size < 128 or size > 4096 for size in value):
        raise ValueError(
            "Attribut 'value': resolution values should always be superior to 128 "
            "and inferior to 4096"
        )


@dataclass
class ResolutionOverride:
    mode: ResolutionMode
    value: tuple[int, int] | list[int]  # constructors take either; the getter returns a list
    log2_offset: int

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "value":
            _check_resolution(value)
        object.__setattr__(self, name, value)


ResolutionMode.__module__ = "substance_painter.source"
ResolutionOverride.__module__ = "substance_painter.source"

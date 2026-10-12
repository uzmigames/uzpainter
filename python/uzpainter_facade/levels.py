"""`substance_painter.levels`: Painter's levels parameters as dataclasses (their documented form:
`dataclasses.replace` edits them), converted to and from the native classes."""

from __future__ import annotations

import dataclasses
from typing import Any

import uzpainter

MODULE = "substance_painter.levels"
Triple = tuple[float, float, float]


@dataclasses.dataclass
class LevelsParamsMono:
    """Levels parameters of a mono channel."""

    input_min: float = 0.0
    input_max: float = 1.0
    gamma: float = 1.0
    output_min: float = 0.0
    output_max: float = 1.0
    clamp: bool = False


@dataclasses.dataclass
class LevelsParamsRGB:
    """Levels parameters of an RGB channel."""

    input_min: Triple = (0.0, 0.0, 0.0)
    input_max: Triple = (1.0, 1.0, 1.0)
    gamma: Triple = (1.0, 1.0, 1.0)
    output_min: Triple = (0.0, 0.0, 0.0)
    output_max: Triple = (1.0, 1.0, 1.0)
    clamp: bool = False


for _cls in (LevelsParamsMono, LevelsParamsRGB):
    _cls.__module__ = MODULE

FIELDS = ("input_min", "input_max", "gamma", "output_min", "output_max")


def to_native(params: Any) -> Any:
    if isinstance(params, LevelsParamsMono):
        return uzpainter.levels.LevelsParamsMono(
            *(float(getattr(params, name)) for name in FIELDS), bool(params.clamp)
        )
    if isinstance(params, LevelsParamsRGB):
        return uzpainter.levels.LevelsParamsRGB(
            *(tuple(float(v) for v in getattr(params, name)) for name in FIELDS),
            bool(params.clamp),
        )
    raise TypeError("params must be a levels.LevelsParamsMono or levels.LevelsParamsRGB")


def from_native(native: Any) -> Any:
    if isinstance(native, uzpainter.levels.LevelsParamsRGB):

        def triple(name: str) -> Triple:
            r, g, b = (float(v) for v in getattr(native, name))
            return (r, g, b)

        return LevelsParamsRGB(
            input_min=triple("input_min"),
            input_max=triple("input_max"),
            gamma=triple("gamma"),
            output_min=triple("output_min"),
            output_max=triple("output_max"),
            clamp=bool(native.clamp),
        )
    return LevelsParamsMono(
        input_min=float(native.input_min),
        input_max=float(native.input_max),
        gamma=float(native.gamma),
        output_min=float(native.output_min),
        output_max=float(native.output_max),
        clamp=bool(native.clamp),
    )

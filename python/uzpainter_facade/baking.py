"""`substance_painter.baking`: the bake parameters over the native `uzpainter.baking`
(`python/FACADE.md` §2; phase3.1_baker-request-model, decision 323).

`BakingParameters` holds its native handle and resolves it again on every call. `common()` and
`baker(usage)` return the native `properties.Property` handles, so a `Property` is the same class
whichever package reached it. The bake itself, the link groups, the texture set's baking state
setters and the UV-tile members raise `NotYetSupported` naming phase3.5_embree-bakers.
"""

from __future__ import annotations

from typing import Any

import uzpainter

from uzpainter_facade.state import edits
from uzpainter_facade.textureset import TextureSet, native_of

_baking = uzpainter.baking

CurvatureMethod = _baking.CurvatureMethod


class BakingParameters:
    """A texture set's bake parameters."""

    __slots__ = ("_native",)

    def __init__(self, material_id: Any) -> None:
        # Painter's constructor takes the texture set's uid; the facade also passes a native handle.
        native = material_id
        if not isinstance(native, _baking.BakingParameters):
            native = _baking.BakingParameters(material_id)
        self._native = native

    @staticmethod
    def from_texture_set(texture_set: Any) -> BakingParameters:
        return BakingParameters(_baking.BakingParameters.from_texture_set(native_of(texture_set)))

    @staticmethod
    def from_texture_set_name(texture_set_name: str) -> BakingParameters:
        return BakingParameters(_baking.BakingParameters.from_texture_set_name(texture_set_name))

    def texture_set(self) -> TextureSet:
        return TextureSet(self._native.texture_set())

    def common(self) -> dict[str, Any]:
        return dict(self._native.common())

    def baker(self, baked_map: Any) -> dict[str, Any]:
        return dict(self._native.baker(baked_map))

    @staticmethod
    @edits
    def set(property_values: dict[Any, Any]) -> None:
        _baking.BakingParameters.set(property_values)

    def get_curvature_method(self) -> Any:
        return self._native.get_curvature_method()

    def get_enabled_bakers(self) -> list[Any]:
        return list(self._native.get_enabled_bakers())

    def is_textureset_enabled(self) -> bool:
        return bool(self._native.is_textureset_enabled())

    # Release gaps (phase3.5_embree-bakers; decision 323): the native call raises before any change.
    def set_textureset_enabled(self, enable: bool) -> None:
        self._native.set_textureset_enabled(enable)

    def set_enabled_bakers(self, enabled_usages: list[Any]) -> None:
        self._native.set_enabled_bakers(enabled_usages)

    def is_baker_enabled(self, usage: Any) -> bool:
        return bool(self._native.is_baker_enabled(usage))

    def set_baker_enabled(self, usage: Any, enable: bool) -> None:
        self._native.set_baker_enabled(usage, enable)

    def set_curvature_method(self, method: Any) -> None:
        self._native.set_curvature_method(method)

    def get_enabled_uv_tiles(self) -> list[Any]:
        return list(self._native.get_enabled_uv_tiles())

    def set_enabled_uv_tiles(self, uv_tiles: list[Any]) -> None:
        self._native.set_enabled_uv_tiles(uv_tiles)

    def is_uv_tile_enabled(self, uv_tile: Any) -> bool:
        return bool(self._native.is_uv_tile_enabled(uv_tile))

    def set_uv_tile_enabled(self, uv_tile: Any, enable: bool) -> None:
        self._native.set_uv_tile_enabled(uv_tile, enable)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BakingParameters) and self._native == other._native

    def __hash__(self) -> int:
        return hash(self._native)

    def __repr__(self) -> str:
        return f"BakingParameters({self._native.texture_set().name()!r})"

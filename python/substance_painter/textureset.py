"""Painter's documented `substance_painter.textureset` module: the facade over the native
`uzpainter` module (texture sets, stacks and channels). Documented symbols only; the
implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter_facade.textureset import (
    Channel,
    ChannelFormat,
    ChannelType,
    MeshMapUsage,
    Resolution,
    Stack,
    TextureSet,
    all_texture_sets,
    get_active_stack,
    set_active_stack,
    set_resolutions,
)

__all__ = [
    "Channel",
    "ChannelFormat",
    "ChannelType",
    "MeshMapUsage",
    "Resolution",
    "Stack",
    "TextureSet",
    "all_texture_sets",
    "get_active_stack",
    "set_active_stack",
    "set_resolutions",
]

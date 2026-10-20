"""`substance_painter.textureset`: texture sets, stacks and channels over the native handles
(`python/FACADE.md` §2). Each object holds its native handle and resolves it again on every call;
the active stack is the native session state, the default address of calls that take a stack and
otherwise inert (10 §3)."""

from __future__ import annotations

from typing import Any

import uzpainter

from uzpainter_facade import resource
from uzpainter_facade.state import RESOURCE_METADATA, SESSION, edits, one_transaction

MODULE = "substance_painter.textureset"
_ts = uzpainter.textureset

ChannelType = _ts.ChannelType
ChannelFormat = _ts.ChannelFormat
MeshMapUsage = _ts.MeshMapUsage
Resolution = _ts.Resolution


# The project Metadata key of the resource names the mesh-map bindings were given:
# `{"<texture set>/<usage>": [name, sha256]}`. A native binding holds the content hash only, and
# two project resources may hold the same bytes under two names, which Painter keeps apart
# (`phase1-create-mesh-maps` s7 and s10, s3 and s11, s8 and s12; decision 319).
MESH_MAP_NAMES = "mesh_map_names"


def mesh_map_names() -> dict[str, list[str]]:
    value = uzpainter.project.Metadata(RESOURCE_METADATA).get(MESH_MAP_NAMES)
    return dict(value) if isinstance(value, dict) else {}


def native_of(value: Any) -> Any:
    """The native handle of a facade TextureSet, Stack or Channel (or a native handle as is)."""
    return getattr(value, "_native", value)


class Channel:
    """A channel of a stack."""

    __slots__ = ("_native",)

    def __init__(self, channel_id: Any) -> None:
        self._native = native_of(channel_id)

    def format(self) -> Any:
        return self._native.format()

    def label(self) -> str:
        return str(self._native.label())

    def is_color(self) -> bool:
        return bool(self._native.is_color())

    def is_floating(self) -> bool:
        return bool(self._native.is_floating())

    def bit_depth(self) -> int:
        return int(self._native.bit_depth())

    def type(self) -> Any:
        return self._native.type()

    @edits
    def edit(self, channel_format: Any, label: str | None = None) -> None:
        self._native.edit(channel_format, label)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Channel) and self._native == other._native

    def __hash__(self) -> int:
        return hash(self._native.type())

    def __repr__(self) -> str:
        return f"Channel({self._native.type().name})"


class Stack:
    """A layer stack of a texture set."""

    __slots__ = ("_native",)

    def __init__(self, stack_id: Any) -> None:
        self._native = native_of(stack_id)

    @staticmethod
    def from_name(texture_set_name: str, stack_name: str = "") -> Stack:
        return Stack(_ts.Stack.from_name(texture_set_name, stack_name))

    def name(self) -> str:
        return str(self._native.name())

    def material(self) -> TextureSet:
        return TextureSet(self._native.material())

    def all_channels(self) -> dict[Any, Channel]:
        return {kind: Channel(channel) for kind, channel in self._native.all_channels().items()}

    @edits
    def add_channel(
        self, channel_type: Any, channel_format: Any, label: str | None = None
    ) -> Channel:
        return Channel(self._native.add_channel(channel_type, channel_format, label))

    @edits
    def remove_channel(self, channel_type: Any) -> None:
        self._native.remove_channel(channel_type)

    @edits
    def edit_channel(
        self, channel_type: Any, channel_format: Any, label: str | None = None
    ) -> None:
        self._native.edit_channel(channel_type, channel_format, label)

    def has_channel(self, channel_type: Any) -> bool:
        return bool(self._native.has_channel(channel_type))

    def get_channel(self, channel_type: Any) -> Channel:
        return Channel(self._native.get_channel(channel_type))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Stack) and self._native == other._native

    def __hash__(self) -> int:
        return hash(self._native)

    def __repr__(self) -> str:
        return f"Stack({self._native.material().name()!r}, {self._native.name()!r})"


class TextureSet:
    """A texture set of the project."""

    __slots__ = ("_native",)

    def __init__(self, material_id: Any) -> None:
        self._native = native_of(material_id)

    @staticmethod
    def from_name(texture_set_name: str) -> TextureSet:
        return TextureSet(_ts.TextureSet.from_name(texture_set_name))

    def name(self) -> str:
        return str(self._native.name())

    def original_name(self) -> str:
        return str(self._native.original_name())

    def description(self) -> str:
        return str(self._native.description())

    def is_layered_material(self) -> bool:
        return False  # material layering is a release gap; no Phase 1 texture set is layered

    def all_stacks(self) -> list[Stack]:
        return [Stack(stack) for stack in self._native.all_stacks()]

    def get_stack(self, stack_name: str = "") -> Stack:
        return Stack(self._native.get_stack(stack_name))

    def get_resolution(self) -> Any:
        return self._native.get_resolution()

    @edits
    def set_resolution(self, new_resolution: Any) -> None:
        self._native.set_resolution(new_resolution)

    def get_mesh_map_resource(self, usage: Any) -> resource.ResourceID | None:
        native = self._native.get_mesh_map_resource(usage)
        if native is None:
            return None
        key = ("mesh_map", self._native.uid(), usage.name)
        found = resource.from_native(native, SESSION.bound_context.get(key))
        given = mesh_map_names().get(f"{self._native.name()}/{usage.name}")
        if given is not None and given[1] == native.version:
            return resource.ResourceID(found.context, given[0], found.version)
        return found

    @edits
    def set_mesh_map_resource(self, usage: Any, new_mesh_map: Any) -> None:
        key = ("mesh_map", self._native.uid(), usage.name)
        name = f"{self._native.name()}/{usage.name}"
        names = mesh_map_names()
        with one_transaction("textureset.TextureSet.set_mesh_map_resource"):
            if new_mesh_map is None:
                self._native.set_mesh_map_resource(usage, None)
                SESSION.bound_context.pop(key, None)
                names.pop(name, None)
            else:
                native = resource.to_native(new_mesh_map)
                self._native.set_mesh_map_resource(usage, native)
                SESSION.bound_context[key] = new_mesh_map.context
                names[name] = [str(native.name), str(native.version)]
            if names != mesh_map_names():
                uzpainter.project.Metadata(RESOURCE_METADATA).set(MESH_MAP_NAMES, names)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TextureSet) and self._native == other._native

    def __hash__(self) -> int:
        return hash(self._native)

    def __repr__(self) -> str:
        return f"TextureSet({self._native.name()!r})"


for _cls in (Channel, Stack, TextureSet):
    _cls.__module__ = MODULE


def all_texture_sets() -> list[TextureSet]:
    return [TextureSet(native) for native in _ts.all_texture_sets()]


def get_active_stack() -> Stack:
    return Stack(_ts.get_active_stack())


def set_active_stack(stack: Any) -> None:
    _ts.set_active_stack(native_of(stack))


@edits
def set_resolutions(texturesets: Any, new_resolution: Any) -> None:
    _ts.set_resolutions([native_of(t) for t in texturesets], new_resolution)

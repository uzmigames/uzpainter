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

_CHANNEL_ALIASES = {
    "AbsorptionColor": "TransmissionColor",
    "Anisotropylevel": "SpecularRoughnessAnisotropy",
    "CoatOpacity": "CoatWeight",
    "Emissive": "EmissionColor",
    "Metallic": "BaseMetalness",
    "Roughness": "SpecularRoughness",
    "Scattering": "SubsurfaceRadiusScale",
    "ScatteringColor": "SubsurfaceColor",
    "SheenColor": "FuzzColor",
    "SheenOpacity": "FuzzWeight",
    "SheenRoughness": "FuzzRoughness",
    "SpecularEdgeColor": "SpecularColor",
    "Translucency": "SubsurfaceWeight",
}


class _ChannelTypeMeta(type(_ts.ChannelType)):  # type: ignore[misc]
    @property
    def __members__(cls) -> dict[str, Any]:
        return dict(cls._members)

    def __call__(cls, value: Any) -> Any:
        native = _ts.ChannelType(value)
        return cls._members[_CHANNEL_ALIASES.get(native.name, native.name)]


ChannelType = _ChannelTypeMeta(
    "ChannelType",
    (_ts.ChannelType,),
    {"__module__": MODULE, "__doc__": "Painter channel names and their canonical aliases."},
)


# Keep native channel identities unchanged. Facade members remain native-compatible values.
ChannelType._members = {}
for _name, _native in _ts.ChannelType.__members__.items():
    if _name not in _CHANNEL_ALIASES:
        _member = type(_ts.ChannelType).__call__(ChannelType, _native)
        ChannelType._members[_name] = _member
        setattr(ChannelType, _name, _member)
for _alias, _canonical in _CHANNEL_ALIASES.items():
    _member = ChannelType._members[_canonical]
    ChannelType._members[_alias] = _member
    setattr(ChannelType, _alias, _member)
ChannelType.__module__ = MODULE

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
        return ChannelType(self._native.type())

    @edits
    def edit(self, channel_format: Any, label: str | None = None) -> None:
        self._native.edit(
            channel_format, label or "" if self.type().name.startswith("User") else ""
        )

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
        return {
            ChannelType(kind): Channel(channel)
            for kind, channel in self._native.all_channels().items()
        }

    @edits
    def add_channel(
        self, channel_type: Any, channel_format: Any, label: str | None = None
    ) -> Channel:
        kind = ChannelType(channel_type)
        if self._native.has_channel(kind):
            raise ValueError("This channel already exists.")
        return Channel(
            self._native.add_channel(
                kind, channel_format, label if kind.name.startswith("User") else None
            )
        )

    @edits
    def remove_channel(self, channel_type: Any) -> None:
        self._native.remove_channel(self._require_channel(channel_type))

    @edits
    def edit_channel(
        self, channel_type: Any, channel_format: Any, label: str | None = None
    ) -> None:
        kind = self._require_channel(channel_type)
        self._native.edit_channel(
            kind, channel_format, label or "" if kind.name.startswith("User") else ""
        )

    def has_channel(self, channel_type: Any) -> bool:
        return bool(self._native.has_channel(ChannelType(channel_type)))

    def get_channel(self, channel_type: Any) -> Channel:
        return Channel(self._native.get_channel(self._require_channel(channel_type)))

    def _require_channel(self, channel_type: Any) -> Any:
        kind = ChannelType(channel_type)
        if not self._native.has_channel(kind):
            name = kind.name[0].lower() + kind.name[1:]
            raise ValueError(
                f"There is no channel '{name}' in the texture set "
                f"'{self._native.material().name()}'."
            )
        return kind

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Stack) and self._native == other._native

    def __hash__(self) -> int:
        return hash(self._native)

    def __repr__(self) -> str:
        return f"Stack({self._native.material().name()!r}, {self._native.name()!r})"


class _CallableName(str):
    def __call__(self) -> str:
        return str(self)


class TextureSet:
    """A texture set of the project."""

    __slots__ = ("_native",)

    def __init__(self, material_id: Any) -> None:
        self._native = native_of(material_id)

    @staticmethod
    def from_name(texture_set_name: str) -> TextureSet:
        try:
            return TextureSet(_ts.TextureSet.from_name(texture_set_name))
        except ValueError:
            raise ValueError(f"Texture Set '{texture_set_name}' not found.") from None

    @property
    def name(self) -> _CallableName:
        return _CallableName(self._native.name())

    @property
    def original_name(self) -> str:
        return str(self._native.original_name())

    @property
    def description(self) -> str:
        return str(self._native.description())

    @description.setter
    @edits
    def description(self, value: str) -> None:
        self._native._set_description(value)

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
        for dimension in (new_resolution.width, new_resolution.height):
            if dimension > 0 and dimension & (dimension - 1):
                raise ValueError(
                    f"{dimension} is not a power of two. The resolution must be power of two "
                    "and in the range [128,4096]. The available resolutions are "
                    "128,256,512,1024,2048."
                )
        self._native.set_resolution(new_resolution)

    def get_mesh_map_resource(self, usage: Any) -> resource.ResourceID | None:
        native = self._native.get_mesh_map_resource(usage)
        if native is None:
            return None
        key = ("mesh_map", self._native.uid(), usage.name)
        found = resource.from_native(native, SESSION.bound_context.get(key))
        return resource.ResourceID(found.context, self._bound_name(usage, native), found.version)

    def _bound_name(self, usage: Any, native: Any) -> str:
        """The name of the resource the mesh map `usage` binds (`native`): the name it was given,
        while its content is the one bound."""
        given = mesh_map_names().get(f"{self._native.name()}/{usage.name}")
        return given[0] if given is not None and given[1] == native.version else str(native.name)

    @edits
    def set_mesh_map_resource(self, usage: Any, new_mesh_map: Any) -> None:
        with one_transaction("textureset.TextureSet.set_mesh_map_resource"):
            self._bind_mesh_map(usage, new_mesh_map)

    def _bind_mesh_map(self, usage: Any, new_mesh_map: Any) -> None:
        """Binds the mesh map `usage` to `new_mesh_map` (or unbinds it) with the name it is given,
        inside the caller's transaction."""
        key = ("mesh_map", self._native.uid(), usage.name)
        name = f"{self._native.name()}/{usage.name}"
        names = mesh_map_names()
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


def replace_mesh_map_resource(old: Any, new_mesh_map: Any) -> bool:
    """Binds every mesh map that binds the native resource `old` (its name and content) to the
    resource `new_mesh_map`, under that resource's name, inside the caller's transaction, as
    `resource.update_layer_stack_resource` does (`phase1-mesh-map-update` s9-s10, both
    recordings); whether one was bound to `old`. A mesh map bound to another name of the same
    bytes keeps its binding (`p22b-mesh-map-alias-update` s9-s11, both recordings)."""
    if isinstance(new_mesh_map, resource.Resource):
        new_mesh_map = new_mesh_map.identifier()
    replaced = False
    for texture_set in all_texture_sets():
        for usage in MeshMapUsage.__members__.values():
            bound = texture_set._native.get_mesh_map_resource(usage)
            if bound is None or bound.version != old.version:
                continue
            if texture_set._bound_name(usage, bound) == old.name:
                texture_set._bind_mesh_map(usage, new_mesh_map)
                replaced = True
    return replaced


def get_active_stack() -> Stack:
    return Stack(_ts.get_active_stack())


def set_active_stack(stack: Any) -> None:
    _ts.set_active_stack(native_of(stack))


@edits
def set_resolutions(texturesets: Any, new_resolution: Any) -> None:
    _ts.set_resolutions([native_of(t) for t in texturesets], new_resolution)

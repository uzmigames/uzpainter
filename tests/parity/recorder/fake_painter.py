"""A fake `substance_painter` package and remote endpoint for recorder tests (no Painter needed).

The fake implements just the documented surface `painter_side.py` uses, with simple behaviour
(it does not model Painter's compositing). `LocalTransport` mimics the documented remote control:
an expression returns its JSON-encoded value, statements return null, errors come back as
`{"error": {"description": ...}}`, and the namespace persists for the life of one fake process.
"""

from __future__ import annotations

import enum
import json
import struct
import sys
import types
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.recorder.session import RemoteError


def write_png(
    path: Path,
    width: int,
    height: int,
    pixels: list[tuple[int, ...]],
    bit_depth: int = 16,
    srgb_chunk: bool = False,
    filters: list[int] | None = None,
) -> None:
    """Write a non-interlaced grey/GA/RGB/RGBA PNG; `filters` gives each row's filter type."""
    channels = len(pixels[0])
    color_type = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    size = bit_depth // 8
    bpp = channels * size
    rows = []
    for y in range(height):
        line = b"".join(
            v.to_bytes(size, "big") for px in pixels[y * width : (y + 1) * width] for v in px
        )
        rows.append(line)
    raw = bytearray()
    previous = bytes(len(rows[0]))
    for y, line in enumerate(rows):
        kind = filters[y] if filters else 0
        out = bytearray()
        for i, value in enumerate(line):
            left = line[i - bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i - bpp] if i >= bpp else 0
            if kind == 0:
                predicted = 0
            elif kind == 1:
                predicted = left
            elif kind == 2:
                predicted = up
            elif kind == 3:
                predicted = (left + up) // 2
            else:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                predicted = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
            out.append((value - predicted) & 0xFF)
        raw += bytes([kind]) + out
        previous = line

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    if srgb_chunk:
        data += chunk(b"sRGB", b"\x00")
    data += chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")
    path.write_bytes(data)


class ProjectError(Exception):
    pass


class ChannelType(enum.Enum):
    BaseColor = 1
    Roughness = 2
    Metallic = 3
    Normal = 4
    Height = 5


class ChannelFormat(enum.Enum):
    sRGB8 = 1
    L8 = 2
    RGB16 = 3
    RGB16F = 4


class BlendingMode(enum.Enum):
    Normal = 1
    Multiply = 2
    Screen = 3


class SourceMode(enum.Enum):
    Split = 1
    Material = 2


class GenericColorSpace(enum.Enum):
    sRGB = 1
    Working = 2
    Raw = 3


class LegacyColorSpace(enum.Enum):
    Linear = 1
    sRGB = 2


class DataColorSpace(enum.Enum):
    Data = 1


class NormalColorSpace(enum.Enum):
    OpenGL = 1


class NormalMapFormat(enum.Enum):
    OpenGL = 1
    DirectX = 2


class TangentSpace(enum.Enum):
    PerVertex = 1
    PerFragment = 2


class ProjectWorkflow(enum.Enum):
    Default = 1


class ProjectSaveMode(enum.Enum):
    Full = 1
    Incremental = 2


# Top-level keys of the documented `json_config`; the fake refuses any other, as a stand-in for
# Painter's ValueError on an invalid configuration.
DOCUMENTED_EXPORT_KEYS = frozenset(
    {
        "exportPath",
        "exportShaderParams",
        "defaultExportPreset",
        "exportPresets",
        "exportList",
        "exportParameters",
    }
)


class ExportStatus(enum.Enum):
    Success = 0
    Cancelled = 1
    Warning = 2
    Error = 3


class UIMode(enum.Enum):
    Edition = 1
    Visualisation = 2
    Baking = 4


class CameraProjectionType(enum.Enum):
    Perspective = 1
    Orthographic = 2


class ToneMappingFunction(enum.Enum):
    Linear = 1
    ACES = 2


class Usage(enum.Enum):
    ENVIRONMENT = 1
    TEXTURE = 2
    COLOR_LUT = 3


class MeshMapUsage(enum.Enum):
    Normal = 1
    WorldSpaceNormal = 2
    ID = 3
    AO = 4
    Curvature = 5
    Position = 6
    Thickness = 7
    Height = 8
    BentNormals = 9
    Opacity = 10


class CurvatureMethod(enum.Enum):
    FromMesh = 1
    FromNormalMap = 2


class BakingStatus(enum.Enum):
    Success = 0
    Cancel = 1
    Fail = 2


# Documented `meshMap` export names of the bakers the fake bakes.
MESH_MAP_EXPORTS = {
    "normal_base": MeshMapUsage.Normal,
    "world_space_normals": MeshMapUsage.WorldSpaceNormal,
    "ambient_occlusion": MeshMapUsage.AO,
}


class BakingProcessEnded:
    def __init__(self, status: BakingStatus) -> None:
        self.status = status


CHANNEL_FORMATS = {
    ChannelType.BaseColor: ChannelFormat.sRGB8,
    ChannelType.Roughness: ChannelFormat.L8,
    ChannelType.Metallic: ChannelFormat.L8,
    ChannelType.Normal: ChannelFormat.RGB16F,
    ChannelType.Height: ChannelFormat.L8,
}


class Color:
    def __init__(self, r: float, g: float, b: float, color_space: Any = None) -> None:
        self.values = (r, g, b)
        self.color_space = color_space

    @property
    def working(self) -> tuple[float, float, float]:
        if self.color_space == GenericColorSpace.sRGB:
            r, g, b = (
                c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in self.values
            )
            return (r, g, b)
        return self.values


class SourceBitmap:
    """An image source of one channel of a fake layer; its colour space lives on the layer."""

    def __init__(self, layer: Layer, channel: ChannelType, resource_id: Any) -> None:
        self.layer, self.channel, self.resource_id = layer, channel, resource_id

    def get_color_space(self) -> GenericColorSpace:
        return self.layer.bitmaps[self.channel]

    def set_color_space(self, space: GenericColorSpace) -> None:
        self.layer.bitmaps[self.channel] = space

    def list_available_color_spaces(self) -> list[Any]:
        """One member of each documented colour-space class, and an OCIO name (a string)."""
        return [
            GenericColorSpace.sRGB,
            GenericColorSpace.Raw,
            LegacyColorSpace.Linear,
            DataColorSpace.Data,
            NormalColorSpace.OpenGL,
            "ACEScg",
        ]


class SourceUniformColor:
    def __init__(self, color: Color) -> None:
        self.color = color

    def get_color(self) -> Color:
        return Color(*self.color.working, GenericColorSpace.Working)


@dataclass
class Property:
    data: Any
    widget: str
    text: str

    def value(self) -> Any:
        return self.data

    def widget_type(self) -> str:
        return self.widget

    def label(self) -> str:
        return self.text


@dataclass(eq=False)
class BakingProperty:
    """A baking parameter with the documented `properties.Property` getters (authored values).

    Hashable by identity: `BakingParameters.set` takes a dict keyed by properties."""

    key: str
    widget: str
    data: Any
    enum: dict[str, int] = field(default_factory=dict)

    def value(self) -> Any:
        return self.data

    def name(self) -> str:
        return f"fake/{self.key}"

    def short_name(self) -> str:
        return self.key

    def label(self) -> str:
        return self.key.replace("_", " ").title()

    def widget_type(self) -> str:
        return self.widget

    def enum_values(self) -> dict[str, int]:
        return dict(self.enum)

    def enum_value(self, enum_label: str) -> int:
        return self.enum[enum_label]

    def properties(self) -> dict[str, Any]:
        return {"min": 0, "max": 10} if self.widget == "Slider" else {}


def fake_baking_parameters() -> dict[str, dict[str, BakingProperty]]:
    """Authored stand-in parameters: `common` and one group per MeshMapUsage name."""
    groups = {
        "common": {
            "fake_size": BakingProperty("fake_size", "Slider", (8, 8)),
            "fake_mode": BakingProperty("fake_mode", "Combobox", 1, {"First": 0, "Second": 1}),
            "fake_tint": BakingProperty(
                "fake_tint", "Color", Color(0.25, 0.5, 0.75, GenericColorSpace.Working)
            ),
            "HipolyMesh": BakingProperty("HipolyMesh", "FileList", ""),
        }
    }
    for usage in MeshMapUsage:
        groups[usage.name] = {
            "fake_strength": BakingProperty("fake_strength", "Slider", float(usage.value)),
            "fake_filter": BakingProperty("fake_filter", "Combobox", 0, {"Off": 0, "On": 1}),
        }
    return groups


class SourceSubstance:
    """A procedural source; its properties are fixed fake values."""

    def __init__(self, url: str) -> None:
        self.url = url

    def get_properties(self) -> dict[str, Property]:
        return {
            "scale": Property(1.5, "Slider", "Scale"),
            "tint": Property(
                (Color(0.25, 0.5, 1.0, GenericColorSpace.Working), 0.5), "Color", "Tint"
            ),
            "seed": Property(7, "RandomSeed", "Random Seed"),
        }


class Resolution:
    def __init__(self, width: int = 1024, height: int = 1024) -> None:
        self.width = width
        self.height = height


@dataclass
class Channel:
    kind: ChannelType
    channel_format: ChannelFormat | None = None

    def format(self) -> ChannelFormat:
        return self.channel_format or CHANNEL_FORMATS[self.kind]

    def bit_depth(self) -> int:
        return 16 if self.kind == ChannelType.Normal else 8

    def is_color(self) -> bool:
        return self.kind in (ChannelType.BaseColor, ChannelType.Normal)

    def is_floating(self) -> bool:
        return self.kind == ChannelType.Normal

    def label(self) -> str:
        return ""


@dataclass
class Layer:
    uid_value: int
    channels: set[ChannelType]
    sources: dict[ChannelType, Color] = field(default_factory=dict)
    substances: dict[ChannelType, str] = field(default_factory=dict)
    # Bitmap sources (an image resource) by channel: their colour space.
    bitmaps: dict[ChannelType, GenericColorSpace] = field(default_factory=dict)
    blending: dict[ChannelType, BlendingMode] = field(default_factory=dict)
    opacity: dict[ChannelType, float] = field(default_factory=dict)


class FakeWorld:
    """State of one fake Painter process."""

    def __init__(self, export_hook: Callable[[Path], None] | None = None) -> None:
        self.project_open = False
        self.edition_polls = 0
        self.busy = False
        self.file_path: str | None = None
        self.texture_set = "uzp_plane"
        self.imported_texture_set = "uzp_plane"  # TextureSet.original_name (a UI rename keeps it)
        self.resolution = (1024, 1024)
        # Texture sets after `texture_set` (none by default) and their resolutions.
        self.other_texture_sets: list[str] = []
        self.other_resolutions: dict[str, tuple[int, int]] = {}
        # Export presets: predefined (name, url) pairs and shelf presets by resource URL.
        self.predefined_presets = [
            ("PBR Metallic Roughness", "export-preset-generator://fake-metal-rough"),
            ("Fake Packed", "export-preset-generator://fake-packed"),
        ]
        self.resource_presets = ["resource://starter_assets/Fake Engine Preset"]
        self.layers: list[Layer] = []  # bottom to top
        self.next_uid = 100
        self.ui_mode = UIMode.Edition
        self.environment: str | None = None
        self.color_lut: str | None = None
        self.scene_bounds: tuple[list[float], list[float]] = ([0.0] * 3, [0.0] * 3)
        self.tone_mapping = ToneMappingFunction.Linear
        self.camera: dict[str, Any] = {
            "projection_type": CameraProjectionType.Perspective,
            "position": [0.0, 0.0, 50.0],
            "rotation": [0.0, 0.0, 0.0],
            "field_of_view": 40.0,
            "focal_length": 50.0,
            "focus_distance": 10.0,
            "aperture": 0.1,
            "orthographic_height": 10.0,
        }
        self.export_hook = export_hook
        self.channels = dict(CHANNEL_FORMATS)
        self.shelf_path: Path | None = None  # application shelf (templates are its .spt files)
        self.template_channels: dict[str, dict[ChannelType, ChannelFormat]] = {}
        self.baking = fake_baking_parameters()
        self.enabled_bakers = [MeshMapUsage.Normal, MeshMapUsage.AO]
        # A bake ends after `bake_polls` busy polls with `bake_status` (BakingProcessEnded).
        self.bake_polls = 3
        self.bake_status = BakingStatus.Success
        self.bake_running: dict[str, Any] | None = None
        self.bakes: list[str] = []  # texture sets in the order their bakes were launched
        self.baked_maps: dict[MeshMapUsage, str] = {}  # resource URL of each baked mesh map
        self.event_handlers: dict[type, list[Callable[[Any], None]]] = {}
        self.active_stacks: list[str] = []  # texture sets made active (set_active_stack)
        self.version = "12.1.0"
        self.version_info = (12, 1, 0)
        self.js_api = "1.1.20"
        self.modules = build_modules(self)

    def require_open(self) -> None:
        if not self.project_open:
            raise ProjectError("no project is opened")

    def texture_set_names(self) -> list[str]:
        return [self.texture_set, *self.other_texture_sets]

    def resolution_of(self, texture_set: str) -> tuple[int, int]:
        if texture_set == self.texture_set:
            return self.resolution
        return self.other_resolutions[texture_set]

    def set_resolution(self, texture_set: str, size: tuple[int, int]) -> None:
        if texture_set == self.texture_set:
            self.resolution = size
        else:
            self.other_resolutions[texture_set] = size

    def advance_bake(self) -> bool:
        """One busy poll of a running bake; the last poll ends it, stores the baked mesh maps
        (on `Success`) and dispatches `BakingProcessEnded`. True while the bake still runs."""
        if self.bake_running is None:
            return False
        self.bake_running["polls"] -= 1
        if self.bake_running["polls"] > 0:
            return True
        self.bake_running = None
        if self.bake_status == BakingStatus.Success:
            for usage in self.enabled_bakers:
                self.baked_maps[usage] = f"resource://project0/baked_{usage.name}"
        for handler in list(self.event_handlers.get(BakingProcessEnded, [])):
            handler(BakingProcessEnded(self.bake_status))
        return False

    def snapshot(self) -> dict[str, Any]:
        return {
            "resolution": list(self.resolution),
            "other_resolutions": {k: list(v) for k, v in self.other_resolutions.items()},
            "channels": {c.name: f.name for c, f in self.channels.items()},
            "layers": [
                {
                    "uid": layer.uid_value,
                    "channels": sorted(c.name for c in layer.channels),
                    "sources": {c.name: list(v.working) for c, v in layer.sources.items()},
                    "substances": {c.name: url for c, url in layer.substances.items()},
                    "bitmaps": {c.name: space.name for c, space in layer.bitmaps.items()},
                    "blending": {c.name: m.name for c, m in layer.blending.items()},
                    "opacity": {c.name: o for c, o in layer.opacity.items()},
                }
                for layer in self.layers
            ],
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.resolution = (data["resolution"][0], data["resolution"][1])
        self.other_resolutions = {k: (v[0], v[1]) for k, v in data["other_resolutions"].items()}
        self.channels = {ChannelType[c]: ChannelFormat[f] for c, f in data["channels"].items()}
        self.layers = [
            Layer(
                uid_value=item["uid"] + 1000,  # uids change across reopen
                channels={ChannelType[c] for c in item["channels"]},
                sources={
                    ChannelType[c]: Color(v[0], v[1], v[2], GenericColorSpace.Working)
                    for c, v in item["sources"].items()
                },
                substances={ChannelType[c]: url for c, url in item["substances"].items()},
                bitmaps={ChannelType[c]: GenericColorSpace[v] for c, v in item["bitmaps"].items()},
                blending={ChannelType[c]: BlendingMode[m] for c, m in item["blending"].items()},
                opacity={ChannelType[c]: o for c, o in item["opacity"].items()},
            )
            for item in data["layers"]
        ]

    def composite(self, channel: ChannelType) -> tuple[float, float, float]:
        value = (0.0, 0.0, 0.0)
        for layer in self.layers:
            if channel not in layer.channels or channel not in layer.sources:
                continue
            top = layer.sources[channel].working
            if layer.blending.get(channel, BlendingMode.Normal) == BlendingMode.Multiply:
                top = (top[0] * value[0], top[1] * value[1], top[2] * value[2])
            alpha = layer.opacity.get(channel, 1.0)
            value = tuple(v + (t - v) * alpha for v, t in zip(value, top, strict=True))  # type: ignore[assignment]
        return value


def build_modules(world: FakeWorld) -> dict[str, types.ModuleType]:
    """The fake `substance_painter` package bound to one world."""

    def module(name: str, **members: Any) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in members.items():
            setattr(mod, key, value)
        return mod

    class Settings:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    def is_in_edition_state() -> bool:
        world.require_open()
        world.edition_polls += 1
        return world.edition_polls > 1  # loading is asynchronous: ready on the second poll

    def create(
        mesh_file_path: str, template_file_path: str | None = None, settings: Any = None
    ) -> None:
        if world.project_open:
            raise ProjectError("there is already an opened project")
        if not Path(mesh_file_path).is_file():
            raise ValueError("mesh file does not exist")
        world.channels = dict(CHANNEL_FORMATS)
        if template_file_path is not None:
            template = Path(template_file_path)
            if not template.is_file():
                raise ValueError("template file does not exist")
            if template.stem not in world.template_channels:
                raise ValueError("template file is invalid")
            world.channels = dict(world.template_channels[template.stem])
        world.project_open, world.edition_polls, world.file_path = True, 0, None
        points = [
            [float(v) for v in line.split()[1:4]]
            for line in Path(mesh_file_path).read_text(encoding="utf-8").splitlines()
            if line.startswith("v ")
        ]
        world.scene_bounds = (
            [min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)],
        )
        size = settings.kwargs.get("default_texture_resolution") or 1024
        world.resolution = (size, size)
        world.other_resolutions = {name: (size, size) for name in world.other_texture_sets}
        world.layers = []
        world.baked_maps = {}

    def save_as(path: str, mode: ProjectSaveMode) -> None:
        world.require_open()
        Path(path).write_text(json.dumps(world.snapshot()), encoding="utf-8")
        world.file_path = path

    def close() -> None:
        world.require_open()
        world.project_open, world.layers, world.file_path = False, [], None

    def open_(path: str) -> None:
        if world.project_open:
            raise ProjectError("there is already an opened project")
        world.restore(json.loads(Path(path).read_text(encoding="utf-8")))
        world.project_open, world.edition_polls, world.file_path = True, 0, path

    def file_path() -> str | None:
        world.require_open()
        return world.file_path

    @dataclass
    class BoundingBox:
        dimensions: list[float]
        center: list[float]
        radius: float

    def get_scene_bounding_box() -> BoundingBox:
        world.require_open()
        low, high = world.scene_bounds
        size = [h - lo for lo, h in zip(low, high, strict=True)]
        centre = [(lo + h) / 2.0 for lo, h in zip(low, high, strict=True)]
        return BoundingBox(size, centre, sum(s * s for s in size) ** 0.5 / 2.0)

    project = module(
        "substance_painter.project",
        Settings=Settings,
        NormalMapFormat=NormalMapFormat,
        TangentSpace=TangentSpace,
        ProjectWorkflow=ProjectWorkflow,
        ProjectSaveMode=ProjectSaveMode,
        is_open=lambda: world.project_open,
        is_in_edition_state=is_in_edition_state,
        is_busy=lambda: world.advance_bake() or world.busy,
        file_path=file_path,
        get_scene_bounding_box=get_scene_bounding_box,
        create=create,
        save_as=save_as,
        close=close,
        open=open_,
    )

    class TextureSet:
        def __init__(self, name: str) -> None:
            self.set_name = name

        @staticmethod
        def from_name(name: str) -> TextureSet:
            if name not in world.texture_set_names():
                raise ValueError(f"no texture set {name}")
            return TextureSet(name)

        def name(self) -> str:
            return self.set_name

        @property
        def original_name(self) -> str:
            """Painter 12.1.5 exposes the documented `original_name` as a string."""
            return world.imported_texture_set

        def get_resolution(self) -> Resolution:
            return Resolution(*world.resolution_of(self.set_name))

        def all_stacks(self) -> list[Stack]:
            return [Stack(self.set_name, "")]

        def get_mesh_map_resource(self, usage: MeshMapUsage) -> ResourceID | None:
            url = world.baked_maps.get(usage)
            return None if url is None else ResourceID.from_url(url)

        def get_stack(self) -> Stack:
            return Stack(self.set_name, "")

    class Stack:
        def __init__(self, texture_set: str, stack: str) -> None:
            self.texture_set, self.stack = texture_set, stack

        @staticmethod
        def from_name(texture_set_name: str, stack_name: str = "") -> Stack:
            return Stack(texture_set_name, stack_name)

        def name(self) -> str:
            return self.stack

        def material(self) -> TextureSet:
            return TextureSet(self.texture_set)

        def all_channels(self) -> dict[ChannelType, Channel]:
            return {kind: Channel(kind, fmt) for kind, fmt in world.channels.items()}

    def set_resolutions(sets: list[TextureSet], resolution: Resolution) -> None:
        for texture_set in sets:
            world.set_resolution(texture_set.name(), (resolution.width, resolution.height))

    def set_active_stack(stack: Stack) -> None:
        world.require_open()
        world.active_stacks.append(stack.texture_set)

    textureset = module(
        "substance_painter.textureset",
        ChannelType=ChannelType,
        ChannelFormat=ChannelFormat,
        MeshMapUsage=MeshMapUsage,
        Resolution=Resolution,
        TextureSet=TextureSet,
        Stack=Stack,
        all_texture_sets=lambda: [TextureSet(name) for name in world.texture_set_names()],
        get_active_stack=lambda: Stack(world.texture_set, ""),
        set_active_stack=set_active_stack,
        set_resolutions=set_resolutions,
    )

    class FillLayerNode:
        def __init__(self, layer: Layer) -> None:
            self.layer = layer

        @property
        def active_channels(self) -> set[ChannelType]:
            return set(self.layer.channels)

        @active_channels.setter
        def active_channels(self, channels: set[ChannelType]) -> None:
            self.layer.channels = set(channels)

        @property
        def source_mode(self) -> SourceMode:
            return SourceMode.Split

        def require(self, channel: ChannelType) -> None:
            if channel not in self.layer.channels:
                raise RuntimeError(f"channel {channel.name} is not active")

        def set_source(self, channel: ChannelType, source: Any) -> Any:
            self.require(channel)
            if isinstance(source, ResourceID):
                self.layer.substances[channel] = source.url()
                self.layer.sources.pop(channel, None)
                if source.image:
                    self.layer.bitmaps[channel] = GenericColorSpace.sRGB
                    return SourceBitmap(self.layer, channel, source)
                self.layer.bitmaps.pop(channel, None)
                return SourceSubstance(source.url())
            self.layer.sources[channel] = source
            self.layer.substances.pop(channel, None)
            return SourceUniformColor(source)

        def get_source(self, channel: ChannelType) -> Any:
            self.require(channel)
            if channel in self.layer.bitmaps:
                url = self.layer.substances[channel]
                return SourceBitmap(self.layer, channel, ResourceID.from_url(url))
            if channel in self.layer.substances:
                return SourceSubstance(self.layer.substances[channel])
            return SourceUniformColor(self.layer.sources.get(channel, Color(0.0, 0.0, 0.0)))

        def get_blending_mode(self, channel: ChannelType) -> BlendingMode:
            self.require(channel)
            return self.layer.blending.get(channel, BlendingMode.Normal)

        def set_blending_mode(self, mode: BlendingMode, channel: ChannelType) -> None:
            self.require(channel)
            self.layer.blending[channel] = mode

        def get_opacity(self, channel: ChannelType) -> float:
            self.require(channel)
            return self.layer.opacity.get(channel, 1.0)

        def set_opacity(self, opacity: float, channel: ChannelType) -> None:
            self.require(channel)
            self.layer.opacity[channel] = opacity

        def get_stack(self) -> Stack:
            return Stack(world.texture_set, "")

        def get_name(self) -> str:
            return f"Fill layer {self.layer.uid_value}"

        def get_parent(self) -> None:
            return None  # every fake fill layer is a root layer

        def is_in_mask_stack(self) -> bool:
            return False

        def uid(self) -> int:
            return self.layer.uid_value

    @dataclass
    class InsertPosition:
        index: int

        @staticmethod
        def from_textureset_stack(stack: Stack) -> InsertPosition:
            return InsertPosition(len(world.layers))

        @staticmethod
        def above_node(node: FillLayerNode) -> InsertPosition:
            return InsertPosition(world.layers.index(node.layer) + 1)

        @staticmethod
        def below_node(node: FillLayerNode) -> InsertPosition:
            return InsertPosition(world.layers.index(node.layer))

    def insert_fill(position: InsertPosition) -> FillLayerNode:
        world.require_open()
        world.next_uid += 1
        layer = Layer(world.next_uid, set(CHANNEL_FORMATS))
        world.layers.insert(position.index, layer)
        return FillLayerNode(layer)

    def get_root_layer_nodes(stack: Stack) -> list[FillLayerNode]:
        return [FillLayerNode(layer) for layer in reversed(world.layers)]  # top first

    layerstack = module(
        "substance_painter.layerstack",
        BlendingMode=BlendingMode,
        InsertPosition=InsertPosition,
        insert_fill=insert_fill,
        get_root_layer_nodes=get_root_layer_nodes,
    )

    @dataclass
    class TextureExportResult:
        status: ExportStatus
        message: str
        textures: dict[tuple[str, str], list[str]]

    def check_config(config: dict[str, Any]) -> None:
        unknown = sorted(set(config) - DOCUMENTED_EXPORT_KEYS)
        if unknown:
            raise ValueError(f"Invalid export configuration: unknown key {unknown[0]!r}")

    def list_project_textures(config: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
        world.require_open()
        check_config(config)
        out_dir = Path(config["exportPath"])
        listed: dict[tuple[str, str], list[str]] = {}
        for entry in config["exportList"]:
            for preset_map in config["exportPresets"][0]["maps"]:
                name = preset_map["fileName"].replace("$textureSet", entry["rootPath"])
                listed.setdefault((entry["rootPath"], ""), []).append(
                    (out_dir / f"{name}.png").as_posix()
                )
        return listed

    def export_project_textures(config: dict[str, Any]) -> TextureExportResult:
        world.require_open()
        check_config(config)
        out_dir = Path(config["exportPath"])
        written: dict[tuple[str, str], list[str]] = {}
        for entry in config["exportList"]:
            texture_set = entry["rootPath"]
            for preset_map in config["exportPresets"][0]["maps"]:
                name = preset_map["fileName"].replace("$textureSet", texture_set)
                path = out_dir / f"{name}.png"
                source = preset_map["channels"][0]["srcMapName"]
                size = world.resolution_of(texture_set)
                width, height = size[0] // 64 or 1, size[1] // 64 or 1
                if preset_map["channels"][0]["srcMapType"] == "virtualMap":
                    # A converted virtual map: a flat grey with no encoding chunk.
                    write_png(path, width, height, [(32768, 32768, 32768)] * (width * height))
                elif preset_map["channels"][0]["srcMapType"] == "meshMap":
                    # A baked mesh map: written only once baked, with no encoding chunk.
                    if MESH_MAP_EXPORTS[source] not in world.baked_maps:
                        continue
                    flat = (32768, 32768, 65535)
                    write_png(path, width, height, [flat] * (width * height))
                else:
                    kind = next(k for k in ChannelType if k.name.lower() == source.lower())
                    r, g, b = world.composite(kind)
                    code = tuple(round(min(max(c, 0.0), 1.0) * 65535) for c in (r, g, b))
                    write_png(path, width, height, [code] * (width * height))
                if world.export_hook is not None:
                    world.export_hook(path)
                written.setdefault((texture_set, ""), []).append(path.as_posix())
        return TextureExportResult(ExportStatus.Success, "Export done", written)

    def output_maps() -> list[dict[str, Any]]:
        """Authored stand-in output maps: one per channel of the project, in the documented
        `maps` format of the JSON configuration."""
        return [
            {
                "fileName": f"$textureSet_{kind.name}",
                "channels": [
                    {
                        "destChannel": "L",
                        "srcChannel": "L",
                        "srcMapType": "documentMap",
                        "srcMapName": kind.name.lower(),
                    }
                ],
            }
            for kind in sorted(world.channels, key=lambda c: c.name)
        ]

    @dataclass
    class PredefinedExportPreset:
        name: str
        url: str

        def list_output_maps(self, stack: Stack) -> list[dict[str, Any]]:
            world.require_open()
            if stack.texture_set not in world.texture_set_names():
                raise ValueError("the given stack is invalid")
            return output_maps()

    @dataclass
    class ResourceExportPreset:
        resource_id: ResourceID

        def list_output_maps(self) -> list[dict[str, Any]]:
            if self.resource_id.url() not in world.resource_presets:
                raise ValueError("the given preset is invalid")
            return output_maps()

    export = module(
        "substance_painter.export",
        ExportStatus=ExportStatus,
        PredefinedExportPreset=PredefinedExportPreset,
        ResourceExportPreset=ResourceExportPreset,
        export_project_textures=export_project_textures,
        list_project_textures=list_project_textures,
        list_predefined_export_presets=lambda: [
            PredefinedExportPreset(name, url) for name, url in world.predefined_presets
        ],
        list_resource_export_presets=lambda: [
            ResourceExportPreset(ResourceID.from_url(url)) for url in world.resource_presets
        ],
    )

    class Camera:
        @staticmethod
        def get_default_camera() -> Camera:
            world.require_open()
            return Camera()

    for name in world.camera:

        def getter(self: Camera, key: str = name) -> Any:
            return world.camera[key]

        def setter(self: Camera, value: Any, key: str = name) -> None:
            world.camera[key] = value

        setattr(Camera, name, property(getter, setter))

    @dataclass
    class ResourceID:
        name: str
        context: str = "project0"
        image: bool = False
        version: str | None = None

        @staticmethod
        def from_url(url: str) -> ResourceID:
            if not url.startswith("resource://"):
                raise ValueError(f"not a resource URL: {url}")
            context, _, name = url[len("resource://") :].partition("/")
            return ResourceID(name, context, name.endswith(".image"))

        def url(self) -> str:
            return f"resource://{self.context}/{self.name}"

    @dataclass
    class Resource:
        rid: ResourceID

        def identifier(self) -> ResourceID:
            return self.rid

    def set_environment_resource(rid: ResourceID) -> None:
        world.environment = rid.name

    display = module(
        "substance_painter.display",
        Camera=Camera,
        CameraProjectionType=CameraProjectionType,
        ToneMappingFunction=ToneMappingFunction,
        get_environment_resource=lambda: (
            None if world.environment is None else ResourceID(world.environment)
        ),
        set_environment_resource=set_environment_resource,
        get_color_lut_resource=lambda: (
            None if world.color_lut is None else ResourceID.from_url(world.color_lut)
        ),
        set_color_lut_resource=lambda rid: setattr(world, "color_lut", rid.url()),
        get_tone_mapping=lambda: world.tone_mapping,
        set_tone_mapping=lambda f: setattr(world, "tone_mapping", f),
    )

    class Shelf:
        def path(self) -> str:
            if world.shelf_path is None:
                raise ValueError("the shelf doesn't exist anymore")
            return str(world.shelf_path)

    class Shelves:
        @staticmethod
        def application_shelf() -> Shelf:
            return Shelf()

    resource = module(
        "substance_painter.resource",
        Usage=Usage,
        ResourceID=ResourceID,
        Shelves=Shelves,
        import_project_resource=lambda path, usage: Resource(
            ResourceID(Path(path).stem + ".image", image=True)
            if usage == Usage.TEXTURE
            else ResourceID(Path(path).stem)
        ),
        import_session_resource=lambda path, usage: Resource(
            ResourceID(Path(path).stem, "session")
        ),
    )
    ui = module(
        "substance_painter.ui",
        UIMode=UIMode,
        get_current_mode=lambda: world.ui_mode,
        switch_to_mode=lambda mode: setattr(world, "ui_mode", mode),
    )

    class BakingParameters:
        def __init__(self, texture_set: TextureSet) -> None:
            self.set_name = texture_set.name()

        @staticmethod
        def from_texture_set(texture_set: TextureSet) -> BakingParameters:
            world.require_open()
            return BakingParameters(texture_set)

        def common(self) -> dict[str, BakingProperty]:
            return dict(world.baking["common"])

        def baker(self, baked_map: MeshMapUsage) -> dict[str, BakingProperty]:
            return dict(world.baking[baked_map.name])

        def get_curvature_method(self) -> CurvatureMethod:
            return CurvatureMethod.FromMesh

        def get_enabled_bakers(self) -> list[MeshMapUsage]:
            return list(world.enabled_bakers)

        def set_enabled_bakers(self, enabled_usages: list[MeshMapUsage]) -> None:
            world.enabled_bakers = list(enabled_usages)

        def is_textureset_enabled(self) -> bool:
            return True

        @staticmethod
        def set(property_values: dict[BakingProperty, Any]) -> None:
            world.require_open()
            for prop, value in property_values.items():
                prop.data = value

    def bake_async(texture_set: TextureSet) -> object:
        world.require_open()
        if world.bake_running is not None:
            raise RuntimeError("a bake is already running")
        world.bake_running = {"texture_set": texture_set.name(), "polls": world.bake_polls}
        world.bakes.append(texture_set.name())
        return object()  # stands for the documented StopSource

    baking = module(
        "substance_painter.baking",
        BakingParameters=BakingParameters,
        BakingStatus=BakingStatus,
        CurvatureMethod=CurvatureMethod,
        bake_async=bake_async,
    )

    class Dispatcher:
        def connect(self, event_cls: type, callback: Callable[[Any], None]) -> None:
            world.event_handlers.setdefault(event_cls, []).append(callback)

        def disconnect(self, event_cls: type, callback: Callable[[Any], None]) -> None:
            world.event_handlers[event_cls].remove(callback)

    event = module(
        "substance_painter.event",
        DISPATCHER=Dispatcher(),
        Dispatcher=Dispatcher,
        BakingProcessEnded=BakingProcessEnded,
    )

    def evaluate(code: str) -> str:
        if code == "alg.version.api":
            return world.js_api
        raise RuntimeError(f"unsupported javascript {code!r}")

    modules = {
        "substance_painter.application": module(
            "substance_painter.application",
            version=lambda: world.version,
            version_info=lambda: world.version_info,
            engine_computations_status=lambda: True,
        ),
        "substance_painter.baking": baking,
        "substance_painter.colormanagement": module(
            "substance_painter.colormanagement",
            Color=Color,
            GenericColorSpace=GenericColorSpace,
            LegacyColorSpace=LegacyColorSpace,
            DataColorSpace=DataColorSpace,
            NormalColorSpace=NormalColorSpace,
        ),
        "substance_painter.display": display,
        "substance_painter.event": event,
        "substance_painter.export": export,
        "substance_painter.js": module("substance_painter.js", evaluate=evaluate),
        "substance_painter.layerstack": layerstack,
        "substance_painter.project": project,
        "substance_painter.resource": resource,
        "substance_painter.source": module(
            "substance_painter.source",
            SourceUniformColor=SourceUniformColor,
            SourceSubstance=SourceSubstance,
            SourceBitmap=SourceBitmap,
        ),
        "substance_painter.textureset": textureset,
        "substance_painter.ui": ui,
    }
    root = module("substance_painter")
    for name, mod in modules.items():
        setattr(root, name.split(".", 1)[1], mod)
    modules["substance_painter"] = root
    return modules


@contextmanager
def installed(world: FakeWorld) -> Iterator[None]:
    saved = {name: sys.modules.get(name) for name in world.modules}
    sys.modules.update(world.modules)
    try:
        yield
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class LocalTransport:
    """The documented remote-control behaviour, executing in this process against a FakeWorld."""

    def __init__(self, world: FakeWorld) -> None:
        self.world = world
        self.namespace: dict[str, Any] = {}
        self.sent: list[str] = []

    def run(self, code: str) -> Any:
        self.sent.append(code)
        with installed(self.world):
            try:
                try:
                    compiled = compile(code, "<string>", "eval")
                except SyntaxError:
                    exec(compile(code, "<string>", "exec"), self.namespace)
                    return None
                value = eval(compiled, self.namespace)
            except Exception as error:  # the endpoint reports any failure as an error object
                raise RemoteError(f"Painter could not execute the sent code: {error}") from error
        return json.loads(json.dumps(value))

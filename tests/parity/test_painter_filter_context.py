"""Execute the real extension and existing probe serializers against authored API objects."""

from __future__ import annotations

import ast
import dataclasses
import enum
import json
import math
from copy import copy
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from tools.parity.filter_context_contract import (
    CONDITIONS,
    NODE,
    SOURCE,
    ContextRefused,
    validate_census,
)
from tools.parity.recorder.filter_context import (
    PAINTER_FILTER_CONTEXT,
    context_readback,
    extension_code,
)


class ChannelType(enum.Enum):
    User0 = 1
    User1 = 2


class NodeType(enum.Enum):
    PaintLayer = 1
    FillLayer = 2
    FilterEffect = 3


class Mode(enum.Enum):
    Normal = 1
    Split = 2
    UV = 3
    Auto = 4
    L32F = 5
    BilinearHQ = 6
    Repeat = 7
    Factors = 8


@dataclasses.dataclass
class Resolution:
    width: int = 128
    height: int = 128


@dataclasses.dataclass
class Transform:
    scale_mode: Mode = Mode.Factors
    scale: list[float] = dataclasses.field(default_factory=lambda: [1.0, 1.0])
    rotation: float = -0.0
    offset: list[float] = dataclasses.field(default_factory=lambda: [0.0, 0.0])


@dataclasses.dataclass
class UVProjectionParams:
    filtering_mode: Mode = Mode.BilinearHQ
    uv_wrapping_mode: Mode = Mode.Repeat
    uv_transformation: Transform = dataclasses.field(default_factory=Transform)


@dataclasses.dataclass
class GeometryMaskMeshParams:
    inclusion_list: bool = False
    meshes: list[str] = dataclasses.field(default_factory=list)


class ResourceID:
    context = "authored"
    name = "source"
    version = "1"

    def url(self) -> str:
        return "resource://authored/source?version=1"


class SourceSubstance:
    resource_id = ResourceID()
    active_output = "scalar"
    image_outputs: ClassVar[list[str]] = ["scalar"]
    resolution = SimpleNamespace(mode=Mode.Auto, value=(128, 128), log2_offset=0)

    def __init__(self, world: World) -> None:
        self.world = world
        self.image_inputs = list(world.inputs)
        world.sources.append(self)

    def get_parameters(self) -> dict[str, Any]:
        return {"signed": -0.0, "integer": 1, "double": 1.0}

    def get_source(self, identifier: str) -> None:
        self.world.input_reads.append(identifier)


class Node:
    def __init__(self, world: World, uid: int, kind: NodeType, parent: int | None = None) -> None:
        self.world, self.identifier, self.kind, self.parent_id = world, uid, kind, parent

    def uid(self) -> int:
        return self.identifier

    def get_type(self) -> NodeType:
        return self.kind

    def get_name(self) -> str:
        return "same name"

    def is_visible(self) -> bool:
        return True

    def get_parent(self) -> Node | None:
        return self.world.resolve(self.parent_id) if self.parent_id is not None else None

    def is_in_mask_stack(self) -> bool:
        return False

    def get_blending_mode(self, channel: ChannelType) -> Mode:
        return Mode.Normal

    def get_opacity(self, channel: ChannelType) -> float:
        return 1.0

    def get_source(self, channel: ChannelType | None = None) -> SourceSubstance:
        return SourceSubstance(self.world)


class LayerNode(Node):
    def has_mask(self) -> bool:
        return False

    def content_effects(self) -> list[Node]:
        return [self.world.resolve(30)] if self.identifier == 20 else []

    def mask_effects(self) -> list[Node]:
        return []

    def get_geometry_mask(self) -> GeometryMaskMeshParams:
        return GeometryMaskMeshParams()


class FillLayerNode(LayerNode):
    source_mode = Mode.Split
    active_channels: ClassVar[set[ChannelType]] = {ChannelType.User0}

    def get_projection_mode(self) -> Mode:
        return Mode.UV

    def get_projection_parameters(self) -> UVProjectionParams:
        return UVProjectionParams()

    def is_symmetry_enabled(self) -> bool:
        raise ValueError("symmetry requires 3D projection")

    def get_symmetry_parameters(self) -> None:
        raise ValueError("symmetry requires 3D projection")


class FilterEffectNode(Node):
    active_channels: ClassVar[set[ChannelType]] = {ChannelType.User0}


class GroupLayerNode(LayerNode):
    pass


class World:
    def __init__(self) -> None:
        self.setup = False
        self.inputs: list[str] = []
        self.sources: list[SourceSubstance] = []
        self.input_reads: list[str] = []
        self.lookups: list[int] = []
        self.nodes = {
            10: LayerNode(self, 10, NodeType.PaintLayer),
            20: FillLayerNode(self, 20, NodeType.FillLayer),
            30: FilterEffectNode(self, 30, NodeType.FilterEffect, 20),
        }
        self.channel = SimpleNamespace(
            format=lambda: Mode.L32F,
            bit_depth=lambda: 32,
            is_color=lambda: False,
            is_floating=lambda: True,
            label=lambda: "User 0",
        )
        self.stack = SimpleNamespace(
            name=lambda: "stack", all_channels=lambda: {ChannelType.User0: self.channel}
        )
        self.texture_set = SimpleNamespace(
            name=lambda: "set", get_resolution=lambda: Resolution(), all_stacks=lambda: [self.stack]
        )

    def resolve(self, uid: int) -> Node:
        self.lookups.append(uid)
        return copy(self.nodes[uid])

    def roots(self, stack: Any) -> list[Node]:
        return [self.resolve(uid) for uid in ([20, 10] if self.setup else [10])]


class Session:
    def __init__(self, world: World) -> None:
        dummy = type("Unused", (), {})
        painter = SimpleNamespace(
            project=SimpleNamespace(
                get_uuid=lambda: "authored-project",
                last_imported_mesh_path=lambda: "authored-plane.obj",
                is_open=lambda: True,
                needs_saving=lambda: world.setup,
            ),
            textureset=SimpleNamespace(all_texture_sets=lambda: [world.texture_set]),
            layerstack=SimpleNamespace(
                Node=Node,
                LayerNode=LayerNode,
                FillLayerNode=FillLayerNode,
                FilterEffectNode=FilterEffectNode,
                GroupLayerNode=GroupLayerNode,
                get_node_by_uid=world.resolve,
                get_root_layer_nodes=world.roots,
            ),
            source=SimpleNamespace(
                SourceSubstance=SourceSubstance, SourceBitmap=dummy, SourceUniformColor=dummy
            ),
            resource=SimpleNamespace(ResourceID=ResourceID, Shelf=dummy, Resource=dummy),
            colormanagement=SimpleNamespace(Color=dummy),
        )
        namespace: dict[str, Any] = {
            "__name__": "authored_probe_extension",
            "Any": Any,
            "substance_painter": painter,
            "enum": enum,
            "dataclasses": dataclasses,
            "json": json,
            "datetime": __import__("datetime"),
            "OPERATIONS": {},
            "PROBE_NODES": {3: world.nodes[20], 6: world.nodes[30]},
            "channel_arg": lambda args: ChannelType[args["channel"]],
        }
        # Use the existing serializer/resolver/source getter bodies, not an imitation of their
        # nested dataclass or ResourceID shapes. The fake objects implement the actual API calls.
        path = PAINTER_FILTER_CONTEXT.with_name("painter_probes.py")
        parsed = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            "class_name",
            "raised",
            "describe",
            "resolve",
            "fresh",
            "substance_source",
            "substance_read",
            "child_lists",
        }
        functions: list[ast.stmt] = [
            node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
        self.probes = namespace
        self.globals: dict[str, Any] = {"uzp_probes": namespace}
        exec(extension_code(PAINTER_FILTER_CONTEXT.read_text(encoding="utf-8")), self.globals)

    def call(self, operation: str, **args: Any) -> Any:
        return self.probes["OPERATIONS"][operation](args)


def frames() -> tuple[World, Session, list[dict[str, Any]]]:
    world = World()
    session = Session(world)
    result = [context_readback(session, "after-create")]
    world.setup = True
    result += [context_readback(session, boundary) for boundary in tuple(CONDITIONS)[1:]]
    return world, session, result


def test_real_extension_dispatch_preserves_types_getters_and_provenance() -> None:
    world, session, contexts = frames()
    assert "collect_filter_context" not in session.probes
    assert session.probes["OPERATIONS"] is session.globals["uzp_filter_context"]["OPERATIONS"]
    for frame in contexts:
        validate_census(frame)
    outputs = contexts[1]["outputs"]
    params = next(row["value"] for row in outputs if row["call"] == SOURCE + "get_parameters")
    assert type(params["integer"]) is int and type(params["double"]) is float
    assert math.copysign(1, params["signed"]) == -1
    projection = next(
        row["value"] for row in outputs if row["call"].endswith(".get_projection_parameters")
    )
    assert (
        projection["class"] == "UVProjectionParams"
        and "class" not in projection["uv_transformation"]
    )
    symmetry = [row for row in outputs if "symmetry" in row["call"]]
    assert len(symmetry) == 2 and all(
        row["value"] is None and row["raised"]["type"] == "ValueError" for row in symmetry
    )
    assert len({id(source) for source in world.sources}) == len(world.sources)
    assert world.lookups.count(20) >= 24 and world.lookups.count(30) >= 24
    assert not any(row["args"]["selector"].get("role") for row in contexts[0]["outputs"])


def test_nonempty_input_slots_are_read_then_refused_as_unsupported() -> None:
    world = World()
    world.setup, world.inputs = True, ["input-a"]
    session = Session(world)
    frame = context_readback(session, "pre16-r1")
    assert world.input_reads == ["input-a", "input-a"]
    assert sum(row["call"] == SOURCE + "get_source" for row in frame["outputs"]) == 2
    with pytest.raises(ContextRefused, match="image input bindings"):
        validate_census(frame)


def test_parent_uid_is_not_inferred_from_matching_name_and_type() -> None:
    _, _, contexts = frames()
    frame = contexts[1]
    parent = next(
        row
        for row in frame["outputs"]
        if row["call"] == NODE + "uid" and row["args"]["selector"].get("parent")
    )
    parent["value"] = 999
    with pytest.raises(ContextRefused, match="parent UID"):
        validate_census(frame)


def test_unknown_geometry_is_preserved_and_never_relabelled_as_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclasses.dataclass
    class GeometryMaskUVTileParams:
        tiles: list[int] = dataclasses.field(default_factory=lambda: [1001])

    monkeypatch.setattr(LayerNode, "get_geometry_mask", lambda self: GeometryMaskUVTileParams())
    frame = context_readback(Session(World()), "after-create")
    geometry = next(
        row["value"] for row in frame["outputs"] if row["call"].endswith(".get_geometry_mask")
    )
    assert geometry["class"].endswith("GeometryMaskUVTileParams")
    assert geometry["tiles"] == [1001]
    with pytest.raises(ContextRefused, match="geometry serializer fields"):
        validate_census(frame)


def test_inactive_filter_channel_error_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    world.setup = True
    world.stack.all_channels = lambda: {
        ChannelType.User0: world.channel,
        ChannelType.User1: world.channel,
    }

    def opacity(self: Node, channel: ChannelType) -> float:
        if self.kind is NodeType.FilterEffect and channel is ChannelType.User1:
            raise ValueError("inactive channel")
        return 1.0

    monkeypatch.setattr(Node, "get_opacity", opacity)
    frame = context_readback(Session(world), "after-setup6")
    validate_census(frame)
    row = next(
        row
        for row in frame["outputs"]
        if row["call"] == NODE + "get_opacity"
        and row["args"]["selector"].get("path") == [["Root", 0], ["Content", 0]]
        and row["args"]["parameters"] == {"channel": "User1"}
    )
    assert row["value"] is None and row["raised"]["type"] == "ValueError"
    active = next(
        row for row in frame["outputs"] if row["call"].endswith("FilterEffectNode.active_channels")
    )
    active["value"] = ["User1", "User0"]
    with pytest.raises(ContextRefused, match="active channels"):
        validate_census(frame)

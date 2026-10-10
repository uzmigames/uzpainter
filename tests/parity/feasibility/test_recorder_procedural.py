"""Recorder vocabulary of the procedural feasibility study (task 2.4): imported resources, mesh
maps, masks, generator effects, smart materials, substance parameters and their readbacks.

`painter_side.py` is executed against a minimal fake `substance_painter` package defined here
(only the documented members these operations use); no Painter is needed.
"""

from __future__ import annotations

import enum
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from tools.parity.feasibility.cases import cases
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import INPUT_ARGS, load_job
from tools.parity.recorder.session import PAINTER_SIDE


class Usage(enum.Enum):
    ENVIRONMENT = 1
    TEXTURE = 2
    GENERATOR = 3
    SMART_MATERIAL = 4


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


class MaskBackground(enum.Enum):
    Black = 0
    White = 1


class NodeStack(enum.Enum):
    Substack = 0
    Content = 1
    Mask = 2


class NodeType(enum.Enum):
    FillLayer = 1
    GeneratorEffect = 2
    GroupLayer = 3


class ChannelType(enum.Enum):
    BaseColor = 1
    SpecularRoughness = 2


@dataclass(frozen=True)
class ResourceID:
    context: str
    name: str

    @staticmethod
    def from_url(url: str) -> ResourceID:
        context, _, name = url[len("resource://") :].partition("/")
        return ResourceID(context, name)

    def url(self) -> str:
        return f"resource://{self.context}/{self.name}"


@dataclass
class Resource:
    rid: ResourceID
    title: str
    kinds: list[Usage]

    def identifier(self) -> ResourceID:
        return self.rid

    def gui_name(self) -> str:
        return self.title

    def usages(self) -> list[Usage]:
        return list(self.kinds)


@dataclass
class Property:
    data: Any
    widget: str

    def value(self) -> Any:
        return self.data

    def name(self) -> str:
        return "name"

    def short_name(self) -> str:
        return "short"

    def label(self) -> str:
        return "Label"

    def widget_type(self) -> str:
        return self.widget

    def enum_values(self) -> dict[str, int]:
        return {}

    def enum_value(self, label: str) -> int:
        raise KeyError(label)

    def properties(self) -> dict[str, Any]:
        return {"min": 0, "max": 1}


@dataclass
class SourceSubstance:
    resource_id: ResourceID
    parameters: dict[str, Any] = field(default_factory=lambda: {"$randomseed": 0, "level": 0.5})
    image_inputs: list[str] = field(default_factory=list)
    image_outputs: list[str] = field(default_factory=lambda: ["output"])

    def set_parameters(self, values: dict[str, Any]) -> None:
        for name, value in values.items():
            if name not in self.parameters or isinstance(value, bool | list):
                raise ValueError(f"bad parameter {name}={value!r}")
            self.parameters[name] = value

    def get_properties(self) -> dict[str, Property]:
        return {name: Property(value, "Slider") for name, value in self.parameters.items()}

    def get_preset_list(self) -> list[str]:
        return []


class SourceUniformColor:
    def get_color(self) -> Any:
        raise AssertionError("not used")


@dataclass
class Node:
    kind: NodeType
    title: str
    source: SourceSubstance | None = None
    mask: MaskBackground | None = None
    children: list[Node] = field(default_factory=list)
    mask_children: list[Node] = field(default_factory=list)

    def get_type(self) -> NodeType:
        return self.kind

    def get_name(self) -> str:
        return self.title

    def add_mask(self, background: MaskBackground) -> None:
        if self.mask is not None:
            raise ValueError("a mask is already set")
        self.mask = background

    def get_source(self, channel: Any = None) -> Any:
        return self.source

    @property
    def active_channels(self) -> set[ChannelType]:
        return {ChannelType.SpecularRoughness} if self.kind == NodeType.FillLayer else set()

    def sub_layers(self) -> list[Node]:
        return list(self.children)

    def content_effects(self) -> list[Node]:
        return []

    def mask_effects(self) -> list[Node]:
        return list(self.mask_children)


@dataclass
class Position:
    node: Node
    stack: NodeStack | None = None


class World:
    def __init__(self) -> None:
        self.mesh_maps: dict[MeshMapUsage, ResourceID | None] = {}
        self.shelf = [
            Resource(ResourceID("starter_assets", "mg_position"), "Position", [Usage.GENERATOR]),
            Resource(ResourceID("starter_assets", "pos_tex"), "Position", [Usage.TEXTURE]),
            Resource(ResourceID("starter_assets", "twin_a"), "Twin", [Usage.GENERATOR]),
            Resource(ResourceID("other_shelf", "twin_b"), "Twin", [Usage.GENERATOR]),
            Resource(
                ResourceID("starter_assets", "sm_leather"),
                "Leather Damaged",
                [Usage.SMART_MATERIAL],
            ),
        ]
        self.queries: list[str] = []
        self.modules = self.build()

    def build(self) -> dict[str, types.ModuleType]:
        world = self

        class TextureSet:
            def name(self) -> str:
                return "uzp_fixture"

            def set_mesh_map_resource(self, usage: MeshMapUsage, rid: ResourceID | None) -> None:
                world.mesh_maps[usage] = rid

            def get_mesh_map_resource(self, usage: MeshMapUsage) -> ResourceID | None:
                return world.mesh_maps.get(usage)

            @staticmethod
            def from_name(name: str) -> TextureSet:
                return TextureSet()

        class InsertPosition:
            @staticmethod
            def above_node(node: Node) -> Position:
                return Position(node)

            @staticmethod
            def below_node(node: Node) -> Position:
                return Position(node)

            @staticmethod
            def inside_node(node: Node, stack: NodeStack) -> Position:
                return Position(node, stack)

        def insert_generator_effect(position: Position, rid: ResourceID) -> Node:
            if position.stack != NodeStack.Mask or position.node.mask is None:
                raise ValueError("generator needs a mask stack of a layer with a mask")
            node = Node(NodeType.GeneratorEffect, rid.name, SourceSubstance(rid))
            position.node.mask_children.append(node)
            return node

        def insert_smart_material(position: Position, rid: ResourceID) -> Node:
            fill = Node(NodeType.FillLayer, "inner fill", SourceSubstance(rid))
            fill.mask = MaskBackground.White
            fill.mask_children.append(
                Node(NodeType.GeneratorEffect, "inner generator", SourceSubstance(rid))
            )
            return Node(NodeType.GroupLayer, rid.name, children=[fill])

        def search(query: str) -> list[Resource]:
            world.queries.append(query)
            return [r for r in world.shelf if query.lower() in r.title.lower()]

        def import_project_resource(path: str, usage: Usage) -> Resource:
            stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            return Resource(ResourceID("project0", stem), stem, [usage])

        def module(name: str, **members: Any) -> types.ModuleType:
            mod = types.ModuleType(name)
            for key, value in members.items():
                setattr(mod, key, value)
            return mod

        modules = {
            "substance_painter.application": module("substance_painter.application"),
            "substance_painter.baking": module("substance_painter.baking"),
            "substance_painter.colormanagement": module(
                "substance_painter.colormanagement", Color=type("Color", (), {})
            ),
            "substance_painter.display": module("substance_painter.display"),
            "substance_painter.export": module("substance_painter.export"),
            "substance_painter.js": module("substance_painter.js"),
            "substance_painter.layerstack": module(
                "substance_painter.layerstack",
                MaskBackground=MaskBackground,
                NodeStack=NodeStack,
                InsertPosition=InsertPosition,
                insert_generator_effect=insert_generator_effect,
                insert_smart_material=insert_smart_material,
                GroupLayerNode=type("GroupLayerNode", (), {}),
            ),
            "substance_painter.project": module("substance_painter.project"),
            "substance_painter.resource": module(
                "substance_painter.resource",
                Usage=Usage,
                ResourceID=ResourceID,
                search=search,
                import_project_resource=import_project_resource,
            ),
            "substance_painter.source": module(
                "substance_painter.source",
                SourceSubstance=SourceSubstance,
                SourceUniformColor=SourceUniformColor,
            ),
            "substance_painter.textureset": module(
                "substance_painter.textureset",
                TextureSet=TextureSet,
                MeshMapUsage=MeshMapUsage,
                ChannelType=ChannelType,
                all_texture_sets=lambda: [TextureSet()],
            ),
            "substance_painter.ui": module("substance_painter.ui"),
        }
        root = module("substance_painter")
        for name, mod in modules.items():
            setattr(root, name.split(".", 1)[1], mod)
        modules["substance_painter"] = root
        return modules


@contextmanager
def installed(world: World) -> Iterator[None]:
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


@pytest.fixture
def side() -> Iterator[tuple[World, dict[str, Any]]]:
    world = World()
    namespace: dict[str, Any] = {"__name__": "painter_side_under_test"}
    with installed(world):
        exec(
            compile(PAINTER_SIDE.read_text(encoding="utf-8"), "painter_side.py", "exec"), namespace
        )
        yield world, namespace


def apply(namespace: dict[str, Any], step: int, call: str, **args: Any) -> Any:
    resolved = args.pop("resolved", {})
    return namespace["apply_step"]({"step": step, "call": call, "args": args, "resolved": resolved})


def test_imported_resource_becomes_the_mesh_map_and_reads_back(
    side: tuple[World, dict[str, Any]],
) -> None:
    world, ns = side
    result = apply(
        ns,
        2,
        ps.IMPORT_RESOURCE,
        input="curv",
        usage="TEXTURE",
        resolved={"input": "C:/work/inputs/sphere-curvature.png"},
    )
    assert result["resource_url"] == "resource://project0/sphere-curvature"
    apply(ns, 3, ps.SET_MESH_MAP, usage="Curvature", resource_step=2)
    assert world.mesh_maps[MeshMapUsage.Curvature] == ResourceID("project0", "sphere-curvature")
    readback = ns["readback"]({"call": ps.GET_MESH_MAP, "args": {"usage": "Curvature"}})
    assert readback == {"uzp_fixture": "resource://project0/sphere-curvature"}
    assert ns["readback"]({"call": ps.GET_MESH_MAP, "args": {"usage": "AO"}}) == {
        "uzp_fixture": None
    }


def test_generator_goes_into_the_mask_found_by_exact_name_and_usage(
    side: tuple[World, dict[str, Any]],
) -> None:
    world, ns = side
    fill = Node(NodeType.FillLayer, "top")
    ns["NODES"][5] = fill
    apply(ns, 6, ps.ADD_MASK, node_step=5, background="Black")
    assert fill.mask == MaskBackground.Black
    result = apply(
        ns,
        7,
        ps.INSERT_GENERATOR,
        inside_step=5,
        stack="Mask",
        resource_name="Position",
        resource_usage="GENERATOR",
    )
    assert result["resource_url"] == "resource://starter_assets/mg_position"
    assert fill.mask_children == [ns["NODES"][7]]
    assert world.queries == ["Position"]


def test_resource_lookup_refuses_ambiguous_and_missing_names(
    side: tuple[World, dict[str, Any]],
) -> None:
    _, ns = side
    with pytest.raises(ValueError, match="2 GENERATOR resources named 'Twin'"):
        ns["find_resource"]({"resource_name": "Twin", "resource_usage": "GENERATOR"})
    found = ns["find_resource"](
        {"resource_name": "Twin", "resource_usage": "GENERATOR", "resource_context": "other_shelf"}
    )
    assert found.url() == "resource://other_shelf/twin_b"
    with pytest.raises(ValueError, match="0 SMART_MATERIAL resources named 'Position'"):
        ns["find_resource"]({"resource_name": "Position", "resource_usage": "SMART_MATERIAL"})
    by_url = ns["find_resource"]({"resource": "resource://starter_assets/x"})
    assert by_url.url() == "resource://starter_assets/x"


def test_set_parameters_reaches_the_generator_source_and_reads_back(
    side: tuple[World, dict[str, Any]],
) -> None:
    _, ns = side
    fill = Node(NodeType.FillLayer, "top", mask=MaskBackground.Black)
    ns["NODES"][5] = fill
    apply(
        ns,
        7,
        ps.INSERT_GENERATOR,
        inside_step=5,
        stack="Mask",
        resource="resource://starter_assets/mg_position",
    )
    apply(ns, 8, ps.SET_PARAMETERS, node_step=7, parameter="$randomseed", value=1)
    apply(ns, 9, ps.SET_PARAMETERS, node_step=7, parameter="level", value=1.0)
    described = ns["readback"]({"call": ps.GET_GENERATOR_SOURCE, "args": {"node_step": 7}})
    assert described["resource_url"] == "resource://starter_assets/mg_position"
    assert described["properties"]["$randomseed"]["value"] == 1
    assert described["properties"]["level"]["value"] == 1.0
    assert described["image_outputs"] == ["output"]


def test_smart_material_structure_readback_walks_layers_and_effects(
    side: tuple[World, dict[str, Any]],
) -> None:
    _, ns = side
    ns["NODES"][14] = Node(NodeType.FillLayer, "base")
    apply(
        ns,
        18,
        ps.INSERT_SMART_MATERIAL,
        above_step=14,
        resource_name="Leather Damaged",
        resource_usage="SMART_MATERIAL",
    )
    structure = ns["readback"]({"call": ps.GET_SUB_LAYERS, "args": {"node_step": 18}})
    assert structure["type"] == "GroupLayer"
    (layer,) = structure["sub_layers"]
    assert layer["type"] == "FillLayer"
    assert layer["sources"]["SpecularRoughness"]["resource_url"].endswith("sm_leather")
    assert layer["mask_effects"][0]["type"] == "GeneratorEffect"


def test_close_forgets_imported_resources(side: tuple[World, dict[str, Any]]) -> None:
    world, ns = side
    setattr(world.modules["substance_painter.project"], "is_open", lambda: False)  # noqa: B010
    apply(ns, 2, ps.IMPORT_RESOURCE, input="ao", usage="TEXTURE", resolved={"input": "C:/w/ao.png"})
    assert ns["RESOURCES"]
    ns["close_project"]({})
    assert ns["RESOURCES"] == {}


def test_study_jobs_load_with_readbacks_of_every_new_step() -> None:
    assert INPUT_ARGS[ps.IMPORT_RESOURCE] == "input"
    for case in cases():
        job = load_job(case.manifest_path)
        calls = [spec["call"] for spec in job.readback_specs()]
        assert calls.count(ps.GET_MESH_MAP) == 6
        if case.asset.usage == "GENERATOR":
            assert ps.GET_GENERATOR_SOURCE in calls
        else:
            assert ps.GET_SUB_LAYERS in calls
